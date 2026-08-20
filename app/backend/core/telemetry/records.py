"""The on-disk shape of one recorded chat turn, and the codecs that move it in and out of blob
storage.

Two design rules run through this module, both inherited from the HYROX visit log
(``approaches/chatbots/hyrox_assessment/visits.py``), which solved the same problem first:

**One blob per turn, never an append.** An append is a read-modify-write that two concurrent
requests race on and silently lose rows to; a blob write is atomic and needs no coordination. There
are up to 10 backend replicas, so nothing may accumulate in process memory either.

**The blob NAME plus its METADATA carry the whole summary row**, so every chart, every table and
every aggregate is one prefix listing with zero body downloads. The body holds only the forensic
detail (messages, per-step payloads, the response) and is downloaded when an operator opens a single
request. Blob metadata comes back inline in the listing response, which is what makes this work.

One deliberate difference from the visit log: the timestamp leads the FILENAME and the chatbot does
NOT lead a folder. Blob listing is lexicographic on the full name, so a ``<day>/<chatbot>/`` layout
would order by bot first and be chronological only within one bot -- and the dashboard's default
view is "all bots, newest first". With the timestamp first a day listing is already in chronological
order, and the per-chatbot filter is a free test on names we are holding anyway.
"""

import base64
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Optional

# The container is private and no route serves it. Deliberately NOT `content`: with
# AZURE_USE_AUTHENTICATION false, `check_path_auth` returns True and `/content/<path>` serves that
# container to anyone holding a blob name. Turn records hold verbatim end-user conversations from
# every bot, including the ungated, publicly embeddable ones.
TELEMETRY_CONTAINER = "telemetry"

REQUESTS_PREFIX = "requests"
ROLLUPS_PREFIX = "rollups/daily"
PRICING_BLOB = "pricing/prices.json"

# Two underscores, because the segment sanitizer below collapses every unsafe character to exactly
# ONE underscore -- so a sanitized field can never contain the separator and the parse is exact.
NAME_FIELD_SEPARATOR = "__"

# Millisecond precision, fixed width (19 characters), lexicographically sortable -> a prefix listing
# comes back in chronological order for free.
TIMESTAMP_FORMAT = "%Y%m%dT%H%M%S%fZ"

# Deliberately the same rule the HYROX session logs use, so an id reads identically in both places.
# Note it permits `.` and `-`, which is why `sanitize_segment` rejects a bare `.` or `..` explicitly.
BLOB_SEGMENT_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]")

TRACE_ID_RE = re.compile(r"^[0-9a-f]{16}$")
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_RE = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])$")

MAX_SEGMENT_LENGTH = 64
UNATTRIBUTED = "_unattributed"

# Retrieval paths. `agentic-web` makes no final answer call at all -- the agentic service returns the
# synthesized answer and `run_until_final_call` short-circuits with a fabricated ChatCompletion.
PATH_CLASSIC = "classic"
PATH_AGENTIC = "agentic"
PATH_AGENTIC_WEB = "agentic-web"
PATH_WIKI = "wiki"
PATH_ASSESSMENT = "assessment"
PATH_UNKNOWN = "unknown"
ALL_PATHS = (PATH_CLASSIC, PATH_AGENTIC, PATH_AGENTIC_WEB, PATH_WIKI, PATH_ASSESSMENT, PATH_UNKNOWN)

STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_ABORTED = "aborted"
STATUS_REJECTED = "rejected"
ALL_STATUSES = (STATUS_OK, STATUS_ERROR, STATUS_ABORTED, STATUS_REJECTED)

# Step kinds drive the colour key in the UI: "was it the model, or the index?"
STEP_TYPE_LLM = "llm"
STEP_TYPE_EMBEDDING = "embedding"
STEP_TYPE_INDEX = "index"
STEP_TYPE_RETRIEVAL = "retrieval"
STEP_TYPE_IO = "io"

