"""First-party LLM telemetry: the record codec, cost arithmetic, aggregation and the recorder.

The invariants pinned here are the ones whose failure would be silent -- a wrong number on a cost
dashboard looks exactly like a right one. In particular:

* a listing must come back in chronological order with several bots interleaved (the whole
  request-explorer design rests on it);
* reasoning tokens must not be added on top of completion tokens, and cached tokens must bill at the
  cached rate (either mistake roughly doubles or halves every reasoning-model turn);
* folding a day must be independent of the order the rows arrive in (this is what makes ten replicas
  computing the same rollup safe);
* an agentic turn must record NON-ZERO tokens (the blind spot this feature exists to close).
"""

import asyncio
import json
import random
import statistics
from datetime import date, datetime, timedelta, timezone

import pytest

from core.telemetry import aggregate as agg
from core.telemetry import records as rec
from core.telemetry import recorder as tr
from core.telemetry.agentic import record_agentic_activity_steps
from core.telemetry.pricing import PriceTable, compare_currencies, parse_price_mapping
from core.telemetry.store import MAX_RANGE_DAYS, TelemetryStore, day_range, parse_cursor

NOON = datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc)


class ChatUsage:
    """Shaped like `openai.types.CompletionUsage`."""

    def __init__(self, prompt: int, completion: int, cached: int = 0, reasoning: int = 0):
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.total_tokens = prompt + completion
        self.prompt_tokens_details = type("Details", (), {"cached_tokens": cached})()
        self.completion_tokens_details = type("Details", (), {"reasoning_tokens": reasoning})()


class EmbeddingUsage:
    """Shaped like `openai.types.CreateEmbeddingResponse.Usage` -- note it has NEITHER details
    attribute, which is exactly why the reader must not assume `CompletionUsage`."""

    prompt_tokens = 350
    total_tokens = 350


# --------------------------------------------------------------------------------------- blob names


def test_a_request_blob_name_round_trips():
    name = rec.request_blob_name(NOON, "bbsa", "a1b2c3d4e5f6a7b8")
    key = rec.parse_request_blob_name(name)
    assert key is not None
    assert (key.day, key.chatbot, key.trace_id, key.timestamp) == ("2026-08-19", "bbsa", "a1b2c3d4e5f6a7b8", NOON)


def test_the_timestamp_is_fixed_width_at_nineteen_characters():
    # Fixed width is what makes a lexicographic listing chronological; a variable-width stamp would
    # sort 9:00 after 10:00.
    assert len(rec.format_timestamp(NOON)) == 19
    assert len(rec.format_timestamp(NOON.replace(microsecond=1))) == 19


@pytest.mark.parametrize(
    "name",
    [
        "requests/2026-08-19/notatimestamp__bbsa__a1b2c3d4e5f6a7b8.json",
        "requests/notadate/20260819T120000000Z__bbsa__a1b2c3d4e5f6a7b8.json",
        "requests/2026-08-19/20260819T120000000Z__bbsa__NOTHEX.json",
        "requests/2026-08-19/extra/20260819T120000000Z__bbsa__a1b2c3d4e5f6a7b8.json",
        "requests/2026-08-19/20260819T120000000Z__bbsa.json",
        "rollups/daily/2026-08-19.json",
        "requests/2026-08-19/20260819T120000000Z__bbsa__a1b2c3d4e5f6a7b8.txt",
        # The folder must agree with the timestamp the filename encodes.
        "requests/2026-08-18/20260819T120000000Z__bbsa__a1b2c3d4e5f6a7b8.json",
        "",
        None,
    ],
)
def test_a_malformed_blob_name_is_rejected_rather_than_guessed(name):
    assert rec.parse_request_blob_name(name) is None


def test_a_day_listing_is_chronological_even_with_several_bots_interleaved():
    # The default request view is "all bots, newest first". A layout that put the chatbot before the
    # timestamp would order by bot and force a whole-day sort, so this is load-bearing.
    generator = random.Random(11)
    names = []
    for index in range(400):
        moment = NOON.replace(
            hour=generator.randrange(24), minute=generator.randrange(60), microsecond=generator.randrange(1000) * 1000
        )
        bot = generator.choice(["aaa", "zzz", "lemon", "bbsa"])
        names.append(rec.request_blob_name(moment, bot, "%016x" % generator.getrandbits(64)))

    timestamps = [rec.parse_request_blob_name(name).timestamp for name in sorted(names)]
    assert timestamps == sorted(timestamps)


