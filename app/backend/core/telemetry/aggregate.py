"""Pure aggregation: folding a day's rows into a rollup, merging rollups over a range, and turning
the result into the dashboard payload. No I/O -- everything here is a function of its arguments,
which is what makes the concurrency story work.

**Why rollups are safe with 10 replicas.** A rollup is a pure function of a *closed, immutable* day.
Two replicas that fold the same day read the same rows and emit byte-identical JSON, so
last-writer-wins is a no-op rather than a race. That is only true if nothing in the folded body
varies per fold -- so `fold_day` contains no timestamps and no iteration-order dependence, and the
store adds its `foldedAt` stamp *outside* the deterministic payload.

**Why histograms and not stored percentiles.** Percentiles are not mergeable: you cannot average a
p95. Histograms are, element-wise, so p50/p95 over any chatbot and any date range come from merging
buckets and interpolating inside the one that contains the quantile. The edges are fixed and
log-spaced, so a bucket spans `[a, a*RATIO)` and a quantile landing in it is known only to within the
**full bucket width** -- 15%, not half that. The API reports that number rather than a flattering one.
"""

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from core.telemetry.records import (
    ALL_STATUSES,
    PATH_UNKNOWN,
    STATUS_ABORTED,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_REJECTED,
    UNATTRIBUTED,
)

ROLLUP_SCHEMA = 1

# 20 ms base, ratio 1.15, 72 buckets -> the top edge lands near 412 s, comfortably past any real
# turn; anything beyond goes into the overflow bucket rather than distorting the last real one.
HISTOGRAM_BASE_MS = 20.0
HISTOGRAM_RATIO = 1.15
HISTOGRAM_BUCKETS = 72
HISTOGRAM_OVERFLOW = HISTOGRAM_BUCKETS
# One bucket wide, because interpolation inside a bucket cannot do better than its width.
MAX_RELATIVE_ERROR = round(HISTOGRAM_RATIO - 1.0, 4)

# Below this many samples an interpolated percentile says more about the bucket edges than about the
# data, so the API omits it and the UI shows the count instead of a confident-looking number.
MIN_SAMPLES_FOR_PERCENTILE = 20

LOG_RATIO = math.log(HISTOGRAM_RATIO)


def bucket_index(duration_ms: float) -> int:
    if duration_ms is None or duration_ms <= 0:
        return 0
    if duration_ms < HISTOGRAM_BASE_MS:
        return 0
    index = int(math.floor(math.log(duration_ms / HISTOGRAM_BASE_MS) / LOG_RATIO))
    if index >= HISTOGRAM_BUCKETS:
        return HISTOGRAM_OVERFLOW
    return max(0, index)


def bucket_bounds(index: int) -> tuple[float, float]:
    """`[from, to)` in milliseconds. The overflow bucket is open-ended, reported as infinity."""
    if index >= HISTOGRAM_OVERFLOW:
        return HISTOGRAM_BASE_MS * (HISTOGRAM_RATIO**HISTOGRAM_BUCKETS), float("inf")
    low = 0.0 if index == 0 else HISTOGRAM_BASE_MS * (HISTOGRAM_RATIO**index)
    high = HISTOGRAM_BASE_MS * (HISTOGRAM_RATIO ** (index + 1))
    return low, high


def empty_histogram() -> dict[str, int]:
    return {}


def add_to_histogram(histogram: dict[str, int], duration_ms: float) -> None:
    key = str(bucket_index(duration_ms))
    histogram[key] = histogram.get(key, 0) + 1


def merge_histograms(target: dict[str, int], source: dict[str, Any]) -> dict[str, int]:
    """Element-wise, and therefore associative and commutative -- the property the whole range-query
    story depends on."""
    for key, count in (source or {}).items():
        try:
            value = int(count)
        except (TypeError, ValueError):
            continue
        target[str(key)] = target.get(str(key), 0) + value
    return target


def histogram_total(histogram: dict[str, Any]) -> int:
    total = 0
    for count in (histogram or {}).values():
        try:
            total += int(count)
        except (TypeError, ValueError):
            continue
    return total


