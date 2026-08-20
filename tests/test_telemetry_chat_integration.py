"""How telemetry attaches to the two chat routes.

The invariant that matters most here is negative: **nothing in this feature may ever break, slow or
alter a chat response.** A telemetry bug must cost a row, never an answer.

The second is subtler and cost a real bug during development. Quart pops the request *and app*
contexts when a view returns, and a streaming response body is iterated afterwards by the ASGI layer,
outside any context -- so anything in the streaming path that reaches for `current_app` raises
`RuntimeError: Working outside of application context` and silently records nothing for the route
that carries most of the traffic. `stream_with_telemetry` is therefore driven here with **no app
context at all**, which is the condition it actually runs under in production.
"""

import asyncio
from datetime import datetime, timezone

import pytest
from quart import Quart

import app as app_module
from core.telemetry import records as rec
from core.telemetry import recorder as tr
from approaches.approach import DataPoints, ExtraInfo
from approaches.chatreadretrieveread import ChatReadRetrieveReadApproach
from core.telemetry.pricing import PriceTable
from core.telemetry.store import TelemetryStore
from tests.test_telemetry import ChatUsage, FakeBlobManager

NOON = datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc)


class RecordingApp:
    """Stands in for the Quart app object the route binds while its context is still live."""

    def __init__(self):
        self.tasks = []

    def add_background_task(self, function, *args):
        self.tasks.append((function, args))

    async def drain(self):
        for function, args in self.tasks:
            await function(*args)


class ExplodingStore:
    """Every method fails, the way a storage outage or a credential expiry would."""

    price_table = None

    async def write(self, record):
        raise RuntimeError("storage is down")


async def fake_stream(chunks):
    for chunk in chunks:
        yield chunk


def run(coroutine):
    return asyncio.run(coroutine)


def test_a_streaming_turn_is_recorded_with_no_app_context_available():
    # The exact condition the response body is iterated under in production.
    async def scenario():
        recording_app = RecordingApp()
        store = TelemetryStore(FakeBlobManager())
        record = tr.begin_turn(route="/chat/stream", streaming=True, started_at=NOON)
        tr.set_identity(chatbot="bbsa")
        tr.set_model("gpt-5.4-mini")
        tr.set_path(rec.PATH_CLASSIC)
        tr.clear_current()

        chunks = [{"delta": {"content": "hel"}}, {"delta": {"content": "lo"}}]
        emitted = [
            chunk async for chunk in app_module.stream_with_telemetry(fake_stream(chunks), recording_app, store, record)
        ]
        await recording_app.drain()
        return emitted, record, store

    emitted, record, store = run(scenario())
    assert emitted == [{"delta": {"content": "hel"}}, {"delta": {"content": "lo"}}]
    assert record.status == rec.STATUS_OK and record.finalized_at is not None
    assert record.blob_name() in store.blob_manager.container.blobs


def test_the_stream_wrapper_installs_the_envelope_for_the_work_that_runs_inside_it():
    # `run_stream` only builds the generator; every token of model work happens later, inside this
    # wrapper. If the ContextVar were not set here, no step recorded by the approach would land.
    async def scenario():
        record = tr.begin_turn(route="/chat/stream", streaming=True, started_at=NOON)
        tr.clear_current()
        seen = []

        async def inner():
            seen.append(tr.get_current())
            yield {"delta": {"content": "x"}}

        async for _ in app_module.stream_with_telemetry(inner(), RecordingApp(), None, record):
            pass
        return seen, record

    seen, record = run(scenario())
    assert seen == [record]
    # Set once and never reset -- an async generator's finally can run in a different context, where
    # ContextVar.reset would raise.
    assert tr.get_current() is None