def test_a_traversal_segment_cannot_survive_sanitising():
    # The sanitizer permits `.` and `-`, so `..` would otherwise pass through as a real path segment.
    assert rec.sanitize_segment("..") == rec.UNATTRIBUTED
    assert rec.sanitize_segment(".") == rec.UNATTRIBUTED
    assert rec.sanitize_segment(None) == rec.UNATTRIBUTED
    # A dotted value that is not ITSELF a traversal segment is allowed through, but it can never
    # become one: the separator is stripped, so it stays a single literal path segment.
    for hostile in ("../../etc", "a/b/c", "..%2f..%2fetc", r"\..\..", "..\\..\\etc"):
        cleaned = rec.sanitize_segment(hostile)
        assert "/" not in cleaned and "\\" not in cleaned
        assert cleaned not in {".", ".."}


# --------------------------------------------------------------------------------------- metadata


def test_the_prompt_preview_survives_umlauts_and_spaces():
    # The blob-segment sanitizer would render this "Wer_zahlt_den_Hausanschluss_in_Schw_ich_", which
    # defeats the point of a scannable preview on a German deployment.
    question = "Wer zahlt den Hausanschluss in Schwöich?"
    encoded = rec.encode_prompt_preview(question)
    assert encoded.isascii()
    assert rec.decode_prompt_preview(encoded) == question


def test_the_step_digest_round_trips_and_stays_inside_its_budget():
    steps = [
        rec.StepRecord(index=i, name=rec.STEP_ANSWER, type=rec.STEP_TYPE_LLM, start_ms=0, duration_ms=100 + i)
        for i in range(200)
    ]
    digest = rec.encode_step_digest(steps)
    assert len(digest) <= rec.MAX_STEP_DIGEST_CHARS
    decoded = rec.decode_step_digest(digest)
    assert decoded and all(entry["name"] == rec.STEP_ANSWER for entry in decoded)


def test_metadata_round_trips_into_a_request_row():
    record = tr.begin_turn(route="/chat", streaming=True, started_at=NOON)
    tr.set_identity(chatbot="bbsa", effective_chatbot="bbsa")
    tr.set_model("gpt-5.4-mini", "gpt-5.4-mini", "medium")
    tr.set_path(rec.PATH_CLASSIC)
    tr.open_step(rec.STEP_ANSWER, rec.STEP_TYPE_LLM).close(
        usage=ChatUsage(1000, 200, cached=400, reasoning=50), model="gpt-5.4-mini"
    )
    tr.set_request_details(messages=[{"role": "user", "content": "hallo"}])
    tr.finalize(record, price_table=PriceTable(env={}), now=NOON)
    tr.clear_current()

    metadata = rec.encode_metadata(record)
    assert sum(len(key) + len(value) for key, value in metadata.items()) < 8192
    row = rec.decode_metadata(rec.parse_request_blob_name(record.blob_name()), metadata)
    assert row["chatbot"] == "bbsa"
    assert row["tokensIn"] == 1000 and row["tokensOut"] == 200 and row["tokensCached"] == 400
    assert row["estCostMicros"] == record.cost_micros
    assert row["promptPreview"] == "hallo"
    assert row["streaming"] is True


# --------------------------------------------------------------------------------------- pricing


def test_reasoning_tokens_are_not_added_on_top_of_completion_tokens():
    # `completion_tokens` already contains them. Adding them would roughly double the reported cost of
    # every gpt-5.4-mini tutor turn.
    table = PriceTable(env={})
    with_reasoning = table.estimate("gpt-5.4-mini", rec.TokenCounts(prompt=10000, completion=1000, reasoning=900))
    without = table.estimate("gpt-5.4-mini", rec.TokenCounts(prompt=10000, completion=1000))
    assert with_reasoning.micros == without.micros


