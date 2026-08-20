"""The admin-gated `/internal-admin/telemetry/*` routes.

Driven through a bare Quart request context rather than the full app fixture: `tests/test_app.py`
cannot start offline (its startup reaches real blob storage), and these routes need nothing from that
startup beyond two config entries. Calling the view functions inside a request context still exercises
the real `internal_admin_required` decorator, the real argument validation and the real store.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from quart import Quart

import app as app_module
from config import (
    CONFIG_AVAILABLE_CHAT_MODELS,
    CONFIG_CHATBOT_REGISTRY_STORE,
    CONFIG_INTERNAL_ADMIN_AUTH_SERVICE,
    CONFIG_TELEMETRY_STORE,
)
from core.telemetry import records as rec
from core.telemetry import recorder as tr
from core.telemetry.pricing import PriceTable
from core.telemetry.store import TelemetryStore
from tests.test_telemetry import ChatUsage, FakeBlobManager, recent_days


class FakeRegistryRecord:
    def __init__(self, bot_name, display_name):
        self.bot_name = bot_name
        self.display_name = display_name


class FakeRegistryStore:
    """`list_records` returns a MAPPING of bot name -> record, not a list. Iterating it directly
    yields the string keys, which is exactly the bug this fixture exists to catch."""

    async def list_records(self):
        return {
            "acme-support": FakeRegistryRecord("acme-support", "ACME Support"),
            "zeta-helpdesk": FakeRegistryRecord("zeta-helpdesk", ""),
        }


class FakeAdminAuth:
    """Only what `internal_admin_required` actually touches."""

    session_cookie_name = "internal_tools_admin_session"

    def __init__(self, *, configured: bool = True, signed_in: bool = True):
        self.configured = configured
        self.signed_in = signed_in

    def has_password_configured(self) -> bool:
        return self.configured

    async def load_session(self, token):
        return object() if self.signed_in else None


# Days come from real "now" and are always in the past, because the range planner and the rollup fold
# both compare against the real clock; a fixture pinned to a literal date would sit in the future for
# part of every UTC day and silently drop half its rows out of range.
ROWS_PER_DAY = 20


async def build_app(*, signed_in: bool = True, days: int = 2) -> Quart:
    quart_app = Quart(__name__)
    store = TelemetryStore(FakeBlobManager())

    index = 0
    for day_number, day in enumerate(recent_days(days)):
        for offset in range(ROWS_PER_DAY):
            moment = day + timedelta(minutes=offset)
            record = tr.begin_turn(route="/chat", streaming=index % 3 == 0, started_at=moment)
            tr.set_identity(chatbot=["bbsa", "lemon"][day_number % 2])
            tr.set_model("gpt-4.1" if day_number % 2 else "gpt-5.4-mini")
            tr.set_path(rec.PATH_AGENTIC if day_number % 2 else rec.PATH_CLASSIC)
            tr.open_step(rec.STEP_ANSWER, rec.STEP_TYPE_LLM).close(
                usage=ChatUsage(1000 + index, 100 + index),
                model="gpt-4.1" if day_number % 2 else "gpt-5.4-mini",
            )
            tr.set_request_details(messages=[{"role": "user", "content": f"question {index}"}])
            tr.set_response_details(content=f"answer {index}")
            tr.finalize(
                record,
                status=rec.STATUS_ERROR if index == 7 else rec.STATUS_OK,
                price_table=PriceTable(env={}),
                now=moment,
            )
            await store.write(record)
            index += 1
    tr.clear_current()

    quart_app.config[CONFIG_TELEMETRY_STORE] = store
    quart_app.config[CONFIG_INTERNAL_ADMIN_AUTH_SERVICE] = FakeAdminAuth(signed_in=signed_in)
    quart_app.config[CONFIG_AVAILABLE_CHAT_MODELS] = ["gpt-4.1", "gpt-5.4-mini"]
    quart_app.config[CONFIG_CHATBOT_REGISTRY_STORE] = FakeRegistryStore()
    return quart_app


async def call(view, path: str, *args, app=None, **kwargs):
    quart_app = app or await build_app()
    async with quart_app.test_request_context(path, method=kwargs.pop("method", "GET"), **kwargs):
        response = await view(*args)
    return response


def run(coroutine):
    return asyncio.run(coroutine)


# --------------------------------------------------------------------------------------- gating


def test_every_telemetry_route_is_admin_gated():
    async def scenario():
        quart_app = await build_app(signed_in=False, days=1)
        statuses = []
        for view, path in (
            (app_module.get_telemetry_summary, "/internal-admin/telemetry/summary"),
            (app_module.list_telemetry_requests, "/internal-admin/telemetry/requests"),
            (app_module.get_telemetry_filters, "/internal-admin/telemetry/filters"),
            (app_module.get_telemetry_pricing, "/internal-admin/telemetry/pricing"),
            (app_module.download_telemetry_csv, "/internal-admin/telemetry/export.csv"),
        ):
            response = await call(view, path, app=quart_app)
            body = await response[0].get_json() if isinstance(response, tuple) else await response.get_json()
            status = response[1] if isinstance(response, tuple) else 200
            statuses.append((status, body.get("message")))
        return statuses

    for status, message in run(scenario()):
        assert status == 401
        # The exact sentinel the frontend's handleUnauthorizedError matches on to bounce to the login
        # gate; changing this string silently breaks every admin tab's session-expiry handling.
        assert message == "Internal admin authentication required."


# --------------------------------------------------------------------------------------- summary


def test_the_summary_answers_with_kpis_series_and_facets():
    async def scenario():
        response = await call(app_module.get_telemetry_summary, "/internal-admin/telemetry/summary?range=30d")
        return await response.get_json()

    payload = run(scenario())
    assert payload["kpis"]["requests"] == 40
    assert payload["kpis"]["errors"] == 1
    assert payload["kpis"]["estCostMicros"] > 0
    assert {row["chatbot"] for row in payload["byChatbot"]} == {"bbsa", "lemon"}
    assert {row["model"] for row in payload["byModel"]} == {"gpt-4.1", "gpt-5.4-mini"}
    assert {row["path"] for row in payload["byPath"]} == {rec.PATH_CLASSIC, rec.PATH_AGENTIC}
    assert payload["series"] and payload["byStep"]
    assert payload["currency"] == "EUR"
    # The UI must be able to say how approximate the percentiles are rather than implying precision.
    assert payload["approximate"] is True and payload["maxRelativeError"] > 0


def test_the_summary_filters_by_chatbot():
    async def scenario():
        response = await call(
            app_module.get_telemetry_summary, "/internal-admin/telemetry/summary?range=30d&chatbot=bbsa"
        )
        return await response.get_json()

    payload = run(scenario())
    assert payload["kpis"]["requests"] == 20
    assert [row["chatbot"] for row in payload["byChatbot"]] == ["bbsa"]


def test_a_window_that_predates_recording_reports_no_comparison_rather_than_a_meaningless_delta():
    # Otherwise every KPI reads +100% for the first fortnight, which is worse than saying nothing.
    async def scenario():
        response = await call(app_module.get_telemetry_summary, "/internal-admin/telemetry/summary?range=all")
        return await response.get_json()

    payload = run(scenario())
    assert payload["noComparisonPeriod"] is True
    assert payload["previousTotals"] is None
    assert payload["dataStartsAt"] == rec.day_of(recent_days(2)[0])


def test_all_time_covers_everything_recorded_rather_than_a_window_that_predates_it():
    """The regression test for "All time shows no data".

    `all` used to resolve to a compiled `2020-01-01`, and `day_range` then clamped to the FIRST 400
    days -- a window ending in February 2021, which contains nothing. Every tab drew an empty
    dashboard, and each click folded 400 rollups for days that predate the product (400 such blobs
    were found in the live container). The test above passed throughout, because it only ever
    asserted the comparison flags and never that the range returned its own data.
    """

    async def scenario():
        quart_app = await build_app(days=2)
        summary = await (
            await call(app_module.get_telemetry_summary, "/internal-admin/telemetry/summary?range=all", app=quart_app)
        ).get_json()
        requests = await (
            await call(
                app_module.list_telemetry_requests, "/internal-admin/telemetry/requests?range=all", app=quart_app
            )
        ).get_json()
        csv_response = await call(
            app_module.download_telemetry_csv,
            "/internal-admin/telemetry/export.csv?range=all&view=chatbot",
            app=quart_app,
        )
        return summary, requests, await csv_response.get_data(as_text=True)

    summary, requests, csv_body = run(scenario())
    days = [rec.day_of(day) for day in recent_days(2)]

    assert summary["kpis"]["requests"] == 2 * ROWS_PER_DAY
    assert {row["chatbot"] for row in summary["byChatbot"]} == {"bbsa", "lemon"}
    # The reported range must be the one actually queried, since the UI prints it and sizes its axis
    # from it -- not the sentinel the request happened to carry in.
    assert summary["range"]["from"] == days[0]
    assert summary["range"]["to"] >= days[-1]
    # No day outside the recorded window may be touched at all.
    assert summary["partial"]["daysMissing"] == 0

    assert requests["rows"], "the request explorer must list the recorded turns for all time"
    assert csv_body.count("\n") > 1, "the CSV export must carry rows for all time"


def test_all_time_works_when_every_turn_is_in_the_still_open_day():
    # The live state on the day this shipped: 198 records, all of them today. Today is not closed, so
    # it is served from the raw listing rather than a rollup -- a path an all-time range never reached
    # while it was resolving to a window in 2021.
    async def scenario():
        quart_app = Quart(__name__)
        store = TelemetryStore(FakeBlobManager())
        today = datetime.now(timezone.utc).replace(hour=0, minute=1, second=0, microsecond=0)
        for index in range(5):
            moment = today + timedelta(minutes=index)
            record = tr.begin_turn(route="/chat", streaming=False, started_at=moment)
            tr.set_identity(chatbot="bbsa")
            tr.set_model("gpt-4.1")
            tr.set_path(rec.PATH_CLASSIC)
            tr.open_step(rec.STEP_ANSWER, rec.STEP_TYPE_LLM).close(usage=ChatUsage(900, 90), model="gpt-4.1")
            tr.finalize(record, price_table=PriceTable(env={}), now=moment)
            await store.write(record)
        tr.clear_current()

        quart_app.config[CONFIG_TELEMETRY_STORE] = store
        quart_app.config[CONFIG_INTERNAL_ADMIN_AUTH_SERVICE] = FakeAdminAuth()
        quart_app.config[CONFIG_AVAILABLE_CHAT_MODELS] = ["gpt-4.1"]
        quart_app.config[CONFIG_CHATBOT_REGISTRY_STORE] = FakeRegistryStore()

        response = await call(
            app_module.get_telemetry_summary, "/internal-admin/telemetry/summary?range=all", app=quart_app
        )
        return await response.get_json()

    payload = run(scenario())
    today = datetime.now(timezone.utc).date().isoformat()
    assert payload["kpis"]["requests"] == 5
    assert payload["range"]["from"] == today and payload["range"]["to"] == today
    assert payload["partial"]["rawDaysUsed"] == 1


def test_all_time_on_an_empty_store_is_an_empty_dashboard_not_an_error():
    async def scenario():
        quart_app = Quart(__name__)
        quart_app.config[CONFIG_TELEMETRY_STORE] = TelemetryStore(FakeBlobManager())
        quart_app.config[CONFIG_INTERNAL_ADMIN_AUTH_SERVICE] = FakeAdminAuth()
        quart_app.config[CONFIG_AVAILABLE_CHAT_MODELS] = []
        quart_app.config[CONFIG_CHATBOT_REGISTRY_STORE] = FakeRegistryStore()
        response = await call(
            app_module.get_telemetry_summary, "/internal-admin/telemetry/summary?range=all", app=quart_app
        )
        return await response.get_json()

    payload = run(scenario())
    today = datetime.now(timezone.utc).date().isoformat()
    assert payload["kpis"]["requests"] == 0
    assert payload["dataStartsAt"] is None
    # Not the placeholder decades in the past: an empty dashboard should read as "today, nothing yet".
    assert payload["range"]["from"] == today and payload["range"]["to"] == today


@pytest.mark.parametrize(
    "query,expected",
    [
        ("?from=nonsense&to=2026-08-19", "from and to must both be dates in YYYY-MM-DD format."),
        ("?from=2026-08-19&to=2026-08-01", "The end of the range must not be before its start."),
        ("?range=fortnight", "range must be one of 24h, 7d, 30d, 90d, month, all."),
        ("?granularity=decade", "granularity must be one of auto, hour, day, week, month."),
    ],
)
def test_a_bad_range_is_rejected_with_a_message_not_a_500(query, expected):
    async def scenario():
        response = await call(app_module.get_telemetry_summary, f"/internal-admin/telemetry/summary{query}")
        return response[1], await response[0].get_json()

    status, body = run(scenario())
    assert status == 400 and body["message"] == expected


# --------------------------------------------------------------------------------------- requests


def test_the_request_list_pages_newest_first_and_carries_its_blob_reference():
    async def scenario():
        quart_app = await build_app()
        first = await (
            await call(
                app_module.list_telemetry_requests,
                "/internal-admin/telemetry/requests?range=30d&limit=10",
                app=quart_app,
            )
        ).get_json()
        second = await (
            await call(
                app_module.list_telemetry_requests,
                f"/internal-admin/telemetry/requests?range=30d&limit=10&cursor={first['cursor']}",
                app=quart_app,
            )
        ).get_json()
        return first, second

    first, second = run(scenario())
    assert len(first["rows"]) == 10 and first["hasMore"] is True
    timestamps = [row["startedAt"] for row in first["rows"]]
    assert timestamps == sorted(timestamps, reverse=True)
    assert not ({row["traceId"] for row in first["rows"]} & {row["traceId"] for row in second["rows"]})
    # The row carries its own blob name, so opening one is a single download rather than a listing.
    assert all(row["blobName"].startswith("requests/") for row in first["rows"])
    assert all("steps" in row and "promptPreview" in row for row in first["rows"])


def test_the_request_list_searches_the_prompt_preview():
    async def scenario():
        response = await call(
            app_module.list_telemetry_requests, "/internal-admin/telemetry/requests?range=30d&q=question%2013"
        )
        return await response.get_json()

    payload = run(scenario())
    assert len(payload["rows"]) == 1 and payload["rows"][0]["promptPreview"] == "question 13"


def test_one_request_opens_with_its_full_body():
    async def scenario():
        quart_app = await build_app()
        listing = await (
            await call(
                app_module.list_telemetry_requests,
                "/internal-admin/telemetry/requests?range=30d&limit=1",
                app=quart_app,
            )
        ).get_json()
        row = listing["rows"][0]
        response = await call(
            app_module.get_telemetry_request,
            f"/internal-admin/telemetry/requests/{row['traceId']}?blob={row['blobName']}",
            row["traceId"],
            app=quart_app,
        )
        return await response.get_json()

    body = run(scenario())
    assert body["schema"] == rec.SCHEMA_VERSION
    assert body["messages"] and body["response"]["content"].startswith("answer ")
    assert body["steps"][0]["name"] == rec.STEP_ANSWER


def test_a_forged_blob_reference_is_refused():
    async def scenario():
        quart_app = await build_app()
        results = []
        for trace_id, blob in (
            ("a" * 16, "requests/../../secrets.json"),
            ("a" * 16, "rollups/daily/2026-08-19.json"),
            ("nothex", "requests/2026-08-19/20260819T120000000Z__bbsa__aaaaaaaaaaaaaaaa.json"),
            # A well-formed name whose trace id is not the one being asked for.
            ("b" * 16, "requests/2026-08-19/20260819T120000000Z__bbsa__aaaaaaaaaaaaaaaa.json"),
        ):
            response = await call(
                app_module.get_telemetry_request,
                f"/internal-admin/telemetry/requests/{trace_id}?blob={blob}",
                trace_id,
                app=quart_app,
            )
            results.append(response[1])
        return results

    assert run(scenario()) == [400, 400, 400, 400]


# --------------------------------------------------------------------------------------- exports


@pytest.mark.parametrize("view", ["chatbot", "model", "path", "step", "requests"])
def test_every_csv_view_exports_without_message_text(view):
    async def scenario():
        response = await call(
            app_module.download_telemetry_csv, f"/internal-admin/telemetry/export.csv?range=30d&view={view}"
        )
        return response

    response = run(scenario())
    assert response.mimetype == "text/csv"
    body = run(response.get_data())
    text = body.decode("utf-8") if isinstance(body, bytes) else str(body)
    assert text.splitlines()[0]
    # The aggregate exports must never leak conversation text; reading one turn is a deliberate,
    # one-at-a-time act through the JSON download instead.
    assert "question 1" not in text and "answer 1" not in text


def test_an_unknown_csv_view_is_rejected():
    async def scenario():
        response = await call(
            app_module.download_telemetry_csv, "/internal-admin/telemetry/export.csv?range=30d&view=everything"
        )
        return response[1], await response[0].get_json()

    status, body = run(scenario())
    assert status == 400 and "view must be one of" in body["message"]


def test_a_sub_cent_cost_survives_the_csv_rounding():
    # Six decimals, so a fractional-cent per-step cost is not written out as 0.00.
    assert app_module.format_micros_for_csv(800) == "0.000800"
    assert app_module.format_micros_for_csv(None) == ""


# --------------------------------------------------------------------------------------- pricing


def test_the_price_table_can_be_read_and_edited():
    async def scenario():
        quart_app = await build_app(days=1)
        before = await (
            await call(app_module.get_telemetry_pricing, "/internal-admin/telemetry/pricing", app=quart_app)
        ).get_json()
        response = await call(
            app_module.save_telemetry_pricing,
            "/internal-admin/telemetry/pricing",
            app=quart_app,
            method="PUT",
            json={"prices": {"gpt-4.1": {"input": 9.0, "output": 18.0, "cachedInput": 1.0}}, "note": "manual"},
        )
        after = await response.get_json()
        return before, after

    before, after = run(scenario())
    assert before["prices"]["gpt-4.1"]["input"] != 9.0
    assert after["prices"]["gpt-4.1"]["input"] == 9.0
    assert after["prices"]["gpt-4.1"]["source"] == "blob"


def test_a_price_edit_with_nothing_valid_in_it_is_rejected():
    async def scenario():
        response = await call(
            app_module.save_telemetry_pricing,
            "/internal-admin/telemetry/pricing",
            method="PUT",
            json={"prices": {"gpt-4.1": {"input": "free"}}},
        )
        return response[1], await response[0].get_json()

    status, body = run(scenario())
    assert status == 400 and "No valid prices" in body["message"]


# --------------------------------------------------------------------------------------- misc


def test_provisioned_bots_appear_in_the_filters_alongside_the_built_in_ones():
    # Regression: `list_records()` hands back a dict keyed by bot name, so iterating it directly gave
    # strings and every request raised AttributeError: 'str' object has no attribute 'bot_name'.
    async def scenario():
        response = await call(app_module.get_telemetry_filters, "/internal-admin/telemetry/filters")
        return await response.get_json()

    payload = run(scenario())
    dynamic = {entry["name"]: entry for entry in payload["chatbots"] if entry["kind"] == "dynamic"}
    assert set(dynamic) == {"acme-support", "zeta-helpdesk"}
    assert dynamic["acme-support"]["displayName"] == "ACME Support"
    # A record with no display name falls back to its bot name rather than rendering blank.
    assert dynamic["zeta-helpdesk"]["displayName"] == "zeta-helpdesk"


def test_a_registry_that_raises_does_not_break_the_filters():
    class BrokenRegistry:
        async def list_records(self):
            raise RuntimeError("registry unavailable")

    async def scenario():
        quart_app = await build_app(days=1)
        quart_app.config[CONFIG_CHATBOT_REGISTRY_STORE] = BrokenRegistry()
        response = await call(app_module.get_telemetry_filters, "/internal-admin/telemetry/filters", app=quart_app)
        return await response.get_json()

    payload = run(scenario())
    # The built-in bots still come back; only the provisioned half is missing.
    assert any(entry["name"] == "bbsa" for entry in payload["chatbots"])


def test_the_filters_endpoint_lists_the_built_in_bots_and_models():
    async def scenario():
        response = await call(app_module.get_telemetry_filters, "/internal-admin/telemetry/filters")
        return await response.get_json()

    payload = run(scenario())
    names = {entry["name"] for entry in payload["chatbots"]}
    assert "bbsa" in names and "lemon" in names
    assert payload["models"] == ["gpt-4.1", "gpt-5.4-mini"]
    assert payload["timezone"] == "UTC"
    assert payload["dataStartsAt"] == rec.day_of(recent_days(2)[0])
