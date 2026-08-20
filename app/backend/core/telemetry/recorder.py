"""The per-turn recorder: a ContextVar envelope opened by the chat routes and written to from deep
inside the approach, without threading a parameter through every call site.

Three contracts hold this together, and all three are load-bearing:

**Nothing here may ever raise into a chat request.** Every public entry point is wrapped, exactly the
way `record_visit` and `record_assessment_session` are. A telemetry bug must cost us a row, never a
user's answer. `probe`-style helpers additionally no-op when no envelope is open, so the approach
code can call them unconditionally (a unit test, a script, or a future non-HTTP caller has no
envelope and must not care).

**The ContextVar is set once and never reset.** Async generators do not get their own context: a
`set()` inside the streaming wrapper mutates whichever context is driving `__anext__`, and the
generator's `finally` can be driven from a *different* context (Quart- or GC-scheduled `aclose()`),
where `ContextVar.reset(token)` raises `ValueError: Token was created in a different Context`. So we
set, and at the end we set back to None -- which is always legal -- rather than resetting a token.

**Step offsets come from `perf_counter`, wall-clock timestamps from `datetime.now`.** A clock
adjustment mid-turn must not be able to produce a negative duration, and a monotonic counter has no
meaningful absolute value to store.
"""

import contextvars
import logging
import os
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Optional

from core.telemetry import records as rec
from core.telemetry.records import StepRecord, TokenCounts, TurnRecord, token_counts_from_usage

logger = logging.getLogger("telemetry")

# Default None so every helper can be called safely with no envelope open.
current_turn: contextvars.ContextVar[Optional[TurnRecord]] = contextvars.ContextVar(
    "telemetry_current_turn", default=None
)

DEFAULT_MAX_BODY_KB = 256
# A single message is clamped well below the whole-record cap so one enormous retrieved-sources
# message cannot crowd out the user's actual question, and so the drawer never has to render a
# multi-megabyte string.
DEFAULT_MAX_MESSAGE_CHARS = 24_000
MAX_TRACEBACK_CHARS = 4_000


def env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def is_enabled() -> bool:
    """Read at call time rather than import time so the kill switch works without a restart in tests
    and so a redeploy is not needed to disable recording."""
    return env_flag("TELEMETRY_ENABLED", True)


def should_store_bodies() -> bool:
    return env_flag("TELEMETRY_STORE_BODIES", True)


def max_body_bytes() -> int:
    raw = os.getenv("TELEMETRY_MAX_BODY_KB", "").strip()
    try:
        value = int(raw) if raw else DEFAULT_MAX_BODY_KB
    except ValueError:
        value = DEFAULT_MAX_BODY_KB
    return max(1, value) * 1024


def new_trace_id() -> str:
    """The active OpenTelemetry span's trace id when there is one, so a telemetry row can be joined
    to an Application Insights trace; otherwise a random id of the same shape."""
    try:
        from opentelemetry import trace as otel_trace

        span_context = otel_trace.get_current_span().get_span_context()
        if getattr(span_context, "is_valid", False) and span_context.trace_id:
            candidate = format(span_context.trace_id, "032x")[-16:]
            if rec.is_valid_trace_id(candidate):
                return candidate
    except Exception:
        pass
    return secrets.token_hex(8)


def clamp_text(value: Any, limit: int = DEFAULT_MAX_MESSAGE_CHARS) -> tuple[str, bool]:
    """Returns the clamped text and whether it was truncated, so the UI can say so rather than
    silently showing a partial answer as if it were whole."""
    text = value if isinstance(value, str) else ("" if value is None else str(value))
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def begin_turn(
    *,
    route: str,
    streaming: bool,
    trace_id: Optional[str] = None,
    started_at: Optional[datetime] = None,
) -> Optional[TurnRecord]:
    """Open the envelope and install it on the current context.

    Called immediately after the request JSON is parsed -- BEFORE the chatbot gates -- so a request
    rejected by validation, login or the provisioned-bot session quota is still recorded. Those are
    precisely the failures an operator needs to see, and they all return before the approach runs.
    """
    if not is_enabled():
        return None
    try:
        record = TurnRecord(
            trace_id=trace_id or new_trace_id(),
            started_at=started_at or datetime.now(timezone.utc),
            route=route,
            streaming=streaming,
            perf_origin=time.perf_counter(),
        )
        current_turn.set(record)
        return record
    except Exception:
        logger.exception("Failed to begin telemetry turn for %s", route)
        return None


def get_current() -> Optional[TurnRecord]:
    try:
        return current_turn.get()
    except Exception:
        return None