def test_a_client_that_disconnects_mid_answer_is_recorded_as_aborted():
    async def scenario():
        recording_app = RecordingApp()
        store = TelemetryStore(FakeBlobManager())
        record = tr.begin_turn(route="/chat/stream", streaming=True, started_at=NOON)
        tr.set_identity(chatbot="lemon")
        tr.open_step(rec.STEP_ANSWER, rec.STEP_TYPE_LLM).close(usage=ChatUsage(500, 10), model="gpt-4.1")
        tr.clear_current()

        generator = app_module.stream_with_telemetry(
            fake_stream([{"delta": {"content": "a"}}, {"delta": {"content": "b"}}]), recording_app, store, record
        )
        await generator.__anext__()
        await generator.aclose()  # what a disconnect looks like from in here
        await recording_app.drain()
        return record, store

    record, store = run(scenario())
    assert record.status == rec.STATUS_ABORTED
    # A turn that was abandoned still spent the tokens it spent, so it is still a billable row.
    assert record.usage.prompt == 500
    assert record.blob_name() in store.blob_manager.container.blobs


def test_a_failure_mid_stream_is_recorded_as_an_error_and_still_propagates():
    async def scenario():
        recording_app = RecordingApp()
        record = tr.begin_turn(route="/chat/stream", streaming=True, started_at=NOON)
        tr.clear_current()

        async def failing():
            yield {"delta": {"content": "a"}}
            raise ValueError("the model exploded")

        with pytest.raises(ValueError):
            async for _ in app_module.stream_with_telemetry(failing(), recording_app, None, record):
                pass
        return record

    record = run(scenario())
    assert record.status == rec.STATUS_ERROR
    assert record.error["type"] == "ValueError"


def test_a_store_that_fails_on_every_call_cannot_break_a_streaming_answer():
    # The single most important property in this file.
    async def scenario():
        recording_app = RecordingApp()
        record = tr.begin_turn(route="/chat/stream", streaming=True, started_at=NOON)
        tr.clear_current()
        emitted = [
            chunk
            async for chunk in app_module.stream_with_telemetry(
                fake_stream([{"delta": {"content": "hello"}}]), recording_app, ExplodingStore(), record
            )
        ]
        # The write is a background task, so its failure is the framework's problem, not the user's.
        with pytest.raises(RuntimeError):
            await recording_app.drain()
        return emitted

    assert run(scenario()) == [{"delta": {"content": "hello"}}]


def test_finishing_a_turn_twice_writes_exactly_one_blob():
    # Both chat routes call this on their success path AND from a belt-and-braces `finally`.
    async def scenario():
        recording_app = RecordingApp()
        store = TelemetryStore(FakeBlobManager())
        record = tr.begin_turn(route="/chat", streaming=False, started_at=NOON)
        tr.set_identity(chatbot="bbsa")
        tr.clear_current()
        app_module.finish_telemetry_turn(recording_app, store, record, status=rec.STATUS_OK)
        app_module.finish_telemetry_turn(recording_app, store, record, status=rec.STATUS_OK)
        await recording_app.drain()
        return recording_app.tasks, store

    tasks, store = run(scenario())
    assert len(tasks) == 1
    assert len([name for name in store.blob_manager.container.blobs if name.startswith("requests/")]) == 1


def test_finishing_a_turn_never_raises_even_with_a_broken_app_object():
    class BrokenApp:
        def add_background_task(self, *args):
            raise RuntimeError("no event loop")

    record = tr.begin_turn(route="/chat", streaming=False, started_at=NOON)
    tr.clear_current()
    app_module.finish_telemetry_turn(BrokenApp(), object(), record, status=rec.STATUS_OK)
    assert record.finalized_at is not None


def test_opening_a_turn_captures_the_prompt_and_drops_the_account_identifier():
    quart_app = Quart(__name__)

    async def scenario():
        async with quart_app.test_request_context("/chat", method="POST"):
            record = app_module.open_telemetry_turn(
                {
                    "messages": [{"role": "user", "content": "Wer zahlt den Hausanschluss?"}],
                    "context": {"overrides": {"include_category": "bbsa", "user": "free-account-42", "top": 3}},
                },
                route="/chat",
                streaming=False,
            )
        tr.clear_current()
        return record

    record = run(scenario())
    assert record.prompt_preview == "Wer zahlt den Hausanschluss?"
    assert record.overrides == {"include_category": "bbsa", "top": 3}