STEP_QUERY_REWRITE = "query_rewrite"
STEP_EMBEDDING = "embedding"
STEP_IMAGE_EMBEDDING = "image_embedding"
STEP_SEARCH = "search"
STEP_AGENTIC_RETRIEVE = "agentic_retrieve"
STEP_AGENTIC_QUERY_PLANNING = "agentic.query_planning"
STEP_AGENTIC_SEARCH = "agentic.search"
STEP_AGENTIC_ANSWER_SYNTHESIS = "agentic.answer_synthesis"
STEP_WIKI_INDEX_READ = "wiki_index_read"
STEP_WIKI_NAVIGATE = "wiki_navigate"
STEP_WIKI_PAGES_LOAD = "wiki_pages_load"
STEP_ANSWER = "answer"

# A closed vocabulary, because these abbreviations go into the blob metadata step digest, which has a
# hard size budget. Anything not listed is digested as `oth`.
STEP_ABBREVIATIONS: dict[str, str] = {
    STEP_QUERY_REWRITE: "rw",
    STEP_EMBEDDING: "emb",
    STEP_IMAGE_EMBEDDING: "iemb",
    STEP_SEARCH: "srch",
    STEP_AGENTIC_RETRIEVE: "agr",
    STEP_AGENTIC_QUERY_PLANNING: "agqp",
    STEP_AGENTIC_SEARCH: "agsr",
    STEP_AGENTIC_ANSWER_SYNTHESIS: "agas",
    STEP_WIKI_INDEX_READ: "wix",
    STEP_WIKI_NAVIGATE: "wnav",
    STEP_WIKI_PAGES_LOAD: "wpl",
    STEP_ANSWER: "ans",
}
STEP_NAMES_BY_ABBREVIATION: dict[str, str] = {value: key for key, value in STEP_ABBREVIATIONS.items()}
UNKNOWN_STEP_ABBREVIATION = "oth"

# Azure caps total blob metadata at 8 KiB. The digest is the largest field, so it gets an explicit
# budget well inside that; the prompt preview is capped separately.
MAX_STEP_DIGEST_CHARS = 1024
MAX_PROMPT_PREVIEW_CHARS = 120

SCHEMA_VERSION = 1


def to_utc(moment: datetime) -> datetime:
    """Azure hands back tz-aware UTC; a naive datetime is treated as UTC rather than rejected."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def format_timestamp(moment: datetime) -> str:
    """19 characters, e.g. ``20260819T142203117Z``."""
    return to_utc(moment).strftime("%Y%m%dT%H%M%S%f")[:-3] + "Z"


def parse_timestamp(text: Any) -> Optional[datetime]:
    if not isinstance(text, str):
        return None
    try:
        return datetime.strptime(text, TIMESTAMP_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def day_of(moment: datetime) -> str:
    return to_utc(moment).strftime("%Y-%m-%d")


def month_of(moment: datetime) -> str:
    return to_utc(moment).strftime("%Y-%m")


def is_valid_day(day: Any) -> bool:
    if not isinstance(day, str) or not DAY_RE.match(day):
        return False
    try:
        date.fromisoformat(day)
    except ValueError:
        return False
    return True


def is_valid_month(month: Any) -> bool:
    return isinstance(month, str) and bool(MONTH_RE.match(month))


def sanitize_segment(value: Any, *, fallback: str = UNATTRIBUTED) -> str:
    """A blob-path-safe segment. The sanitizer permits `.` and `-`, so a value of `.` or `..` would
    survive as a real path-traversal segment -- reject those explicitly rather than trusting the
    regex to have covered it."""
    text = str(value).strip() if value not in (None, "") else ""
    cleaned = BLOB_SEGMENT_UNSAFE_RE.sub("_", text[:MAX_SEGMENT_LENGTH])
    if not cleaned or cleaned in {".", ".."}:
        return fallback
    return cleaned


def is_valid_trace_id(trace_id: Any) -> bool:
    return isinstance(trace_id, str) and bool(TRACE_ID_RE.match(trace_id))


@dataclass(frozen=True)
class RequestKey:
    """Everything recoverable from a request blob's name alone."""

    day: str
    timestamp: datetime
    chatbot: str
    trace_id: str
    blob_name: str