def clear_current() -> None:
    """Set back to None rather than resetting a token -- see the module docstring."""
    try:
        current_turn.set(None)
    except Exception:
        logger.debug("Could not clear the telemetry context variable", exc_info=True)


def set_identity(
    chatbot: Optional[str] = None,
    effective_chatbot: Optional[str] = None,
    source_chatbot: Optional[str] = None,
) -> None:
    record = get_current()
    if record is None:
        return
    try:
        if chatbot:
            record.chatbot = chatbot
        if effective_chatbot:
            record.effective_chatbot = effective_chatbot
        if source_chatbot:
            record.source_chatbot = source_chatbot
    except Exception:
        logger.exception("Failed to set telemetry identity")


def set_identity_from_attributes(attributes: dict[str, str]) -> None:
    """Consume the same attribute dict the request-identity helper in app.py already assembles, so
    there is exactly one place that decides which bot a request belongs to."""
    if not attributes:
        return
    set_identity(
        chatbot=attributes.get("chatbot.name"),
        effective_chatbot=attributes.get("chatbot.effective_name"),
        source_chatbot=attributes.get("chatbot.source_name"),
    )


def set_model(
    model: Optional[str] = None,
    deployment: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
) -> None:
    record = get_current()
    if record is None:
        return
    try:
        if model:
            record.model = model
        if deployment:
            record.deployment = deployment
        if reasoning_effort:
            record.reasoning_effort = reasoning_effort
    except Exception:
        logger.exception("Failed to set telemetry model")


def set_path(path: str) -> None:
    record = get_current()
    if record is None:
        return
    try:
        record.path = path
    except Exception:
        logger.exception("Failed to set telemetry path")


def set_session_id(session_id: Any) -> None:
    record = get_current()
    if record is None:
        return
    try:
        if isinstance(session_id, str) and session_id:
            record.session_id = session_id
    except Exception:
        logger.exception("Failed to set telemetry session id")


REDACTED_OVERRIDE_KEYS = {
    # The Free Bot / rak account identifier. Dropped rather than hashed: nothing in this dashboard
    # groups by user, and a module-salted hash of a low-entropy id is not anonymisation -- it is a
    # lookup table away from the identifier itself, sitting next to a verbatim transcript.
    "user",
    # The rendered system prompt is injected here by the prompt-override layer; it is captured
    # separately (hashed, with a bounded head) rather than duplicated per record.
    "__saved_prompt_template",
}


def sanitize_overrides(overrides: Any) -> dict[str, Any]:
    if not isinstance(overrides, dict):
        return {}
    clean: dict[str, Any] = {}
    for key, value in overrides.items():
        if key in REDACTED_OVERRIDE_KEYS:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            clean[key] = value if not isinstance(value, str) else value[:500]
        elif isinstance(value, (list, tuple)) and len(value) <= 50:
            clean[key] = [item for item in value if isinstance(item, (str, int, float, bool))]
    return clean


def set_request_details(
    *,
    messages: Any = None,
    overrides: Any = None,
    system_prompt: Any = None,
) -> None:
    """Capture the inputs, but nothing at all when body storage is off.

    The prompt preview is 120 verbatim characters of the user's last message. It lives in blob
    METADATA rather than the body, which once made it look like a different class of thing -- it is
    not. `TELEMETRY_STORE_BODIES=false` is the documented privacy switch ("no message text at all"),
    and someone flips that for a legal reason, so the preview has to fall under it. The request table
    already renders an empty preview as "not stored"."""
    record = get_current()
    if record is None:
        return
    try:
        record.overrides = sanitize_overrides(overrides)

        conversation = messages if isinstance(messages, list) else []
        last_user = ""
        for message in reversed(conversation):
            if isinstance(message, dict) and message.get("role") == "user":
                content = message.get("content")
                if isinstance(content, str):
                    last_user = content
                    break
        if not should_store_bodies():
            return
        record.prompt_preview = last_user

        stored: list[dict[str, Any]] = []
        for message in conversation:
            if not isinstance(message, dict):
                continue
            text, truncated = clamp_text(message.get("content"))
            entry: dict[str, Any] = {"role": message.get("role"), "content": text}
            if truncated:
                entry["truncated"] = True
            stored.append(entry)
        record.messages = stored

        if isinstance(system_prompt, str) and system_prompt:
            import hashlib

            head, _ = clamp_text(system_prompt, 2048)
            record.system_prompt = {
                "sha256": hashlib.sha256(system_prompt.encode("utf-8")).hexdigest(),
                "length": len(system_prompt),
                "head": head,
            }
    except Exception:
        logger.exception("Failed to capture telemetry request details")