def percentile_from_histogram(histogram: dict[str, Any], quantile: float) -> Optional[float]:
    """Linear interpolation inside the bucket that contains the quantile.

    Returns None below `MIN_SAMPLES_FOR_PERCENTILE`, and None for the open-ended overflow bucket,
    where there is no upper edge to interpolate against and any number would be invented.
    """
    total = histogram_total(histogram)
    if total < MIN_SAMPLES_FOR_PERCENTILE:
        return None

    target = quantile * total
    cumulative = 0
    for index in sorted((int(key) for key in histogram if str(key).lstrip("-").isdigit())):
        count = int(histogram[str(index)])
        if cumulative + count < target:
            cumulative += count
            continue
        low, high = bucket_bounds(index)
        if math.isinf(high):
            return low
        if count <= 0:
            return low
        fraction = (target - cumulative) / count
        return low + (high - low) * max(0.0, min(1.0, fraction))
    return None


def histogram_display_buckets(histogram: dict[str, Any]) -> list[dict[str, Any]]:
    """Fold the 72 storage buckets into a dozen human-readable ones. Nobody reads a 72-bar chart, and
    the storage resolution exists for percentile accuracy, not for display."""
    edges = [0, 1000, 2000, 3000, 5000, 8000, 12000, 20000, 30000, 45000, 60000, 90000]
    counts = [0] * (len(edges) + 1)
    for key, raw_count in (histogram or {}).items():
        try:
            index = int(key)
            count = int(raw_count)
        except (TypeError, ValueError):
            continue
        low, high = bucket_bounds(index)
        midpoint = low if math.isinf(high) else (low + high) / 2
        slot = len(edges)
        for position, edge in enumerate(edges):
            if midpoint < edge:
                slot = position
                break
        counts[slot] += count

    buckets: list[dict[str, Any]] = []
    for position, count in enumerate(counts):
        low = 0 if position == 0 else edges[position - 1]
        high = edges[position] if position < len(edges) else None
        buckets.append({"fromMs": low, "toMs": high, "count": count})
    return buckets


def new_turn_cell() -> dict[str, Any]:
    return {
        "requests": 0,
        "tokensIn": 0,
        "tokensOut": 0,
        "tokensReasoning": 0,
        "tokensCached": 0,
        "costMicros": 0,
        "unpricedCount": 0,
        "msSum": 0,
        "msMax": 0,
        "hist": {},
    }


def new_step_cell() -> dict[str, Any]:
    return {
        "calls": 0,
        "tokensIn": 0,
        "tokensOut": 0,
        "msSum": 0,
        "msMax": 0,
        "hist": {},
    }


def accumulate_turn(cell: dict[str, Any], row: dict[str, Any]) -> None:
    cell["requests"] += 1
    cell["tokensIn"] += int(row.get("tokensIn") or 0)
    cell["tokensOut"] += int(row.get("tokensOut") or 0)
    cell["tokensReasoning"] += int(row.get("tokensReasoning") or 0)
    cell["tokensCached"] += int(row.get("tokensCached") or 0)
    cost = row.get("estCostMicros")
    if cost is None:
        cell["unpricedCount"] += 1
    else:
        cell["costMicros"] += int(cost)
    duration = int(row.get("durationMs") or 0)
    cell["msSum"] += duration
    cell["msMax"] = max(cell["msMax"], duration)
    add_to_histogram(cell["hist"], duration)