def request_blob_name(moment: datetime, chatbot: Any, trace_id: str) -> str:
    """``requests/<YYYY-MM-DD>/<ts>__<chatbot>__<traceId>.json``

    ``moment`` is the FINALIZE time, not the turn start. `/chat/stream` sets `response.timeout = None`,
    so a turn opened at 23:58 can finish well after midnight; keying the day on finalize means a blob
    can never land in a day that has already been rolled up.
    """
    return (
        f"{REQUESTS_PREFIX}/{day_of(moment)}/"
        f"{format_timestamp(moment)}{NAME_FIELD_SEPARATOR}{sanitize_segment(chatbot)}"
        f"{NAME_FIELD_SEPARATOR}{trace_id}.json"
    )


def parse_request_blob_name(blob_name: Any) -> Optional[RequestKey]:
    """Recover the key from a request blob's name, or None when the name is not one of ours.

    Exact rather than best-effort: both variable fields are constrained to charsets that exclude the
    `__` separator and `/`, so no rejoin trick is needed and a malformed name is rejected instead of
    silently mis-parsed.
    """
    if not isinstance(blob_name, str):
        return None
    if not blob_name.startswith(f"{REQUESTS_PREFIX}/") or not blob_name.endswith(".json"):
        return None

    rest = blob_name[len(REQUESTS_PREFIX) + 1 : -len(".json")]
    segments = rest.split("/")
    if len(segments) != 2:
        return None

    day, filename = segments
    if not is_valid_day(day):
        return None

    parts = filename.split(NAME_FIELD_SEPARATOR)
    if len(parts) != 3:
        return None

    timestamp = parse_timestamp(parts[0])
    if timestamp is None:
        return None
    if not is_valid_trace_id(parts[2]):
        return None
    chatbot = parts[1]
    if not chatbot or chatbot != sanitize_segment(chatbot):
        return None
    # The folder is derived from the same moment the filename encodes; a mismatch means a hand-edited
    # or foreign blob, which must not be read back as one of ours.
    if day_of(timestamp) != day:
        return None

    return RequestKey(day=day, timestamp=timestamp, chatbot=chatbot, trace_id=parts[2], blob_name=blob_name)


def rollup_blob_name(day: str) -> str:
    return f"{ROLLUPS_PREFIX}/{day}.json"


@dataclass
class TokenCounts:
    """`completion` ALREADY CONTAINS `reasoning`, and `prompt` already contains `cached` -- both are
    breakdowns, not addends. Adding either on top double-counts, which on a reasoning model like
    gpt-5.4-mini roughly doubles the reported cost of every tutor turn."""

    prompt: int = 0
    completion: int = 0
    reasoning: int = 0
    cached: int = 0

    @property
    def total(self) -> int:
        return self.prompt + self.completion

    def add(self, other: "TokenCounts") -> None:
        self.prompt += other.prompt
        self.completion += other.completion
        self.reasoning += other.reasoning
        self.cached += other.cached

    def is_empty(self) -> bool:
        return not (self.prompt or self.completion or self.reasoning or self.cached)

    def as_dict(self) -> dict[str, int]:
        return {
            "promptTokens": self.prompt,
            "completionTokens": self.completion,
            "reasoningTokens": self.reasoning,
            "cachedTokens": self.cached,
            "totalTokens": self.total,
        }


def read_int_attribute(source: Any, *names: str) -> int:
    """First present numeric attribute (or mapping key) among `names`, else 0."""
    if source is None:
        return 0
    for name in names:
        value = getattr(source, name, None)
        if value is None and isinstance(source, dict):
            value = source.get(name)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return int(value)
    return 0