def set_response_details(
    *,
    content: Any = None,
    finish_reason: Any = None,
    citations: Any = None,
    followup_questions: Any = None,
    sources: Any = None,
) -> None:
    record = get_current()
    if record is None:
        return
    try:
        if isinstance(sources, list):
            record.sources = [item for item in sources[:100] if isinstance(item, dict)]
        if not should_store_bodies():
            return
        text, truncated = clamp_text(content)
        response: dict[str, Any] = {"content": text}
        if truncated:
            response["truncated"] = True
        if finish_reason:
            response["finishReason"] = finish_reason
        if isinstance(citations, list):
            response["citations"] = [item for item in citations[:100] if isinstance(item, str)]
        if isinstance(followup_questions, list):
            response["followupQuestions"] = [item for item in followup_questions[:20] if isinstance(item, str)]
        record.response = response
    except Exception:
        logger.exception("Failed to capture telemetry response details")


class StepHandle:
    """A step that has started but not finished.

    Exists because the final answer call spans two frames: it is created when
    `run_until_final_call` hands back the awaitable, and closed at whichever exit actually consumed
    it (the non-streaming return, or the terminal usage chunk of the stream).
    """

    def __init__(self, record: Optional[TurnRecord], name: str, step_type: str, **fields: Any):
        self.record = record
        self.name = name
        self.step_type = step_type
        self.fields = fields
        self.start_perf = time.perf_counter()
        self.closed = False
        self.step: Optional[StepRecord] = None

    def close(
        self,
        *,
        usage: Any = None,
        model: Optional[str] = None,
        deployment: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
        parent: Optional[int] = None,
        duration_ms: Optional[int] = None,
    ) -> Optional[StepRecord]:
        if self.closed:
            return self.step
        self.closed = True
        record = self.record
        if record is None:
            return None
        try:
            elapsed = (
                duration_ms
                if duration_ms is not None
                else int(round((time.perf_counter() - self.start_perf) * 1000))
            )
            step = StepRecord(
                index=len(record.steps),
                name=self.name,
                type=self.step_type,
                start_ms=max(0, int(round((self.start_perf - record.perf_origin) * 1000))),
                duration_ms=max(0, elapsed),
                parent=parent if parent is not None else self.fields.get("parent"),
                model=model or self.fields.get("model"),
                deployment=deployment or self.fields.get("deployment"),
                reasoning_effort=reasoning_effort or self.fields.get("reasoning_effort"),
                usage=token_counts_from_usage(usage),
                payload=payload or self.fields.get("payload") or {},
                error=error,
            )
            record.steps.append(step)
            self.step = step
            return step
        except Exception:
            logger.exception("Failed to record telemetry step %s", self.name)
            return None

    def __enter__(self) -> "StepHandle":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if not self.closed:
            self.close(error=None if exc is None else type(exc).__name__)
        return False


def open_step(name: str, step_type: str, **fields: Any) -> StepHandle:
    """Always returns a handle, even with no envelope open, so call sites need no guard."""
    return StepHandle(get_current(), name, step_type, **fields)


def open_answer_step(**fields: Any) -> StepHandle:
    """Open the final-answer step and park the handle on the current request's record.

    Two frames apart: `run_until_final_call` creates the awaitable, and either
    `run_without_streaming` or the stream's terminal usage chunk consumes it. The handle therefore
    has to survive between them -- on the ContextVar record, never on the shared approach instance.
    """
    handle = open_step(rec.STEP_ANSWER, rec.STEP_TYPE_LLM, **fields)
    record = get_current()
    if record is not None:
        record.pending_answer_step = handle
    return handle


def close_answer_step(**kwargs: Any) -> None:
    """Close the parked answer step, if there is one. Idempotent, and a no-op when the turn made no
    final call at all (the agentic-web short circuit) or when telemetry is disabled."""
    record = get_current()
    handle = getattr(record, "pending_answer_step", None) if record is not None else None
    if handle is None:
        return
    try:
        handle.close(**kwargs)
    except Exception:
        logger.exception("Failed to close the telemetry answer step")
    finally:
        if record is not None:
            record.pending_answer_step = None


def answer_step_started_at() -> Optional[float]:
    """`time.perf_counter()` reading from when the answer call was issued, or None.

    Exposed so the streaming loop can report time-to-first-token without reaching into the handle.
    That reference point has to be the moment the request went out -- not the moment the stream
    object resolved -- because for a reasoning model most of the wait happens in between.
    """
    record = get_current()
    handle = getattr(record, "pending_answer_step", None) if record is not None else None
    return getattr(handle, "start_perf", None) if handle is not None else None


def discard_answer_step() -> None:
    """Drop an answer step that was opened but never consumed, so it does not linger as a zero-length
    row. Used by the agentic-web short circuit, which makes no final call."""
    record = get_current()
    if record is not None:
        record.pending_answer_step = None