def fold_day(day: str, rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """One day's rows -> the deterministic rollup body.

    Deterministic by construction: every mapping is emitted as a list sorted by its key tuple, and
    nothing time-dependent is read. Feeding the same rows in a different order must produce a
    byte-identical result -- that is what makes concurrent folds by different replicas safe, and it
    is asserted by a shuffle test.
    """
    turns: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    steps: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    errors: dict[str, int] = {}
    row_count = 0

    for row in rows:
        row_count += 1
        chatbot = row.get("chatbot") or UNATTRIBUTED
        model = row.get("model") or ""
        path = row.get("path") or PATH_UNKNOWN
        status = row.get("status") or STATUS_OK

        turn_key = (chatbot, model, path, status)
        accumulate_turn(turns.setdefault(turn_key, new_turn_cell()), row)

        for step in row.get("steps") or []:
            step_key = (chatbot, path, str(step.get("name")), str(step.get("type")))
            cell = steps.setdefault(step_key, new_step_cell())
            cell["calls"] += 1
            cell["tokensIn"] += int(step.get("tokensIn") or 0)
            cell["tokensOut"] += int(step.get("tokensOut") or 0)
            duration = int(step.get("ms") or 0)
            cell["msSum"] += duration
            cell["msMax"] = max(cell["msMax"], duration)
            add_to_histogram(cell["hist"], duration)

        error_type = row.get("errorType")
        if error_type:
            errors[error_type] = errors.get(error_type, 0) + 1

    return {
        "schema": ROLLUP_SCHEMA,
        "day": day,
        "rowCount": row_count,
        "turns": [
            {"chatbot": key[0], "model": key[1], "path": key[2], "status": key[3], **value}
            for key, value in sorted(turns.items())
        ],
        "steps": [
            {"chatbot": key[0], "path": key[1], "step": key[2], "type": key[3], **value}
            for key, value in sorted(steps.items())
        ],
        "errors": [{"type": name, "count": errors[name]} for name in sorted(errors)],
    }


def rows_to_rollup(day: str, rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    return fold_day(day, rows)


def matches_filters(entry: dict[str, Any], filters: dict[str, Any]) -> bool:
    """OR within a facet, AND across facets."""
    for field, values in filters.items():
        if not values:
            continue
        value = entry.get(field)
        if field == "status" and value is None:
            value = STATUS_OK
        if value not in values:
            return False
    return True


def bucket_start(moment: datetime, granularity: str) -> datetime:
    moment = moment.astimezone(timezone.utc)
    if granularity == "hour":
        return moment.replace(minute=0, second=0, microsecond=0)
    if granularity == "week":
        day = moment.replace(hour=0, minute=0, second=0, microsecond=0)
        return day - timedelta(days=day.weekday())
    if granularity == "month":
        return moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


def bucket_label(moment: datetime, granularity: str) -> str:
    if granularity == "hour":
        return moment.strftime("%Y-%m-%dT%H:00Z")
    if granularity == "month":
        return moment.strftime("%Y-%m")
    return moment.strftime("%Y-%m-%d")


HOURLY_MAX_DAYS = 7
"""The widest range an explicit `hour` granularity is served for.

An hourly axis is the one granularity that cannot come from a rollup -- a daily rollup aggregates
each key across the whole day and cannot be split back apart -- so it costs one raw day listing per
day in the range, which is why `summarize` lifts its raw-day budget for it. `auto` never asks for
more than two days, but a caller can ask for any span, and an unclamped `range=all&granularity=hour`
would mean up to MAX_RANGE_DAYS listings to draw an axis of ~9,600 columns.

Seven days is what the one question an hourly axis answers actually needs -- "which hour of the day
is busy?" takes a full week to show a weekday pattern -- and is roughly where a column chart stops
being readable anyway. Kept in lockstep with HOURLY_MAX_RANGE_DAYS in `useTelemetryQuery.ts`, which
is what greys the Hourly control out; this clamp is the backstop for every other caller.
"""


def resolve_granularity(requested: Optional[str], day_span: int) -> str:
    """`auto` keeps the x axis readable: roughly 8-60 buckets whatever the range.

    An explicit granularity is honoured, with one exception: `hour` is clamped to `day` beyond
    HOURLY_MAX_DAYS, which is what bounds the raw listing an hourly range forces. The clamp is
    visible rather than silent -- the summary payload reports the requested and the resolved
    granularity separately, so the UI can say why the axis is not the one that was asked for.
    """
    if requested == "hour" and day_span > HOURLY_MAX_DAYS:
        return "day"
    if requested in {"hour", "day", "week", "month"}:
        return requested
    if day_span <= 2:
        return "hour"
    if day_span <= 62:
        return "day"
    if day_span <= 400:
        return "week"
    return "month"


class RangeAggregate:
    """Accumulates whatever the range planner feeds it -- rollup cells for closed days, raw rows for
    the live tail -- into one payload. The two sources produce identical cells by construction, so a
    range that spans both is not a special case."""

    def __init__(self, granularity: str):
        self.granularity = granularity
        self.series: dict[str, dict[str, Any]] = {}
        self.by_chatbot: dict[str, dict[str, Any]] = {}
        self.by_model: dict[str, dict[str, Any]] = {}
        self.by_path: dict[str, dict[str, Any]] = {}
        self.by_step: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.series_by_chatbot: dict[tuple[str, str], dict[str, Any]] = {}
        self.series_by_model: dict[tuple[str, str], dict[str, Any]] = {}
        self.errors: dict[str, dict[str, Any]] = {}
        self.latency: dict[str, int] = {}
        self.totals = new_turn_cell()
        self.status_counts: dict[str, int] = {status: 0 for status in ALL_STATUSES}
        self.unpriced_models: dict[str, int] = {}

    def merge_turn_cell(self, target: dict[str, Any], cell: dict[str, Any]) -> None:
        for field in ("requests", "tokensIn", "tokensOut", "tokensReasoning", "tokensCached", "costMicros", "unpricedCount", "msSum"):
            target[field] = target.get(field, 0) + int(cell.get(field, 0) or 0)
        target["msMax"] = max(target.get("msMax", 0), int(cell.get("msMax", 0) or 0))
        merge_histograms(target.setdefault("hist", {}), cell.get("hist") or {})

    def add_turn_cell(self, bucket: str, cell: dict[str, Any], *, chatbot: str, model: str, path: str, status: str) -> None:
        self.merge_turn_cell(self.totals, cell)
        self.status_counts[status] = self.status_counts.get(status, 0) + int(cell.get("requests", 0) or 0)
        merge_histograms(self.latency, cell.get("hist") or {})

        self.merge_turn_cell(self.series.setdefault(bucket, new_turn_cell()), cell)
        self.merge_turn_cell(self.by_chatbot.setdefault(chatbot, new_turn_cell()), cell)
        self.merge_turn_cell(self.by_path.setdefault(path, new_turn_cell()), cell)
        if model:
            self.merge_turn_cell(self.by_model.setdefault(model, new_turn_cell()), cell)
        self.merge_turn_cell(self.series_by_chatbot.setdefault((bucket, chatbot), new_turn_cell()), cell)
        if model:
            self.merge_turn_cell(self.series_by_model.setdefault((bucket, model), new_turn_cell()), cell)
        if status in {STATUS_ERROR, STATUS_ABORTED, STATUS_REJECTED}:
            entry = self.series.setdefault(bucket, new_turn_cell())
            entry[status] = entry.get(status, 0) + int(cell.get("requests", 0) or 0)

    def add_step_cell(self, cell: dict[str, Any], *, path: str, step: str, step_type: str) -> None:
        target = self.by_step.setdefault((path, step, step_type), new_step_cell())
        for field in ("calls", "tokensIn", "tokensOut", "msSum"):
            target[field] = target.get(field, 0) + int(cell.get(field, 0) or 0)
        target["msMax"] = max(target.get("msMax", 0), int(cell.get("msMax", 0) or 0))
        merge_histograms(target.setdefault("hist", {}), cell.get("hist") or {})

    def add_error(self, error_type: str, count: int, last_seen: Optional[str] = None, trace_id: Optional[str] = None) -> None:
        entry = self.errors.setdefault(error_type, {"type": error_type, "count": 0, "lastSeen": None, "exampleTraceId": None})
        entry["count"] += count
        if last_seen and (entry["lastSeen"] is None or last_seen > entry["lastSeen"]):
            entry["lastSeen"] = last_seen
            entry["exampleTraceId"] = trace_id or entry["exampleTraceId"]

    def note_unpriced(self, model: Optional[str], count: int = 1) -> None:
        if model:
            self.unpriced_models[model] = self.unpriced_models.get(model, 0) + count

    def percentiles(self, histogram: dict[str, Any]) -> dict[str, Optional[float]]:
        return {
            "p50Ms": percentile_from_histogram(histogram, 0.50),
            "p90Ms": percentile_from_histogram(histogram, 0.90),
            "p95Ms": percentile_from_histogram(histogram, 0.95),
            "p99Ms": percentile_from_histogram(histogram, 0.99),
        }

    def facet_rows(self, facet: dict[str, dict[str, Any]], key_name: str) -> list[dict[str, Any]]:
        total_cost = max(1, self.totals.get("costMicros", 0))
        total_requests = max(1, self.totals.get("requests", 0))
        rows: list[dict[str, Any]] = []
        for key, cell in facet.items():
            histogram = cell.get("hist") or {}
            rows.append(
                {
                    key_name: key,
                    "requests": cell.get("requests", 0),
                    "tokensIn": cell.get("tokensIn", 0),
                    "tokensOut": cell.get("tokensOut", 0),
                    "tokensReasoning": cell.get("tokensReasoning", 0),
                    "tokensCached": cell.get("tokensCached", 0),
                    "estCostMicros": cell.get("costMicros", 0),
                    "unpricedCount": cell.get("unpricedCount", 0),
                    "avgMs": int(cell.get("msSum", 0) / cell["requests"]) if cell.get("requests") else 0,
                    "maxMs": cell.get("msMax", 0),
                    "shareOfCost": cell.get("costMicros", 0) / total_cost,
                    "shareOfRequests": cell.get("requests", 0) / total_requests,
                    **self.percentiles(histogram),
                }
            )
        rows.sort(key=lambda row: (-row["estCostMicros"], -row["requests"], str(row[key_name])))
        return rows

    def series_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for bucket in sorted(self.series):
            cell = self.series[bucket]
            rows.append(
                {
                    "bucket": bucket,
                    "requests": cell.get("requests", 0),
                    "errors": cell.get(STATUS_ERROR, 0),
                    "aborted": cell.get(STATUS_ABORTED, 0),
                    "rejected": cell.get(STATUS_REJECTED, 0),
                    "estCostMicros": cell.get("costMicros", 0),
                    "tokensIn": cell.get("tokensIn", 0),
                    "tokensOut": cell.get("tokensOut", 0),
                    "avgMs": int(cell.get("msSum", 0) / cell["requests"]) if cell.get("requests") else 0,
                    **self.percentiles(cell.get("hist") or {}),
                }
            )
        return rows

    def split_series_rows(self, facet: dict[tuple[str, str], dict[str, Any]], key_name: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for (bucket, key) in sorted(facet):
            cell = facet[(bucket, key)]
            rows.append(
                {
                    "bucket": bucket,
                    key_name: key,
                    "requests": cell.get("requests", 0),
                    "estCostMicros": cell.get("costMicros", 0),
                    "tokensIn": cell.get("tokensIn", 0),
                    "tokensOut": cell.get("tokensOut", 0),
                }
            )
        return rows

    def step_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for (path, step, step_type), cell in self.by_step.items():
            calls = cell.get("calls", 0)
            rows.append(
                {
                    "path": path,
                    "step": step,
                    "type": step_type,
                    "calls": calls,
                    "avgMs": int(cell.get("msSum", 0) / calls) if calls else 0,
                    "totalMs": cell.get("msSum", 0),
                    "maxMs": cell.get("msMax", 0),
                    "tokensIn": cell.get("tokensIn", 0),
                    "tokensOut": cell.get("tokensOut", 0),
                    **self.percentiles(cell.get("hist") or {}),
                }
            )
        rows.sort(key=lambda row: (row["path"], -row["totalMs"], row["step"]))
        return rows

    def kpis(self) -> dict[str, Any]:
        requests = self.totals.get("requests", 0)
        errors = self.status_counts.get(STATUS_ERROR, 0)
        return {
            "requests": requests,
            "errors": errors,
            "aborted": self.status_counts.get(STATUS_ABORTED, 0),
            "rejected": self.status_counts.get(STATUS_REJECTED, 0),
            "errorRate": (errors / requests) if requests else 0.0,
            "estCostMicros": self.totals.get("costMicros", 0),
            "unpricedCount": self.totals.get("unpricedCount", 0),
            "tokensIn": self.totals.get("tokensIn", 0),
            "tokensOut": self.totals.get("tokensOut", 0),
            "tokensReasoning": self.totals.get("tokensReasoning", 0),
            "tokensCached": self.totals.get("tokensCached", 0),
            "avgMs": int(self.totals.get("msSum", 0) / requests) if requests else 0,
            **self.percentiles(self.latency),
        }


def ingest_rollup(aggregate: RangeAggregate, rollup: dict[str, Any], filters: dict[str, Any]) -> None:
    day = rollup.get("day") or ""
    try:
        day_moment = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return

    for cell in rollup.get("turns") or []:
        if not matches_filters(cell, filters):
            continue
        bucket = bucket_label(bucket_start(day_moment, aggregate.granularity), aggregate.granularity)
        aggregate.add_turn_cell(
            bucket,
            cell,
            chatbot=cell.get("chatbot") or UNATTRIBUTED,
            model=cell.get("model") or "",
            path=cell.get("path") or PATH_UNKNOWN,
            status=cell.get("status") or STATUS_OK,
        )
        if cell.get("unpricedCount"):
            aggregate.note_unpriced(cell.get("model"), int(cell.get("unpricedCount") or 0))

    step_filters = {field: values for field, values in filters.items() if field in {"chatbot", "path"}}
    for cell in rollup.get("steps") or []:
        if not matches_filters(cell, step_filters):
            continue
        aggregate.add_step_cell(
            cell,
            path=cell.get("path") or PATH_UNKNOWN,
            step=str(cell.get("step")),
            step_type=str(cell.get("type")),
        )

    for entry in rollup.get("errors") or []:
        aggregate.add_error(str(entry.get("type")), int(entry.get("count") or 0), last_seen=day)


def ingest_row(aggregate: RangeAggregate, row: dict[str, Any], filters: dict[str, Any]) -> None:
    if not matches_filters(row, filters):
        return

    started = row.get("startedAt")
    try:
        moment = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return
    bucket = bucket_label(bucket_start(moment, aggregate.granularity), aggregate.granularity)

    cell = new_turn_cell()
    accumulate_turn(cell, row)
    aggregate.add_turn_cell(
        bucket,
        cell,
        chatbot=row.get("chatbot") or UNATTRIBUTED,
        model=row.get("model") or "",
        path=row.get("path") or PATH_UNKNOWN,
        status=row.get("status") or STATUS_OK,
    )
    if row.get("estCostMicros") is None:
        aggregate.note_unpriced(row.get("model"))

    for step in row.get("steps") or []:
        step_cell = new_step_cell()
        step_cell["calls"] = 1
        step_cell["tokensIn"] = int(step.get("tokensIn") or 0)
        step_cell["tokensOut"] = int(step.get("tokensOut") or 0)
        step_cell["msSum"] = int(step.get("ms") or 0)
        step_cell["msMax"] = int(step.get("ms") or 0)
        add_to_histogram(step_cell["hist"], step_cell["msSum"])
        aggregate.add_step_cell(
            step_cell,
            path=row.get("path") or PATH_UNKNOWN,
            step=str(step.get("name")),
            step_type=str(step.get("type")),
        )

    if row.get("errorType"):
        aggregate.add_error(
            str(row.get("errorType")), 1, last_seen=str(started), trace_id=row.get("traceId")
        )