def token_counts_from_usage(usage: Any) -> TokenCounts:
    """Read an OpenAI usage object without caring which one it is.

    A chat completion yields `CompletionUsage` (prompt/completion tokens plus
    `prompt_tokens_details.cached_tokens` and `completion_tokens_details.reasoning_tokens`); an
    embeddings call yields `CreateEmbeddingResponse.Usage`, which has ONLY `prompt_tokens` and
    `total_tokens` and would raise on the details attributes. Reading defensively covers both, and
    also covers the agentic activity records, which arrive as plain dicts with `inputTokens` /
    `outputTokens`.
    """
    if usage is None:
        return TokenCounts()

    counts = TokenCounts(
        prompt=read_int_attribute(usage, "prompt_tokens", "input_tokens", "promptTokens", "inputTokens"),
        completion=read_int_attribute(
            usage, "completion_tokens", "output_tokens", "completionTokens", "outputTokens"
        ),
    )

    prompt_details = getattr(usage, "prompt_tokens_details", None)
    if prompt_details is None and isinstance(usage, dict):
        prompt_details = usage.get("prompt_tokens_details")
    counts.cached = read_int_attribute(prompt_details, "cached_tokens", "cachedTokens")

    completion_details = getattr(usage, "completion_tokens_details", None)
    if completion_details is None and isinstance(usage, dict):
        completion_details = usage.get("completion_tokens_details")
    counts.reasoning = read_int_attribute(completion_details, "reasoning_tokens", "reasoningTokens")
    return counts


@dataclass
class StepRecord:
    """One measured stage of a turn. `parent` nests the agentic activity records under the retrieve
    call that produced them, so the drawer can render them as children on a shared time axis."""

    index: int
    name: str
    type: str
    start_ms: int
    duration_ms: int
    parent: Optional[int] = None
    model: Optional[str] = None
    deployment: Optional[str] = None
    reasoning_effort: Optional[str] = None
    usage: TokenCounts = field(default_factory=TokenCounts)
    cost_micros: Optional[int] = None
    payload: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "index": self.index,
            "name": self.name,
            "type": self.type,
            "startMs": self.start_ms,
            "durationMs": self.duration_ms,
        }
        if self.parent is not None:
            body["parent"] = self.parent
        for key, value in (
            ("model", self.model),
            ("deployment", self.deployment),
            ("reasoningEffort", self.reasoning_effort),
            ("costMicros", self.cost_micros),
            ("error", self.error),
        ):
            if value is not None:
                body[key] = value
        if not self.usage.is_empty():
            body["usage"] = self.usage.as_dict()
        if self.payload:
            body["payload"] = self.payload
        return body


@dataclass
class TurnRecord:
    """The mutable accumulator for one chat turn.

    Deliberately NOT a field on `ExtraInfo`: `JSONEncoder.default` calls `dataclasses.asdict`, which
    deep-copies every non-dataclass field, and `run_with_streaming` yields `ExtraInfo` as the
    response `context` up to three times per turn. A live accumulator hanging off it would be
    deep-copied per yield, or would raise inside `format_as_ndjson`.
    """

    trace_id: str
    started_at: datetime
    route: str = "/chat"
    streaming: bool = False
    chatbot: Optional[str] = None
    effective_chatbot: Optional[str] = None
    source_chatbot: Optional[str] = None
    path: str = PATH_UNKNOWN
    model: Optional[str] = None
    deployment: Optional[str] = None
    reasoning_effort: Optional[str] = None
    status: str = STATUS_OK
    duration_ms: int = 0
    finalized_at: Optional[datetime] = None
    usage: TokenCounts = field(default_factory=TokenCounts)
    cost_micros: Optional[int] = None
    cost_currency: Optional[str] = None
    price_version: Optional[str] = None
    unpriced_models: list[str] = field(default_factory=list)
    steps: list[StepRecord] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    system_prompt: Optional[dict[str, Any]] = None
    response: Optional[dict[str, Any]] = None
    sources: list[dict[str, Any]] = field(default_factory=list)
    overrides: dict[str, Any] = field(default_factory=dict)
    error: Optional[dict[str, Any]] = None
    prompt_preview: str = ""
    session_id: Optional[str] = None
    # Monotonic origin for step offsets. Never serialized -- wall-clock timestamps come from
    # `started_at`/`finalized_at`, which are immune to a clock adjustment mid-turn.
    perf_origin: float = 0.0
    # The final-answer step, opened when the approach hands back its awaitable and closed at whichever
    # exit consumes it. It lives HERE, on the per-request record, and never on the approach instance:
    # a single `ChatReadRetrieveReadApproach` is shared by every concurrent request for that bot, so
    # per-request state on `self` is a race two simultaneous users would lose. Never serialized.
    pending_answer_step: Any = None

    @property
    def chatbot_segment(self) -> str:
        return sanitize_segment(self.chatbot)

    def blob_name(self) -> str:
        return request_blob_name(self.finalized_at or self.started_at, self.chatbot, self.trace_id)

    def body(self) -> dict[str, Any]:
        moment = self.finalized_at or self.started_at
        body: dict[str, Any] = {
            "schema": SCHEMA_VERSION,
            "traceId": self.trace_id,
            "startedAt": to_utc(self.started_at).isoformat(),
            "finalizedAt": to_utc(moment).isoformat(),
            "route": self.route,
            "streaming": self.streaming,
            "chatbot": {
                "name": self.chatbot,
                "effectiveName": self.effective_chatbot,
                "sourceName": self.source_chatbot,
            },
            "path": self.path,
            "model": self.model,
            "deployment": self.deployment,
            "reasoningEffort": self.reasoning_effort,
            "status": self.status,
            "durationMs": self.duration_ms,
            "usage": self.usage.as_dict(),
            "cost": {
                "micros": self.cost_micros,
                "currency": self.cost_currency,
                "priceVersion": self.price_version,
                "unpriced": list(self.unpriced_models),
            },
            "steps": [step.as_dict() for step in self.steps],
        }
        if self.session_id:
            body["sessionId"] = self.session_id
        if self.messages:
            body["messages"] = self.messages
        if self.system_prompt:
            body["systemPrompt"] = self.system_prompt
        if self.response:
            body["response"] = self.response
        if self.sources:
            body["sources"] = self.sources
        if self.overrides:
            body["overrides"] = self.overrides
        if self.error:
            body["error"] = self.error
        return body