def test_recording_can_be_turned_off_entirely(monkeypatch):
    monkeypatch.setenv("TELEMETRY_ENABLED", "false")
    quart_app = Quart(__name__)

    async def scenario():
        async with quart_app.test_request_context("/chat", method="POST"):
            return app_module.open_telemetry_turn({"messages": []}, route="/chat", streaming=False)

    record = run(scenario())
    assert record is None
    # Every downstream helper has to tolerate the None the kill switch produces.
    app_module.finish_telemetry_turn(RecordingApp(), None, record, status=rec.STATUS_OK)


# --------------------------------------------------------- the streamed answer step


class StreamChunk:
    """Shaped like `openai.types.chat.ChatCompletionChunk` as the loop consumes it."""

    def __init__(self, content=None, usage=None):
        self.usage = usage
        self.choices = (
            [] if content is None else [{"delta": {"role": "assistant", "content": content}, "index": 0}]
        )

    def model_dump(self):
        return {"choices": self.choices, "usage": self.usage}


class StubStreamingApproach:
    """The real `run_with_streaming`, with only the collaborators it touches stubbed out.

    Driving the genuine method matters: the bug this pins lived in the chunk loop itself, and any
    reimplementation here would have reproduced the reading of the code rather than the code.
    """

    include_token_usage = True
    run_with_streaming = ChatReadRetrieveReadApproach.run_with_streaming

    def __init__(self, chunks, extra_info):
        self.chunks = chunks
        self.extra_info = extra_info

    async def run_until_final_call(self, messages, overrides, auth_claims, should_stream=False):
        # The answer step is opened here in production, at the point the request goes out.
        tr.open_answer_step(model="gpt-5.4-mini", deployment="gpt-5.4-mini")

        async def stream():
            for chunk in self.chunks:
                await asyncio.sleep(0.02)
                yield chunk

        async def awaitable():
            return stream()

        return self.extra_info, awaitable()

    def extract_followup_questions(self, content):
        return content, []


def drive_stream(chunks):
    """Run one streamed turn and hand back its recorded steps."""

    async def scenario():
        record = tr.begin_turn(route="/chat/stream", streaming=True, started_at=NOON)
        extra_info = ExtraInfo(data_points=DataPoints(citations=["doc.pdf#page=1"]))
        approach = StubStreamingApproach(chunks, extra_info)
        async for _ in approach.run_with_streaming([{"role": "user", "content": "hallo"}], {}, {}):
            pass
        tr.finalize(record, price_table=PriceTable(env={}), now=NOON)
        tr.clear_current()
        return record

    return run(scenario())


def test_the_streamed_answer_step_survives_azures_leading_choiceless_chunk():
    """The regression test for a short, token-less answer step and a wall of "unaccounted" time.

    Azure opens a stream with a chunk carrying `prompt_filter_results` and NO choices, and the loop
    used to treat any choice-less chunk as terminal. So the answer step closed at time-to-first-chunk
    with `usage=None`; because `close_answer_step` clears the handle, the real usage arriving at the
    end was then silently dropped. Every streamed turn recorded an answer with no tokens and no cost
    -- the largest part of a turn's spend -- and the generation itself fell outside every step.
    """
    usage = ChatUsage(3000, 400, cached=1200, reasoning=100)
    chunks = [
        StreamChunk(),  # Azure's prompt-filter chunk: no choices, no usage
        StreamChunk(content="Der "),
        StreamChunk(content="Hausanschluss "),
        StreamChunk(content="wird bezahlt."),
        StreamChunk(usage=usage),  # the real terminal chunk
    ]
    record = drive_stream(chunks)
    answers = [step for step in record.steps if step.name == rec.STEP_ANSWER]

    assert len(answers) == 1
    answer = answers[0]
    # The tokens that were being thrown away.
    assert answer.usage is not None
    assert answer.usage.prompt == 3000
    assert answer.usage.completion == 400
    assert answer.usage.cached == 1200
    assert answer.usage.reasoning == 100
    # Five chunks at 20 ms each: a step that stopped at the first one could not reach 60 ms.
    assert answer.duration_ms >= 60, answer.duration_ms
    # And the turn's totals must now include the answer, not just the retrieval steps.
    assert record.usage.prompt >= 3000

    payload = answer.payload or {}
    assert payload.get("chunks") == 3
    # Time to first token is inside the step, not equal to it -- that is the whole point of recording
    # it separately now that the step spans the generation.
    assert 0 <= payload.get("time_to_first_token_ms", 0) <= answer.duration_ms


