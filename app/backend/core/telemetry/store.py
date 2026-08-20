"""Blob-backed persistence for turn records, plus the range planner the dashboard queries through.

The store owns its own container client off the blob manager's service client, exactly as
`ChatbotPromptStore` does. That is deliberate: extending `prepdocslib/blobmanager.py` would drag in
the `scripts/copy_prepdocslib.py` four-copy sync invariant for a class the Functions apps have no use
for, and `BlobManager.list_blobs` returns only name and last-modified -- no metadata, which is the
one thing this design depends on.

**Reads never download a body to draw a chart.** `list_blobs(include=["metadata"])` returns the
summary row inline with each listing entry, so a day of traffic costs one listing and zero
`download_blob` calls. A body is fetched only when an operator opens a single request.

**Closed days are served from rollups.** A day in the past (plus a grace window) is immutable, so it
is folded once into `rollups/daily/<day>.json` and every later query reads that ~14 KB blob instead
of re-listing thousands of entries. The fold is a pure function of the day, so ten replicas doing it
concurrently write identical bytes.
"""

import io
import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import ContentSettings

from core.telemetry import aggregate as agg
from core.telemetry import records as rec
from core.telemetry.pricing import PriceTable, parse_price_mapping

logger = logging.getLogger("telemetry")

# A day is not folded until it has been over for this long. `/chat/stream` sets
# `response.timeout = None`, so a turn can be held open by a slow reader for a very long time; the
# blob's day comes from the FINALIZE time, so a late finish lands in the day it finished, and this
# window only has to cover the gap between finalizing and the background write completing.
ROLLUP_GRACE_MINUTES = 60

# A single query never lists more than this many raw days. Without it a filter that matches nothing
# recent (`status=error, chatbot=knoll, all time`) walks every day in the store to fill one page.
MAX_RAW_DAYS_PER_QUERY = 3
MAX_SCAN_DAYS_PER_REQUEST_PAGE = 14
MAX_RANGE_DAYS = 400