def add_step(
    name: str,
    step_type: str,
    *,
    duration_ms: int,
    start_ms: Optional[int] = None,
    usage: Any = None,
    model: Optional[str] = None,
    deployment: Optional[str] = None,
    parent: Optional[int] = None,
    payload: Optional[dict[str, Any]] = None,
) -> Optional[StepRecord]:
    """Record an already-measured step. Used for the agentic activity records, whose durations come
    from the search service rather than from our own clock."""
    record = get_current()
    if record is None:
        return None
    try:
        step = StepRecord(
            index=len(record.steps),
            name=name,
            type=step_type,
            start_ms=max(0, start_ms if start_ms is not None else 0),
            duration_ms=max(0, int(duration_ms)),
            parent=parent,
            model=model,
            deployment=deployment,
            usage=token_counts_from_usage(usage),
            payload=payload or {},
        )
        record.steps.append(step)
        return step
    except Exception:
        logger.exception("Failed to add telemetry step %s", name)
        return None


def roll_up_usage(record: TurnRecord) -> TokenCounts:
    """Sum the leaf steps only.

    A parented child (an agentic activity) has its tokens counted once, at the child; the parent
    `agentic_retrieve` step carries the same tokens as a convenience for the drawer's summary row and
    must not be added again.
    """
    total = TokenCounts()
    parents = {step.parent for step in record.steps if step.parent is not None}
    for step in record.steps:
        if step.index in parents:
            continue
        total.add(step.usage)
    return total


def price_record(record: TurnRecord, price_table: Any) -> None:
    """Freeze the cost at write time, per step and in total, so history stays what we computed then.

    Each step is priced with its OWN model: the agentic planning and synthesis tokens are billed
    against the knowledge-base model (gpt-4.1-mini), not the chat model that wrote the answer.
    """
    if price_table is None:
        return
    try:
        total_micros = 0
        priced_any = False
        unpriced: list[str] = []
        currency: Optional[str] = None
        parents = {step.parent for step in record.steps if step.parent is not None}

        for step in record.steps:
            if step.usage.is_empty():
                continue
            estimate = price_table.estimate(step.model or record.model, step.usage)
            step.cost_micros = estimate.micros
            if step.index in parents:
                continue
            if estimate.micros is None:
                name = estimate.model or "unknown"
                if name not in unpriced:
                    unpriced.append(name)
                continue
            total_micros += estimate.micros
            currency = currency or estimate.currency
            priced_any = True

        record.cost_micros = total_micros if priced_any else None
        record.cost_currency = currency
        record.price_version = getattr(price_table, "version", None)
        record.unpriced_models = unpriced
    except Exception:
        logger.exception("Failed to price telemetry record %s", record.trace_id)


def finalize(
    record: Optional[TurnRecord],
    *,
    status: str = rec.STATUS_OK,
    error: Optional[BaseException] = None,
    price_table: Any = None,
    now: Optional[datetime] = None,
) -> Optional[TurnRecord]:
    """Close the turn. Safe to call more than once -- the streaming path finalizes in a `finally:`
    that can run after an error path already did, and the second call is a no-op.

    `now` pins the finalize timestamp. Production never passes it; a backfill or a test that needs a
    deterministic blob name does.
    """
    if record is None:
        return None
    try:
        if record.finalized_at is not None:
            return record

        record.finalized_at = now or datetime.now(timezone.utc)
        record.duration_ms = max(0, int(round((time.perf_counter() - record.perf_origin) * 1000)))
        record.status = status
        record.usage = roll_up_usage(record)

        if error is not None:
            import traceback as traceback_module

            formatted = "".join(
                traceback_module.format_exception(type(error), error, error.__traceback__)
            )
            record.error = {
                "type": type(error).__name__,
                "message": str(error)[:1000],
                "traceback": formatted[:MAX_TRACEBACK_CHARS],
            }

        price_record(record, price_table)

        if record.chatbot is None:
            # Never dropped: an unattributed row is still a real request, and a rising count of them
            # is itself the signal that identity resolution has regressed.
            logger.warning("Telemetry turn %s finalized with no chatbot attribution", record.trace_id)
        if record.path == rec.PATH_AGENTIC and record.usage.total == 0 and status == rec.STATUS_OK:
            # The only tripwire for a field rename in the beta search SDK, which would otherwise
            # silently zero the cost of every agentic turn.
            logger.warning(
                "Agentic turn %s recorded zero tokens - check the knowledge base activity records",
                record.trace_id,
            )
        return record
    except Exception:
        logger.exception("Failed to finalize telemetry turn")
        return record