def encode_step_digest(steps: list[StepRecord]) -> str:
    """``<abbrev>:<type>:<ms>:<tin>:<tout>`` joined by ``|``.

    This is what makes the step-timing chart, the per-step cost table and the request-row sparkline
    buildable from a listing alone -- without it the zero-download premise does not hold. Truncated
    rather than dropped when it would blow the metadata budget: a partial digest still draws, and the
    body always holds the full list.
    """
    parts: list[str] = []
    for step in steps:
        abbreviation = STEP_ABBREVIATIONS.get(step.name, UNKNOWN_STEP_ABBREVIATION)
        parts.append(
            f"{abbreviation}:{step.type}:{max(0, step.duration_ms)}:{step.usage.prompt}:{step.usage.completion}"
        )

    digest = "|".join(parts)
    if len(digest) <= MAX_STEP_DIGEST_CHARS:
        return digest

    kept: list[str] = []
    length = 0
    for part in parts:
        if length + len(part) + 1 > MAX_STEP_DIGEST_CHARS:
            break
        kept.append(part)
        length += len(part) + 1
    return "|".join(kept)


def decode_step_digest(digest: Any) -> list[dict[str, Any]]:
    """The inverse, tolerating a truncated or foreign digest by skipping unparseable entries."""
    if not isinstance(digest, str) or not digest:
        return []
    steps: list[dict[str, Any]] = []
    for index, part in enumerate(digest.split("|")):
        fields = part.split(":")
        if len(fields) != 5:
            continue
        abbreviation, step_type, duration, tokens_in, tokens_out = fields
        try:
            steps.append(
                {
                    "index": index,
                    "name": STEP_NAMES_BY_ABBREVIATION.get(abbreviation, abbreviation),
                    "type": step_type,
                    "ms": int(duration),
                    "tokensIn": int(tokens_in),
                    "tokensOut": int(tokens_out),
                }
            )
        except ValueError:
            continue
    return steps