class TelemetryStore:
    """One instance per app, held in `app.config`."""

    def __init__(self, blob_manager: Any, *, container: str = rec.TELEMETRY_CONTAINER):
        self.blob_manager = blob_manager
        self.container = container
        self.price_table = PriceTable()
        self.container_ready = False
        self.folded_days: set[str] = set()
        self.earliest_recorded_day: Optional[str] = None
        self.last_write_day: Optional[str] = None

    # ------------------------------------------------------------------ plumbing

    def get_container_client(self):
        return self.blob_manager.blob_service_client.get_container_client(self.container)

    async def ensure_container(self):
        container_client = self.get_container_client()
        if not self.container_ready:
            if not await container_client.exists():
                await container_client.create_container()
            self.container_ready = True
        return container_client

    # ------------------------------------------------------------------ writing

    async def write(self, record: rec.TurnRecord) -> Optional[str]:
        """Persist one finalized turn. Never raises: this runs as a background task on the request's
        app object, and an unhandled error there would be logged by the framework as a failed task
        for something the user must never be affected by."""
        try:
            container_client = await self.ensure_container()
            blob_name = record.blob_name()
            body = json.dumps(record.body(), ensure_ascii=False, sort_keys=False).encode("utf-8")
            await container_client.upload_blob(
                blob_name,
                io.BytesIO(body),
                overwrite=True,
                metadata=rec.encode_metadata(record),
                content_settings=ContentSettings(content_type="application/json"),
            )
            logger.debug("Telemetry recorded: %s", blob_name)
            await self.maybe_fold_previous_day(record.finalized_at or record.started_at)
            return blob_name
        except Exception:
            logger.exception("Failed to write telemetry record %s", record.trace_id)
            return None

    async def maybe_fold_previous_day(self, moment: datetime) -> None:
        """Fold yesterday on the first write of today.

        Without this, a rollup is only ever created when somebody happens to query that day -- and
        nobody queries day D again on day D+89. Folding on the day boundary means every day gets
        materialised exactly once, cheaply, whether or not anyone is looking.
        """
        try:
            today = rec.day_of(moment)
            if self.last_write_day == today:
                return
            self.last_write_day = today
            previous = (rec.to_utc(moment).date() - timedelta(days=1)).isoformat()
            if previous in self.folded_days:
                return
            # Gated on the SAME closure rule the query path uses, not merely on the date having
            # changed. A turn that finalizes at 23:59:59 has its blob written by a background task a
            # moment later, so folding the instant the clock rolls over would race that write and
            # silently drop it from the rollup -- permanently, because the day is then marked folded.
            if not self.day_is_closed(previous):
                return
            if await self.load_rollup(previous) is None:
                await self.fold_and_store_day(previous)
        except Exception:
            logger.exception("Failed to fold the previous telemetry day")

    # ------------------------------------------------------------------ reading

    async def list_day_rows(self, day: str, *, with_metadata: bool = True) -> list[dict[str, Any]]:
        """Every row for one day, oldest first. Degrades to an empty list rather than a 500 -- the
        dashboard showing fewer rows beats the dashboard showing an error."""
        if not rec.is_valid_day(day):
            return []
        try:
            container_client = self.get_container_client()
            if not await container_client.exists():
                return []
            rows: list[dict[str, Any]] = []
            include = ["metadata"] if with_metadata else None
            async for blob in container_client.list_blobs(
                name_starts_with=f"{rec.REQUESTS_PREFIX}/{day}/", include=include
            ):
                key = rec.parse_request_blob_name(getattr(blob, "name", "") or "")
                if key is None:
                    continue
                rows.append(rec.decode_metadata(key, getattr(blob, "metadata", None)))
            rows.sort(key=lambda row: (row["startedAt"], row["traceId"]))
            return rows
        except Exception:
            logger.exception("Failed to list telemetry rows for %s", day)
            return []

    async def read_request(self, blob_name: str) -> Optional[dict[str, Any]]:
        """One full record body.

        The caller passes a blob name that came from a listing, but it is re-parsed here before use:
        the name is round-tripped through the same codec that produced it, so a caller-supplied path
        cannot reach outside the requests prefix.
        """
        key = rec.parse_request_blob_name(blob_name)
        if key is None:
            return None
        try:
            container_client = self.get_container_client()
            blob_client = container_client.get_blob_client(key.blob_name)
            downloader = await blob_client.download_blob()
            payload = json.loads((await downloader.readall()).decode("utf-8"))
            return payload if isinstance(payload, dict) else None
        except ResourceNotFoundError:
            return None
        except Exception:
            logger.exception("Failed to read telemetry record %s", blob_name)
            return None

    # ------------------------------------------------------------------ rollups

    async def load_rollup(self, day: str) -> Optional[dict[str, Any]]:
        if not rec.is_valid_day(day):
            return None
        try:
            container_client = self.get_container_client()
            blob_client = container_client.get_blob_client(rec.rollup_blob_name(day))
            downloader = await blob_client.download_blob()
            payload = json.loads((await downloader.readall()).decode("utf-8"))
            if isinstance(payload, dict) and payload.get("day") == day:
                self.folded_days.add(day)
                return payload
            return None
        except ResourceNotFoundError:
            return None
        except Exception:
            logger.exception("Failed to read telemetry rollup for %s", day)
            return None

    async def fold_and_store_day(self, day: str) -> Optional[dict[str, Any]]:
        """Fold one closed day and write it. `foldedAt` is added on write, OUTSIDE the deterministic
        payload, so two replicas folding the same day still agree on every number.

        A day that recorded nothing is folded but NOT written: re-deriving it costs one listing of an
        empty prefix, which is cheaper than the read of the blob it would replace, so storing it is
        pure loss. It also stops a wide query from minting a rollup per data-less day -- an all-time
        request once wrote 400 of them for days that predate the product. The empty rollup is still
        returned, so the caller reads the day as empty rather than missing.
        """
        rows = await self.list_day_rows(day)
        rollup = agg.fold_day(day, rows)
        if not rollup.get("rowCount"):
            return rollup
        try:
            container_client = await self.ensure_container()
            body = dict(rollup)
            body["foldedAt"] = datetime.now(timezone.utc).isoformat()
            await container_client.upload_blob(
                rec.rollup_blob_name(day),
                io.BytesIO(json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")),
                overwrite=True,
                content_settings=ContentSettings(content_type="application/json"),
            )
            self.folded_days.add(day)
            logger.info("Folded telemetry rollup for %s (%d rows)", day, rollup["rowCount"])
        except Exception:
            logger.exception("Failed to store telemetry rollup for %s", day)
        return rollup

    def day_is_closed(self, day: str, now: Optional[datetime] = None) -> bool:
        now = now or datetime.now(timezone.utc)
        try:
            day_end = datetime.fromisoformat(day).replace(tzinfo=timezone.utc) + timedelta(days=1)
        except ValueError:
            return False
        return now >= day_end + timedelta(minutes=ROLLUP_GRACE_MINUTES)

    # ------------------------------------------------------------------ querying

    async def summarize(
        self,
        *,
        from_day: str,
        to_day: str,
        granularity: str,
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        """The range planner.

        Closed days come from rollups (one small read each, folded on demand and cached forever);
        the live tail comes from raw listings. An hourly range is always served from raw rows,
        because a daily rollup aggregates each key across the whole day and cannot be split by hour.
        The budget below is lifted for that case, and what bounds it is `resolve_granularity`, which
        clamps an hourly range to HOURLY_MAX_DAYS days before it ever reaches here.
        """
        days = day_range(from_day, to_day)
        aggregate = agg.RangeAggregate(granularity)
        rollup_days = 0
        raw_days = 0
        days_missing = 0
        days_empty = 0
        truncated = False

        hourly = granularity == "hour"
        raw_budget = MAX_RAW_DAYS_PER_QUERY if not hourly else len(days)

        for day in days:
            use_raw = hourly or not self.day_is_closed(day)
            if use_raw:
                if raw_budget <= 0:
                    truncated = True
                    days_missing += 1
                    continue
                raw_budget -= 1
                raw_days += 1
                rows = await self.list_day_rows(day)
                if not rows:
                    days_empty += 1
                for row in rows:
                    agg.ingest_row(aggregate, row, filters)
                continue

            rollup = await self.load_rollup(day)
            if rollup is None:
                rollup = await self.fold_and_store_day(day)
            if rollup is None:
                days_missing += 1
                continue
            if not rollup.get("rowCount"):
                days_empty += 1
            rollup_days += 1
            agg.ingest_rollup(aggregate, rollup, filters)

        return {
            "aggregate": aggregate,
            "partial": {
                "rollupDaysUsed": rollup_days,
                "rawDaysUsed": raw_days,
                "daysMissing": days_missing,
                "daysEmpty": days_empty,
                "truncated": truncated,
            },
        }

    async def list_requests(
        self,
        *,
        from_day: str,
        to_day: str,
        filters: dict[str, Any],
        query: str = "",
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> dict[str, Any]:
        """Newest first, paged by a last-key cursor.

        The cursor is `<day>|<ts>|<traceId>` rather than an offset: a turn finishing mid-page inserts
        a new row into the day being read, and an offset cursor would then skip or duplicate rows.
        A last-key cursor is stable under inserts.
        """
        days = list(reversed(day_range(from_day, to_day)))
        cursor_day, cursor_ts, cursor_trace = parse_cursor(cursor)
        if cursor_day:
            days = [day for day in days if day <= cursor_day]

        rows: list[dict[str, Any]] = []
        scanned = 0
        next_cursor: Optional[str] = None
        has_more = False
        needle = (query or "").strip().lower()

        for day in days:
            if scanned >= MAX_SCAN_DAYS_PER_REQUEST_PAGE:
                has_more = True
                break
            scanned += 1
            day_rows = await self.list_day_rows(day)
            for row in reversed(day_rows):
                if cursor_day and day == cursor_day:
                    marker = (row["startedAt"], row["traceId"])
                    if marker >= (cursor_ts or "", cursor_trace or ""):
                        continue
                if not agg.matches_filters(row, filters):
                    continue
                if needle and not row_matches_query(row, needle):
                    continue
                if len(rows) >= limit:
                    has_more = True
                    next_cursor = f"{rows[-1]['day']}|{rows[-1]['startedAt']}|{rows[-1]['traceId']}"
                    break
                rows.append(row)
            if has_more:
                break

        if has_more and next_cursor is None and rows:
            next_cursor = f"{rows[-1]['day']}|{rows[-1]['startedAt']}|{rows[-1]['traceId']}"

        return {"rows": rows, "cursor": next_cursor, "hasMore": has_more, "scannedDays": scanned}

    async def earliest_day(self) -> Optional[str]:
        """The first day recording produced anything, so the UI can draw a `recording started` rule
        and leave everything to its left blank instead of zero-filled.

        Memoized once it is known, because it is also what `range=all` resolves against and would
        otherwise cost a prefix listing on every summary, every request page and every export. The
        value only moves when the very first day is deleted, and retention here is forever; a None is
        deliberately not cached, so the first recorded day is picked up as soon as it exists.
        """
        if self.earliest_recorded_day is not None:
            return self.earliest_recorded_day
        try:
            container_client = self.get_container_client()
            if not await container_client.exists():
                return None
            days: list[str] = []
            async for prefix in container_client.walk_blobs(
                name_starts_with=f"{rec.REQUESTS_PREFIX}/", delimiter="/"
            ):
                name = getattr(prefix, "name", "") or ""
                candidate = name.rstrip("/").rsplit("/", 1)[-1]
                if rec.is_valid_day(candidate):
                    days.append(candidate)
            self.earliest_recorded_day = min(days) if days else None
            return self.earliest_recorded_day
        except Exception:
            logger.exception("Failed to determine the earliest telemetry day")
            return None

    # ------------------------------------------------------------------ pricing

    async def load_price_overrides(self) -> dict[str, Any]:
        try:
            container_client = self.get_container_client()
            blob_client = container_client.get_blob_client(rec.PRICING_BLOB)
            downloader = await blob_client.download_blob()
            payload = json.loads((await downloader.readall()).decode("utf-8"))
            return payload if isinstance(payload, dict) else {}
        except ResourceNotFoundError:
            return {}
        except Exception:
            logger.exception("Failed to read the telemetry price overrides")
            return {}

    async def save_price_overrides(self, prices: dict[str, Any], note: str = "") -> dict[str, Any]:
        container_client = await self.ensure_container()
        payload = {
            "prices": prices,
            "note": note,
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        }
        await container_client.upload_blob(
            rec.PRICING_BLOB,
            io.BytesIO(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")),
            overwrite=True,
            content_settings=ContentSettings(content_type="application/json"),
        )
        await self.refresh_price_table()
        return payload

    async def refresh_price_table(self) -> PriceTable:
        overrides = await self.load_price_overrides()
        self.price_table = PriceTable(override=parse_price_mapping(overrides.get("prices"), source="blob"))
        return self.price_table


def clamp_day_range(from_day: str, to_day: str) -> Optional[tuple[str, str]]:
    """The effective range, or None when it is unusable.

    A range wider than MAX_RANGE_DAYS keeps the most recent days and moves the START forward. It used
    to clamp the other way -- keeping the first MAX_RANGE_DAYS days and discarding everything after
    -- which is never the right reading of "too wide" on a dashboard of recent activity: an all-time
    request resolving to 2020-01-01 came back as a 400-day window ending in February 2021, so every
    tab drew an empty page. Exposed separately from `day_range` so a route can report the range it
    actually queried rather than the one it was asked for.
    """
    try:
        start = date.fromisoformat(from_day)
        end = date.fromisoformat(to_day)
    except ValueError:
        return None
    if end < start:
        return None
    if (end - start).days > MAX_RANGE_DAYS - 1:
        start = end - timedelta(days=MAX_RANGE_DAYS - 1)
    return start.isoformat(), end.isoformat()


def day_range(from_day: str, to_day: str) -> list[str]:
    """Inclusive, clamped. An inverted or absurd range is a caller error the route rejects, but the
    clamp here means it can never turn into an unbounded listing loop."""
    clamped = clamp_day_range(from_day, to_day)
    if clamped is None:
        return []
    start = date.fromisoformat(clamped[0])
    span = (date.fromisoformat(clamped[1]) - start).days
    return [(start + timedelta(days=offset)).isoformat() for offset in range(span + 1)]


def parse_cursor(cursor: Optional[str]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    if not cursor or not isinstance(cursor, str):
        return None, None, None
    parts = cursor.split("|")
    if len(parts) != 3 or not rec.is_valid_day(parts[0]):
        return None, None, None
    return parts[0], parts[1], parts[2]


def row_matches_query(row: dict[str, Any], needle: str) -> bool:
    for field in ("chatbot", "model", "traceId", "promptPreview", "path", "errorType"):
        value = row.get(field)
        if isinstance(value, str) and needle in value.lower():
            return True
    return False