def test_cached_tokens_bill_at_the_cached_rate():
    table = PriceTable(env={})
    cached = table.estimate("gpt-5.4-mini", rec.TokenCounts(prompt=10000, completion=1000, cached=9000))
    uncached = table.estimate("gpt-5.4-mini", rec.TokenCounts(prompt=10000, completion=1000))
    assert cached.micros < uncached.micros

    price = table.price_for("gpt-5.4-mini")
    expected = (1000 * price.input + 9000 * price.cached_input + 1000 * price.output) / 1_000_000
    # Cost is stored as whole micro-units, so agreement is to within one of them -- deliberately, so
    # that summing hundreds of thousands of rows accumulates no float drift.
    assert abs(cached.micros / 1_000_000 - expected) < 1e-6


def test_an_unknown_model_is_unpriced_and_never_silently_free():
    estimate = PriceTable(env={}).estimate("gpt-9-does-not-exist", rec.TokenCounts(prompt=1000, completion=10))
    assert estimate.micros is None and estimate.is_priced is False


def test_price_layers_win_in_order():
    # compiled -> env -> blob override. There is no automatic layer: a model missing from all three is
    # reported as unpriced and has to be added in the price editor.
    table = PriceTable(
        env=parse_price_mapping({"gpt-4.1": {"input": 1, "output": 1}}, source="env"),
        override=parse_price_mapping({"gpt-4.1": {"input": 2, "output": 2}}, source="blob"),
    )
    assert table.price_for("gpt-4.1").source == "blob"
    assert table.price_for("gpt-4.1").input == 2
    assert PriceTable(env=parse_price_mapping({"gpt-4.1": {"input": 1, "output": 1}}, source="env")).price_for(
        "gpt-4.1"
    ).source == "env"
    # Nothing supplied for this model anywhere, so the compiled default stands.
    assert table.price_for("gpt-5.4-mini").source == "compiled"


def test_a_malformed_price_entry_is_skipped_rather_than_poisoning_the_table():
    parsed = parse_price_mapping(
        {"a": {"input": 1}, "b": "nope", "c": {"input": -1, "output": 1}, "d": {"input": 1, "output": 2}},
        source="test",
    )
    assert set(parsed) == {"d"}


def test_amounts_in_different_currencies_are_never_treated_as_comparable():
    assert compare_currencies("EUR", "eur") is True
    assert compare_currencies("EUR", "USD") is False
    # An unlabelled amount is exactly the case this guard exists for.
    assert compare_currencies(None, "EUR") is False


# --------------------------------------------------------------------------------------- aggregate