def encode_prompt_preview(text: Any) -> str:
    """base64url of the UTF-8 preview.

    Blob metadata travels in HTTP headers and must be ASCII, but the obvious codec -- the blob
    segment sanitizer -- collapses every space and every non-ASCII character to `_`. On this
    German/Dutch deployment that turns a real question into `Wer_zahlt_den_Hausanschluss_` and any
    umlaut into `_`, which defeats the entire point of a scannable preview. base64 round-trips
    exactly.
    """
    if not isinstance(text, str) or not text:
        return ""
    collapsed = " ".join(text.split())[:MAX_PROMPT_PREVIEW_CHARS]
    if not collapsed:
        return ""
    return base64.urlsafe_b64encode(collapsed.encode("utf-8")).decode("ascii").rstrip("=")


def decode_prompt_preview(encoded: Any) -> str:
    if not isinstance(encoded, str) or not encoded:
        return ""
    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", errors="replace")
    except Exception:
        return ""


def encode_metadata(record: TurnRecord) -> dict[str, str]:
    """The summary row, as blob metadata. Keys are lowercase C# identifiers (Azure's requirement) and
    every value is ASCII. Empty values are dropped rather than stored blank."""
    moment = record.finalized_at or record.started_at
    metadata = {
        "v": str(SCHEMA_VERSION),
        "ts": format_timestamp(moment),
        "bot": sanitize_segment(record.chatbot),
        "effbot": sanitize_segment(record.effective_chatbot, fallback=""),
        "srcbot": sanitize_segment(record.source_chatbot, fallback=""),
        "path": record.path,
        "model": sanitize_segment(record.model, fallback=""),
        "dep": sanitize_segment(record.deployment, fallback=""),
        "effort": sanitize_segment(record.reasoning_effort, fallback=""),
        "stream": "1" if record.streaming else "0",
        "status": record.status,
        "err": sanitize_segment((record.error or {}).get("type"), fallback=""),
        "ms": str(max(0, record.duration_ms)),
        "tin": str(record.usage.prompt),
        "tout": str(record.usage.completion),
        "treason": str(record.usage.reasoning),
        "tcached": str(record.usage.cached),
        "costmicro": "" if record.cost_micros is None else str(record.cost_micros),
        "cur": sanitize_segment(record.cost_currency, fallback=""),
        "pricever": sanitize_segment(record.price_version, fallback=""),
        "nsteps": str(len(record.steps)),
        "steps": encode_step_digest(record.steps),
        "promptb64": encode_prompt_preview(record.prompt_preview),
    }
    return {key: value for key, value in metadata.items() if value != ""}


def decode_metadata(key: RequestKey, metadata: Optional[dict[str, Any]]) -> dict[str, Any]:
    """One request-table row, from a listing entry. Falls back to whatever the blob name carries when
    metadata is absent, so a row written by an older schema still lists."""
    raw = {str(name): ("" if value is None else str(value)) for name, value in (metadata or {}).items()}

    def as_int(name: str) -> int:
        try:
            return int(raw.get(name, "") or 0)
        except ValueError:
            return 0

    def as_optional_int(name: str) -> Optional[int]:
        value = raw.get(name, "")
        if value == "":
            return None
        try:
            return int(value)
        except ValueError:
            return None

    return {
        "traceId": key.trace_id,
        "day": key.day,
        "blobName": key.blob_name,
        "startedAt": to_utc(key.timestamp).isoformat(),
        "chatbot": raw.get("bot") or key.chatbot,
        "effectiveChatbot": raw.get("effbot") or None,
        "sourceChatbot": raw.get("srcbot") or None,
        "path": raw.get("path") or PATH_UNKNOWN,
        "model": raw.get("model") or None,
        "deployment": raw.get("dep") or None,
        "reasoningEffort": raw.get("effort") or None,
        "streaming": raw.get("stream") == "1",
        "status": raw.get("status") or STATUS_OK,
        "errorType": raw.get("err") or None,
        "durationMs": as_int("ms"),
        "tokensIn": as_int("tin"),
        "tokensOut": as_int("tout"),
        "tokensReasoning": as_int("treason"),
        "tokensCached": as_int("tcached"),
        "estCostMicros": as_optional_int("costmicro"),
        "currency": raw.get("cur") or None,
        "priceVersion": raw.get("pricever") or None,
        "steps": decode_step_digest(raw.get("steps")),
        "promptPreview": decode_prompt_preview(raw.get("promptb64")),
    }