def test_a_stream_that_never_reports_usage_still_records_the_answer_step():
    # No terminal usage chunk (an older API version, or a provider that omits it). The step must still
    # close with its real duration rather than being dropped or left open.
    record = drive_stream([StreamChunk(content="hi"), StreamChunk(content=" there")])
    answers = [step for step in record.steps if step.name == rec.STEP_ANSWER]
    assert len(answers) == 1
    # A step with no usage reported reads as zero tokens, not as a missing step -- the turn still
    # happened and its wall clock is real.
    assert answers[0].usage.total == 0
    assert answers[0].duration_ms >= 20


def test_an_abandoned_stream_still_records_what_the_answer_spent():
    # The client disconnects mid-answer: GeneratorExit is raised at a yield, so only the `finally`
    # can close the step. Without it an abandoned turn shows an answer step of zero -- or none at all.
    async def scenario():
        record = tr.begin_turn(route="/chat/stream", streaming=True, started_at=NOON)
        extra_info = ExtraInfo(data_points=DataPoints(citations=[]))
        chunks = [StreamChunk(), StreamChunk(content="a"), StreamChunk(content="b"), StreamChunk(content="c")]
        approach = StubStreamingApproach(chunks, extra_info)
        generator = approach.run_with_streaming([{"role": "user", "content": "hallo"}], {}, {})
        seen = 0
        async for _ in generator:
            seen += 1
            if seen == 2:
                break
        await generator.aclose()
        tr.finalize(record, status=rec.STATUS_ABORTED, price_table=PriceTable(env={}), now=NOON)
        tr.clear_current()
        return record

    record = run(scenario())
    answers = [step for step in record.steps if step.name == rec.STEP_ANSWER]
    assert len(answers) == 1
    assert answers[0].duration_ms >= 0


def test_an_aborted_stream_records_its_answer_step_through_the_real_wrapper_chain():
    """The regression guard for cleanup ordering.

    `stream_with_telemetry.finally` -> `finish_telemetry_turn` -> `clear_current()`. An `async for`
    does NOT close its iterator, and closing a generator does not cascade into what it wraps, so
    without an explicit `aclose()` the inner generator's `finally` ran after the ContextVar was gone:
    `close_answer_step` and `set_response_details` both silently no-opped, and every aborted turn lost
    its answer step (duration, model, TTFT, chunk count) and its response body.

    Driving `run_with_streaming` directly cannot catch this -- there is no wrapper to unwind through.
    """

    async def scenario():
        record = tr.begin_turn(route="/chat/stream", streaming=True, started_at=NOON)
        seen_context = []

        async def inner():
            tr.open_answer_step(model="gpt-5.4-mini", deployment="gpt-5.4-mini")
            try:
                for index in range(10):
                    await asyncio.sleep(0.005)
                    yield {"delta": {"content": str(index)}}
            finally:
                seen_context.append(tr.get_current() is not None)
                tr.close_answer_step(usage=None, payload={"chunks": 3})
                tr.set_response_details(content="partial answer")

        app_object, store = RecordingApp(), ExplodingStore()
        stream = app_module.stream_with_telemetry(inner(), app_object, store, record)

        consumed = 0
        async for _ in stream:
            consumed += 1
            if consumed == 3:
                break
        await stream.aclose()
        for _ in range(3):
            await asyncio.sleep(0.01)
        tr.clear_current()
        return record, seen_context

    record, seen_context = run(scenario())

    assert seen_context == [True], "the inner cleanup must run while the turn is still current"
    assert record.status == rec.STATUS_ABORTED
    answers = [step for step in record.steps if step.name == rec.STEP_ANSWER]
    assert len(answers) == 1, "an aborted turn must still record what its answer spent"
    assert answers[0].duration_ms >= 0
    assert record.response and record.response.get("content") == "partial answer"