def sample_rows(count: int = 2000, seed: int = 5) -> list[dict]:
    generator = random.Random(seed)
    rows = []
    for index in range(count):
        duration = int(generator.lognormvariate(8.0, 0.9))
        rows.append(
            {
                "traceId": "%016x" % index,
                "startedAt": f"2026-08-19T{generator.randrange(24):02d}:{generator.randrange(60):02d}:00+00:00",
                "chatbot": generator.choice(["bbsa", "lemon", "knoll"]),
                "model": generator.choice(["gpt-5.4-mini", "gpt-4.1"]),
                "path": generator.choice([rec.PATH_CLASSIC, rec.PATH_AGENTIC]),
                "status": generator.choice([rec.STATUS_OK] * 20 + [rec.STATUS_ERROR]),
                "tokensIn": generator.randrange(500, 20000),
                "tokensOut": generator.randrange(50, 2000),
                "tokensReasoning": 0,
                "tokensCached": 0,
                "estCostMicros": generator.randrange(100, 50000),
                "durationMs": duration,
                "errorType": None,
                "steps": [
                    {"name": rec.STEP_ANSWER, "type": rec.STEP_TYPE_LLM, "ms": duration // 2, "tokensIn": 100, "tokensOut": 20}
                ],
            }
        )
    return rows


def test_folding_a_day_does_not_depend_on_the_order_the_rows_arrive_in():
    # This is the property the concurrency argument rests on: ten replicas folding the same closed day
    # must emit byte-identical JSON, so last-writer-wins is a no-op rather than a race.
    rows = sample_rows()
    shuffled = rows[:]
    random.Random(99).shuffle(shuffled)
    assert json.dumps(agg.fold_day("2026-08-19", rows), sort_keys=True) == json.dumps(
        agg.fold_day("2026-08-19", shuffled), sort_keys=True
    )


def test_a_rollup_carries_the_same_totals_as_the_rows_it_folded():
    rows = sample_rows()
    rollup = agg.fold_day("2026-08-19", rows)
    assert rollup["rowCount"] == len(rows)
    assert sum(cell["requests"] for cell in rollup["turns"]) == len(rows)
    assert sum(cell["costMicros"] for cell in rollup["turns"]) == sum(row["estCostMicros"] for row in rows)
    assert sum(cell["tokensIn"] for cell in rollup["turns"]) == sum(row["tokensIn"] for row in rows)


def test_histogram_merging_is_associative_and_commutative():
    rows = sample_rows()
    whole = {}
    for row in rows:
        agg.add_to_histogram(whole, row["durationMs"])
    first, second = {}, {}
    for row in rows[:800]:
        agg.add_to_histogram(first, row["durationMs"])
    for row in rows[800:]:
        agg.add_to_histogram(second, row["durationMs"])
    assert agg.merge_histograms(dict(first), second) == agg.merge_histograms(dict(second), first) == whole


def test_interpolated_percentiles_stay_inside_the_error_bound_the_api_reports():
    rows = sample_rows(4000)
    histogram = {}
    for row in rows:
        agg.add_to_histogram(histogram, row["durationMs"])
    durations = sorted(row["durationMs"] for row in rows)

    for quantile in (0.5, 0.9, 0.95, 0.99):
        exact = statistics.quantiles(durations, n=1000)[int(quantile * 1000) - 1]
        approximate = agg.percentile_from_histogram(histogram, quantile)
        assert abs(approximate - exact) / exact <= agg.MAX_RELATIVE_ERROR


def test_a_percentile_is_suppressed_when_there_are_too_few_samples():
    # An interpolated percentile over three requests describes the bucket edges, not the data, and
    # rendering it as authoritative is worse than rendering nothing.
    assert agg.percentile_from_histogram({"10": 3}, 0.5) is None
    assert agg.percentile_from_histogram({"10": agg.MIN_SAMPLES_FOR_PERCENTILE}, 0.5) is not None


def test_facets_compose_as_or_within_and_and_across():
    rows = sample_rows()
    rollup = agg.fold_day("2026-08-19", rows)

    def requests_for(filters):
        aggregate = agg.RangeAggregate("day")
        agg.ingest_rollup(aggregate, rollup, filters)
        return aggregate.kpis()["requests"]

    one = requests_for({"chatbot": {"bbsa"}})
    two = requests_for({"chatbot": {"bbsa", "lemon"}})
    assert two > one  # OR within a facet widens
    assert requests_for({"chatbot": {"bbsa"}, "model": {"gpt-4.1"}}) < one  # AND across facets narrows


def test_step_rows_survive_facets_that_do_not_exist_on_a_step_cell():
    # A step cell carries only chatbot and path. Applying the model/status facets to it would match
    # nothing and silently empty the step-timing chart.
    rollup = agg.fold_day("2026-08-19", sample_rows())
    aggregate = agg.RangeAggregate("day")
    agg.ingest_rollup(aggregate, rollup, {"chatbot": {"bbsa"}, "model": {"gpt-5.4-mini"}, "status": {rec.STATUS_OK}})
    assert aggregate.step_rows()


def test_auto_granularity_keeps_the_axis_readable_at_every_range():
    assert agg.resolve_granularity(None, 1) == "hour"
    assert agg.resolve_granularity(None, 7) == "day"
    assert agg.resolve_granularity(None, 90) == "week"
    assert agg.resolve_granularity(None, 500) == "month"


def test_an_explicit_hourly_range_is_clamped_before_it_can_list_a_year_of_raw_days():
    # An hourly axis is the one granularity a rollup cannot serve, so `summarize` lifts its raw-day
    # budget to the whole range for it. Without this clamp, `range=all&granularity=hour` would list
    # every day in the range raw -- up to MAX_RANGE_DAYS blob listings -- to draw ~9,600 columns.
    assert agg.resolve_granularity("hour", agg.HOURLY_MAX_DAYS) == "hour"
    assert agg.resolve_granularity("hour", agg.HOURLY_MAX_DAYS + 1) == "day"
    assert agg.resolve_granularity("hour", 400) == "day"

    # Only `hour` is clamped: the other three are served from rollups at any span.
    for granularity in ("day", "week", "month"):
        assert agg.resolve_granularity(granularity, 400) == granularity


# --------------------------------------------------------------------------------------- recorder


def test_the_recorder_no_ops_entirely_when_no_envelope_is_open():
    # The approach code calls these unconditionally; a unit test, a script or a future non-HTTP caller
    # has no envelope and must not have to care.
    tr.clear_current()
    assert tr.open_step("x", "llm").close() is None
    assert tr.add_step("x", "llm", duration_ms=1) is None
    tr.set_identity(chatbot="nope")
    tr.set_request_details(messages=[{"role": "user", "content": "hi"}])
    tr.finalize(None)


def test_an_embeddings_usage_object_is_read_without_assuming_completion_usage():
    counts = rec.token_counts_from_usage(EmbeddingUsage())
    assert counts.prompt == 350 and counts.completion == 0 and counts.reasoning == 0


def test_the_account_identifier_never_reaches_a_stored_record():
    record = tr.begin_turn(route="/chat", streaming=False, started_at=NOON)
    tr.set_request_details(
        messages=[{"role": "user", "content": "hi"}],
        overrides={"user": "free-account-42", "top": 3, "__saved_prompt_template": "secret prompt"},
    )
    tr.finalize(record, now=NOON)
    tr.clear_current()
    body = json.dumps(record.body())
    assert "free-account-42" not in body
    assert "__saved_prompt_template" not in body
    assert record.overrides["top"] == 3


def test_bodies_are_omitted_when_body_storage_is_off(monkeypatch):
    monkeypatch.setenv("TELEMETRY_STORE_BODIES", "false")
    record = tr.begin_turn(route="/chat", streaming=False, started_at=NOON)
    tr.set_request_details(messages=[{"role": "user", "content": "a secret question"}])
    tr.set_response_details(content="a secret answer")
    tr.open_step(rec.STEP_ANSWER, rec.STEP_TYPE_LLM).close(usage=ChatUsage(100, 10), model="gpt-4.1")
    tr.finalize(record, price_table=PriceTable(env={}), now=NOON)
    tr.clear_current()

    body = json.dumps(record.body())
    assert "a secret question" not in body and "a secret answer" not in body
    # The metrics are unaffected -- turning off bodies must not turn off the dashboard.
    assert record.usage.prompt == 100 and record.cost_micros is not None
    # The preview is metadata rather than a body, and is what keeps the request table scannable.
    assert record.prompt_preview == "a secret question"


def test_a_failed_turn_is_still_recorded_with_its_error():
    record = tr.begin_turn(route="/chat", streaming=False, started_at=NOON)
    tr.set_identity(chatbot="lemon")
    try:
        raise ValueError("the model exploded")
    except ValueError as error:
        tr.finalize(record, status=rec.STATUS_ERROR, error=error, now=NOON)
    tr.clear_current()
    assert record.status == rec.STATUS_ERROR
    assert record.error["type"] == "ValueError" and "exploded" in record.error["message"]
    assert rec.encode_metadata(record)["err"] == "ValueError"


def test_finalizing_twice_keeps_the_first_result():
    record = tr.begin_turn(route="/chat", streaming=False, started_at=NOON)
    tr.finalize(record, status=rec.STATUS_OK, now=NOON)
    first = record.finalized_at
    tr.finalize(record, status=rec.STATUS_ERROR, now=NOON + timedelta(hours=1))
    tr.clear_current()
    assert record.finalized_at == first and record.status == rec.STATUS_OK


# --------------------------------------------------------------------------------------- agentic


class QueryPlanningActivity:
    def __init__(self):
        self.id, self.type, self.elapsed_ms, self.input_tokens, self.output_tokens = 0, "modelQueryPlanning", 610, 4100, 90

    def as_dict(self):
        return {"id": 0, "type": "modelQueryPlanning", "elapsedMs": 610, "inputTokens": 4100, "outputTokens": 90}


class SearchIndexActivity:
    def __init__(self, identifier):
        self.id, self.type, self.elapsed_ms = identifier, "searchIndex", 220

    def as_dict(self):
        return {"id": self.id, "type": "searchIndex", "elapsedMs": 220}


class AnswerSynthesisActivity:
    def __init__(self):
        self.id, self.type, self.elapsed_ms, self.input_tokens, self.output_tokens = 9, "modelAnswerSynthesis", 1900, 5000, 120

    def as_dict(self):
        return {"id": 9, "type": "modelAnswerSynthesis", "elapsedMs": 1900, "inputTokens": 5000, "outputTokens": 120}


def test_an_agentic_turn_records_non_zero_tokens():
    # The regression guard for the blind spot this whole feature exists to close: before it, an
    # agentic turn reported zero LLM tokens and therefore zero cost, however much it actually spent.
    record = tr.begin_turn(route="/chat", streaming=False, started_at=NOON)
    tr.set_path(rec.PATH_AGENTIC)
    tr.set_model("gpt-5.4-mini")
    parent = tr.open_step(rec.STEP_AGENTIC_RETRIEVE, rec.STEP_TYPE_RETRIEVAL)
    record_agentic_activity_steps(
        parent,
        [QueryPlanningActivity(), SearchIndexActivity(1), AnswerSynthesisActivity()],
        model="gpt-4.1-mini",
        deployment="gpt-4.1-mini",
    )
    tr.open_step(rec.STEP_ANSWER, rec.STEP_TYPE_LLM).close(usage=ChatUsage(18000, 800), model="gpt-5.4-mini")
    tr.finalize(record, price_table=PriceTable(env={}), now=NOON)
    tr.clear_current()

    assert record.usage.prompt == 4100 + 5000 + 18000  # leaves only; the parent is not counted twice
    assert record.cost_micros > 0

    planning = next(step for step in record.steps if step.name == rec.STEP_AGENTIC_QUERY_PLANNING)
    # Planning runs on the knowledge-base model, which is priced very differently from the chat model.
    assert planning.model == "gpt-4.1-mini"


def test_an_unrecognised_activity_still_lands_on_the_timeline_with_the_knowledge_base_model():
    class Renamed:
        def as_dict(self):
            return {"id": 5, "type": "somethingNew", "elapsedMs": 44, "inputTokens": 7, "outputTokens": 3}

    record = tr.begin_turn(route="/chat", streaming=False, started_at=NOON)
    tr.set_path(rec.PATH_AGENTIC)
    tr.set_model("gpt-5.4-mini")
    record_agentic_activity_steps(
        tr.open_step(rec.STEP_AGENTIC_RETRIEVE, rec.STEP_TYPE_RETRIEVAL), [Renamed()], model="gpt-4.1-mini"
    )
    tr.finalize(record, price_table=PriceTable(env={}), now=NOON)
    tr.clear_current()

    child = record.steps[-1]
    assert child.usage.prompt == 7
    # Without an explicit model the pricer would fall back to the turn's CHAT model, which is the
    # wrong (and far more expensive) price -- on precisely the path an SDK rename would take.
    assert child.model == "gpt-4.1-mini"


def test_an_activity_record_that_raises_on_every_field_cannot_break_the_turn():
    class Hostile:
        @property
        def type(self):
            raise RuntimeError("renamed")

        def as_dict(self):
            raise RuntimeError("renamed")

    record = tr.begin_turn(route="/chat", streaming=False, started_at=NOON)
    tr.set_path(rec.PATH_AGENTIC)
    record_agentic_activity_steps(
        tr.open_step(rec.STEP_AGENTIC_RETRIEVE, rec.STEP_TYPE_RETRIEVAL), [Hostile()], model="gpt-4.1-mini"
    )
    tr.finalize(record, price_table=PriceTable(env={}), now=NOON)
    tr.clear_current()
    assert record.status == rec.STATUS_OK


# --------------------------------------------------------------------------------------- store


class FakeBlob:
    def __init__(self, name, data, metadata):
        self.name, self.data, self.metadata = name, data, metadata


class FakeDownloader:
    def __init__(self, data):
        self.data = data

    async def readall(self):
        return self.data


class FakeBlobClient:
    def __init__(self, blobs, name):
        self.blobs, self.name = blobs, name

    async def download_blob(self):
        from azure.core.exceptions import ResourceNotFoundError

        if self.name not in self.blobs:
            raise ResourceNotFoundError(self.name)
        return FakeDownloader(self.blobs[self.name].data)


class FakeContainer:
    def __init__(self):
        self.blobs, self.created = {}, False

    async def exists(self):
        return self.created

    async def create_container(self):
        self.created = True

    async def upload_blob(self, name, data, overwrite=False, metadata=None, content_settings=None):
        self.blobs[name] = FakeBlob(name, data.read(), metadata or {})
        self.created = True

    def get_blob_client(self, name):
        return FakeBlobClient(self.blobs, name)

    async def iterate(self, items):
        for item in items:
            yield item

    def list_blobs(self, name_starts_with="", include=None):
        return self.iterate([blob for name, blob in sorted(self.blobs.items()) if name.startswith(name_starts_with)])

    def walk_blobs(self, name_starts_with="", delimiter="/"):
        prefixes = sorted(
            {
                name[: name.index("/", len(name_starts_with)) + 1]
                for name in self.blobs
                if name.startswith(name_starts_with) and "/" in name[len(name_starts_with) :]
            }
        )
        return self.iterate([type("Prefix", (), {"name": prefix})() for prefix in prefixes])


class FakeBlobManager:
    def __init__(self):
        self.container = FakeContainer()
        self.blob_service_client = type("Service", (), {"get_container_client": lambda _self, _name: self.container})()


# Anchored to real UTC "now" rather than a fixed date, and always in the past: the range planner and
# the eager rollup fold both compare against the real clock, so a fixture pinned to a literal date
# would drift into the future (or across the closure grace window) depending on when it runs.
def recent_days(count: int = 2) -> list[datetime]:
    midnight = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    return [midnight - timedelta(days=offset) for offset in range(count, 0, -1)]


async def populate(store: TelemetryStore, per_day: int = 15) -> list[str]:
    """Writes whole days in chronological order, the way production does. Interleaving them would
    trip the eager fold, which is entitled to assume a closed day has stopped receiving writes."""
    days = recent_days()
    index = 0
    for day_number, day in enumerate(days):
        for offset in range(per_day):
            moment = day + timedelta(minutes=offset)
            record = tr.begin_turn(route="/chat", streaming=False, started_at=moment)
            tr.set_identity(chatbot=["bbsa", "lemon"][day_number % 2])
            tr.set_model("gpt-5.4-mini")
            tr.set_path(rec.PATH_CLASSIC)
            tr.open_step(rec.STEP_ANSWER, rec.STEP_TYPE_LLM).close(
                usage=ChatUsage(1000 + index, 100), model="gpt-5.4-mini"
            )
            tr.set_request_details(messages=[{"role": "user", "content": f"question {index}"}])
            tr.finalize(record, price_table=PriceTable(env={}), now=moment)
            await store.write(record)
            index += 1
    tr.clear_current()
    return [rec.day_of(day) for day in days]


def test_a_summary_never_downloads_a_request_body():
    # The zero-download premise: charts are built from blob metadata returned inline by the listing.
    async def scenario():
        store = TelemetryStore(FakeBlobManager())
        days = await populate(store)
        downloads = []
        original = store.read_request

        async def spy(name):
            downloads.append(name)
            return await original(name)

        store.read_request = spy
        await store.summarize(from_day=days[0], to_day=days[-1], granularity="day", filters={})
        return downloads

    assert asyncio.run(scenario()) == []


def test_request_paging_is_stable_and_newest_first():
    async def scenario():
        store = TelemetryStore(FakeBlobManager())
        days = await populate(store)
        first = await store.list_requests(from_day=days[0], to_day=days[-1], filters={}, limit=12)
        second = await store.list_requests(
            from_day=days[0], to_day=days[-1], filters={}, limit=12, cursor=first["cursor"]
        )
        return first, second

    first, second = asyncio.run(scenario())
    timestamps = [row["startedAt"] for row in first["rows"]]
    assert timestamps == sorted(timestamps, reverse=True)
    assert not ({row["traceId"] for row in first["rows"]} & {row["traceId"] for row in second["rows"]})


def test_a_storage_outage_degrades_to_empty_rather_than_raising():
    class Broken:
        def __getattr__(self, name):
            raise RuntimeError("storage is down")

    async def scenario():
        store = TelemetryStore(type("Manager", (), {"blob_service_client": Broken()})())
        record = tr.begin_turn(route="/chat", streaming=False, started_at=NOON)
        tr.finalize(record, now=NOON)
        tr.clear_current()
        return await store.write(record), await store.list_day_rows("2026-08-19"), await store.load_rollup("2026-08-19")

    written, rows, rollup = asyncio.run(scenario())
    assert written is None and rows == [] and rollup is None


def test_a_caller_supplied_blob_path_cannot_escape_the_requests_prefix():
    async def scenario():
        store = TelemetryStore(FakeBlobManager())
        days = await populate(store, per_day=1)
        return [
            await store.read_request("requests/../../etc/passwd"),
            await store.read_request(rec.rollup_blob_name(days[0])),
            await store.read_request("pricing/prices.json"),
        ]

    assert asyncio.run(scenario()) == [None, None, None]


def test_the_previous_day_is_folded_on_the_first_write_of_a_new_day():
    # Without this a rollup is only ever created when somebody happens to query that day, and nobody
    # queries day D again on day D+89 -- so the all-time series would develop undetectable holes.
    async def scenario():
        store = TelemetryStore(FakeBlobManager())
        days = await populate(store)
        blobs = store.blob_manager.container.blobs
        first_day_rollup = rec.rollup_blob_name(days[0])
        return sorted(name for name in blobs if name.startswith("rollups/")), json.loads(
            blobs[first_day_rollup].data.decode("utf-8")
        ), first_day_rollup

    names, rollup, first_day_rollup = asyncio.run(scenario())
    # Nobody queried that day; it was folded because a write landed on the following one.
    assert first_day_rollup in names
    assert rollup["rowCount"] > 0 and rollup["turns"]


def test_a_range_wider_than_the_cap_keeps_the_most_recent_days():
    # `range=all` resolves to a from-day far in the past, and the clamp used to keep the FIRST
    # MAX_RANGE_DAYS days and throw the rest away -- so All time asked for a 400-day window ending in
    # February 2021 and every tab drew an empty dashboard. A dashboard of recent activity that drops
    # the newest days is never the right reading of "too wide".
    end = date.today()
    days = day_range("2020-01-01", end.isoformat())
    assert len(days) == MAX_RANGE_DAYS
    assert days[-1] == end.isoformat()
    assert days[0] == (end - timedelta(days=MAX_RANGE_DAYS - 1)).isoformat()

    # A range inside the cap is untouched, and a single day still yields that day.
    assert day_range("2026-08-18", "2026-08-20") == ["2026-08-18", "2026-08-19", "2026-08-20"]
    assert day_range("2026-08-20", "2026-08-20") == ["2026-08-20"]


def test_a_day_with_no_traffic_does_not_mint_a_rollup_blob():
    # Every closed day in a query with no rollup gets folded on demand. Writing one for a day that
    # never had traffic is pure loss -- re-deriving it costs one listing of an empty prefix, which is
    # cheaper than the read of the blob it would replace -- and an all-time query used to mint
    # hundreds of them for days that predate the product (400 were found in the live container).
    async def scenario():
        store = TelemetryStore(FakeBlobManager())
        await store.ensure_container()
        rollup = await store.fold_and_store_day("2021-02-03")
        written = [name for name in store.get_container_client().blobs if name.startswith(rec.ROLLUPS_PREFIX)]
        return rollup, written

    rollup, written = asyncio.run(scenario())
    # The caller still gets an empty rollup to ingest, so a data-less day reads as empty, not missing.
    assert rollup["rowCount"] == 0
    assert written == []


def test_a_day_with_traffic_is_still_written():
    async def scenario():
        store = TelemetryStore(FakeBlobManager())
        days = await populate(store)
        return [name for name in store.get_container_client().blobs if name.startswith(rec.ROLLUPS_PREFIX)], days

    written, days = asyncio.run(scenario())
    assert written, "a day that recorded traffic must still be folded and stored"
    assert any(days[0] in name for name in written)


def test_day_range_and_cursor_parsing_reject_nonsense():
    assert day_range("2026-08-19", "2026-08-21") == ["2026-08-19", "2026-08-20", "2026-08-21"]
    assert day_range("2026-08-21", "2026-08-19") == []
    assert day_range("nonsense", "2026-08-19") == []
    assert parse_cursor("2026-08-19|2026-08-19T12:00:00+00:00|abc") == (
        "2026-08-19",
        "2026-08-19T12:00:00+00:00",
        "abc",
    )
    assert parse_cursor("garbage") == (None, None, None)
    assert parse_cursor(None) == (None, None, None)
