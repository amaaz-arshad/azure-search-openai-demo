import contextlib
import csv
import dataclasses
import io
import json
import logging
import mimetypes
import os
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from azure.cognitiveservices.speech import (
    ResultReason,
    SpeechConfig,
    SpeechSynthesisOutputFormat,
    SpeechSynthesisResult,
    SpeechSynthesizer,
)
from azure.identity.aio import (
    AzureCliCredential,
    AzureDeveloperCliCredential,
    ChainedTokenCredential,
    ManagedIdentityCredential,
    get_bearer_token_provider,
)
from azure.monitor.opentelemetry import configure_azure_monitor
from azure.search.documents.aio import SearchClient
from azure.search.documents.indexes.aio import SearchIndexClient
from azure.search.documents.knowledgebases.aio import KnowledgeBaseRetrievalClient
from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor
from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware
from opentelemetry.instrumentation.httpx import (
    HTTPXClientInstrumentor,
)
from opentelemetry.instrumentation.openai import OpenAIInstrumentor
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter


class LLMOnlySpanExporter(SpanExporter):
    """Wraps an exporter and only forwards LLM-related spans."""

    _LLM_SPAN_PREFIXES = ("chat ", "embeddings ", "completion ", "responses ")
    _LLM_ATTRIBUTES = ("gen_ai.system", "gen_ai.request.model", "llm.request.type")

    def __init__(self, inner: SpanExporter):
        self._inner = inner

    def _is_llm_span(self, span):  # type: ignore[no-untyped-def]
        name = span.name.lower()
        if any(name.startswith(p) for p in self._LLM_SPAN_PREFIXES):
            return True
        attrs = span.attributes or {}
        return any(a in attrs for a in self._LLM_ATTRIBUTES)

    def export(self, spans):  # type: ignore[no-untyped-def]
        llm_spans = [s for s in spans if self._is_llm_span(s)]
        if not llm_spans:
            return SpanExportResult.SUCCESS
        return self._inner.export(llm_spans)

    def shutdown(self):  # type: ignore[no-untyped-def]
        self._inner.shutdown()

    def force_flush(self, timeout_millis=30000):  # type: ignore[no-untyped-def]
        return self._inner.force_flush(timeout_millis)


OPENLIT_LLM_ONLY_DISABLED_INSTRUMENTORS = (
    "aiohttp",
    "httpx",
    "requests",
    "urllib",
    "urllib3",
    "asgi",
    "flask",
    "starlette",
    "fastapi",
    "falcon",
    "tornado",
    "pyramid",
    "django",
    "psycopg",
    "psycopg-pool",
)


def get_openlit_llm_only_disabled_instrumentors() -> list[str]:
    extra_disabled = os.getenv("OPENLIT_DISABLED_INSTRUMENTORS", "")
    configured_instrumentors = [name.strip() for name in extra_disabled.split(",") if name.strip()]
    return list(dict.fromkeys((*OPENLIT_LLM_ONLY_DISABLED_INSTRUMENTORS, *configured_instrumentors)))


from quart import (
    Blueprint,
    Quart,
    abort,
    current_app,
    jsonify,
    make_response,
    redirect as quart_redirect,
    request,
    send_file,
    send_from_directory,
)
from quart_cors import cors

from approaches.approach import Approach, DataPoints
from approaches.chatbot_config_registry import load_all_chatbot_configs, load_chatbot_config
from approaches.chatbot_prompt_registry import (
    CHATBOT_NAME_ALIASES,
    DEFAULT_CHATBOT_NAME,
    get_chatbot_prompt,
    get_registered_chatbot_names,
    normalize_chatbot_name,
)
from approaches.chatbots.hyrox_assessment.visits import (
    ALL_MONTHS,
    collect_rows,
    csv_filename,
    filter_rows_by_month,
    is_valid_month,
    month_summaries,
    record_visit,
    render_visits_csv,
)
from approaches.chatreadretrieveread import ChatReadRetrieveReadApproach
from approaches.promptmanager import PromptManager
from chat_history.cosmosdb import chat_history_cosmosdb_bp
from config import (
    CONFIG_AGENTIC_KNOWLEDGEBASE_ENABLED,
    CONFIG_AVAILABLE_CHAT_MODELS,
    CONFIG_AUTH_CLIENT,
    CONFIG_CATEGORY_UPLOAD_MANAGER,
    CONFIG_CHATBOT_UPLOAD_MANAGERS,
    CONFIG_CHAT_APPROACH,
    CONFIG_CHATBOT_CHAT_APPROACHES,
    CONFIG_CHATBOT_WIKI_STORE,
    CONFIG_LLM_WIKI_ENABLED,
    CONFIG_CHAT_MODEL_REASONING_EFFORTS,
    CONFIG_CHAT_MODEL_DEPLOYMENTS,
    CONFIG_CHATBOT_PROMPT_STORE,
    CONFIG_CHATBOT_EMBED_CONFIG_STORE,
    CONFIG_CHATBOT_REGISTRY_STORE,
    CONFIG_CHATBOT_SESSION_COUNTER_STORE,
    CONFIG_RESERVED_BOT_NAMES,
    CONFIG_PROVISIONING_API_KEY,
    CONFIG_CHAT_HISTORY_BROWSER_ENABLED,
    CONFIG_CHAT_HISTORY_COSMOS_ENABLED,
    CONFIG_CREDENTIAL,
    CONFIG_DEFAULT_CHAT_MODEL,
    CONFIG_DEFAULT_REASONING_EFFORT,
    CONFIG_DEFAULT_RETRIEVAL_REASONING_EFFORT,
    CONFIG_GLOBAL_BLOB_MANAGER,
    CONFIG_INGESTER,
    CONFIG_KNOWLEDGEBASE_CLIENT,
    CONFIG_KNOWLEDGEBASE_CLIENT_WITH_SHAREPOINT,
    CONFIG_KNOWLEDGEBASE_CLIENT_WITH_WEB,
    CONFIG_KNOWLEDGEBASE_CLIENT_WITH_WEB_AND_SHAREPOINT,
    CONFIG_LANGUAGE_PICKER_ENABLED,
    CONFIG_MULTIMODAL_ENABLED,
    CONFIG_OPENAI_CLIENT,
    CONFIG_INTERNAL_ADMIN_AUTH_SERVICE,
    CONFIG_QUERY_REWRITING_ENABLED,
    CONFIG_RAG_SEARCH_IMAGE_EMBEDDINGS,
    CONFIG_RAG_SEARCH_TEXT_EMBEDDINGS,
    CONFIG_RAG_SEND_IMAGE_SOURCES,
    CONFIG_RAG_SEND_TEXT_SOURCES,
    CONFIG_FREE_AUTH_SERVICE,
    CONFIG_REASONING_EFFORT_ENABLED,
    CONFIG_REASONING_CHAT_MODELS,
    CONFIG_SEARCH_CLIENT,
    CONFIG_SEMANTIC_RANKER_DEPLOYED,
    CONFIG_SHAREPOINT_SOURCE_ENABLED,
    CONFIG_SIMPLE_CHATBOT_AUTH_SERVICE,
    CONFIG_SPEECH_AVATAR_CHARACTER,
    CONFIG_SPEECH_AVATAR_ENABLED,
    CONFIG_SPEECH_AVATAR_STYLE,
    CONFIG_SPEECH_AVATAR_VOICE,
    CONFIG_SPEECH_INPUT_ENABLED,
    CONFIG_SPEECH_OUTPUT_AZURE_ENABLED,
    CONFIG_SPEECH_OUTPUT_BROWSER_ENABLED,
    CONFIG_SPEECH_SERVICE_ID,
    CONFIG_SPEECH_SERVICE_LOCATION,
    CONFIG_SPEECH_SERVICE_TOKEN,
    CONFIG_SPEECH_SERVICE_VOICE,
    CONFIG_TELEMETRY_STORE,
    CONFIG_STREAMING_ENABLED,
    CONFIG_USER_BLOB_MANAGER,
    CONFIG_USER_UPLOAD_ENABLED,
    CONFIG_VECTOR_SEARCH_ENABLED,
    CONFIG_WEB_SOURCE_ENABLED,
)
from core.authentication import AuthenticationHelper
from core.chatbotembedconfigstore import ChatbotEmbedConfig, ChatbotEmbedConfigStore
from core.chatbotpromptstore import ChatbotPromptOverride, ChatbotPromptStore
from core.chatbotregistrystore import UNLIMITED_SESSIONS, ChatbotRegistryRecord, ChatbotRegistryStore
from core.chatbotsessioncounterstore import ChatbotSessionCounterStore
from core.dynamic_tutor_prompt import DYNAMIC_CITATION_GUARDS
from core.dynamic_bot_config import (
    DEFAULT_DYNAMIC_QNA_MODEL,
    DEFAULT_DYNAMIC_TUTOR_MODEL,
    build_bot_config_payload,
    build_dynamic_system_prompt,
    derive_chatbot_mode,
)
from core.chatbotwikistore import ChatbotWikiStore
from provisioning import ensure_embed_public_id, provisioning_bp
from core.internaladminauth import (
    INTERNAL_ADMIN_INVALID_PASSWORD_MESSAGE,
    INTERNAL_ADMIN_PASSWORD_MISSING_MESSAGE,
    InternalAdminAuthStore,
)
from core.freeauth import (
    FREE_ACCOUNT_LIFETIME_DAYS,
    FreeAuthError,
    FreeAuthStore,
    FreeSession,
    describe_account_expiry,
    normalize_free_email,
)
from core.hubspot import HubSpotContactStore
from core.sessionhelper import create_session_id
from core.telemetry import aggregate as telemetry_aggregate
from core.telemetry import records as telemetry_records
from core.telemetry import recorder as telemetry
from core.telemetry.pricing import micros_to_units, parse_price_mapping
from core.telemetry.store import TelemetryStore, clamp_day_range
from core.speechavatar import fetch_avatar_ice_servers
from core.simplechatbotauth import (
    SIMPLE_CHATBOT_AUTH_INVALID_CREDENTIALS_MESSAGE,
    SIMPLE_CHATBOT_AUTH_REQUIRED_MESSAGE,
    SimpleChatbotAuthStore,
    SimpleChatbotCredentials,
    SimpleChatbotSession,
)
from decorators import authenticated, authenticated_path, internal_admin_required
from embed_public_ids import (
    generate_public_id,
    get_public_id,
    get_record_public_id,
    is_embeddable,
    resolve_public_id,
    resolve_public_id_async,
)
from embed_rules import match_url, rules_to_frame_ancestors
from error import ErrorContext, error_dict, error_response, get_request_error_context
from prepdocs import (
    OpenAIHost,
    setup_embeddings_service,
    setup_file_processors,
    setup_image_embeddings_service,
    setup_openai_client,
    setup_search_info,
)
from prepdocslib.blobmanager import AdlsBlobManager, BlobManager
from prepdocslib.categoryupload import CategoryUploadStrategy
from prepdocslib.embeddings import ImageEmbeddings
from prepdocslib.filestrategy import (
    ChatbotUploadCancelled,
    ChatbotUploadRules,
    ChatbotUploadStrategy,
    UploadUserFileStrategy,
)
from prepdocslib.listfilestrategy import File

bp = Blueprint("routes", __name__, static_folder="static")
# Fix Windows registry issue with mimetypes
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
STATIC_ROOT = Path(__file__).resolve().parent / "static"
# Dedicated container for provisioned ("generic") bot knowledge-base files (content2/<bot>/<file>).
# Served by the /content2 citation route; keep in sync with CONTENT2_AUTO_INDEX_CONTAINER / the
# content2ContainerName bicep param (all default to "content2").
CONTENT2_STORAGE_CONTAINER = os.getenv("AZURE_STORAGE_CONTAINER2", "content2")
FREE_CHATBOT_NAME = "free"
FREE_CHATBOT_ROUTE_NAME = "free"
RAK_CHATBOT_NAME = "rak"
RAK_ALLOWED_USERNAMES = frozenset({"12345", "67890"})
INTERNAL_ROUTER_CHATBOT_NAME = "internal"
HYROX_ASSESSMENT_CHATBOT_NAME = "hyrox-assessment"
INTERNAL_INVALID_SOURCE_BOTS = frozenset(
    {INTERNAL_ROUTER_CHATBOT_NAME, FREE_CHATBOT_NAME, RAK_CHATBOT_NAME, HYROX_ASSESSMENT_CHATBOT_NAME}
)

NON_CHATBOT_FRONTEND_PREFIXES = {
    "admin",
    "assets",
    "auth_setup",
    "chat",
    "chatbot-auth",
    "chatbot_uploads",
    "chatbots",
    "chat_history",
    "config",
    "content",
    "embed",
    "embed-demo",
    "free-admin",
    "free-auth",
    "free-users",
    "delete_uploaded",
    "favicon.ico",
    "list_uploaded",
    "managed_uploads",
    "manage-prompts",
    "bot-config",
    "provisioning",
    "public-test-admin",
    "public-test-users",
    "redirect",
    "speech",
    "upload",
    "upload-files",
    "internal-admin",
}

# Keep in sync with frontend chatbot routes in app/frontend/src/chatbots/registry.ts.
KNOWN_CHATBOT_NAMES = {
    "agindo",
    "bbsa",
    "bensberg",
    "cbtx",
    "nerilio",
    "snap",
    "free",
    "public-test",
    "rak",
    "sartorius",
    "steuertipps",
    "knoll",
    "lemon",
    "hyrox-assessment",
    "internal",
    "moodle",
    "publishone",
    "publishone2",
    "fbn",
    "demo",
    "fhg",
    "vjoonk4",
}

SIMPLE_CHATBOT_AUTH_CREDENTIALS = {
    "agindo": SimpleChatbotCredentials(usernames=frozenset({"agindo"}), password="agindo@123"),
    "demo": SimpleChatbotCredentials(usernames=frozenset({"demouser"}), password="demo@123"),
    "fbn": SimpleChatbotCredentials(usernames=frozenset({"fbnuser"}), password="fbn@123"),
    "fhg": SimpleChatbotCredentials(usernames=frozenset({"fhg"}), password="1nnsbruck#"),
    "internal": SimpleChatbotCredentials(usernames=frozenset({"internal"}), password="internal"),
    "knoll": SimpleChatbotCredentials(usernames=frozenset({"knolluser"}), password="knoll@123"),
    "moodle": SimpleChatbotCredentials(usernames=frozenset({"moodle"}), password="H8mburg#"),
    "rak": SimpleChatbotCredentials(usernames=RAK_ALLOWED_USERNAMES, password="rak99#"),
    "sartorius": SimpleChatbotCredentials(usernames=frozenset({"sarto"}), password="G8tting3n#"),
    "steuertipps": SimpleChatbotCredentials(usernames=frozenset({"wks"}), password="Steuer2026#"),
    "vjoonk4": SimpleChatbotCredentials(usernames=frozenset({"vjoon"}), password="k4k4k4"),
}

DEVELOPER_CHAT_MODELS = (
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4.1-nano",
    "gpt-5",
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
)
DEFAULT_DEVELOPER_CHAT_MODEL = "gpt-4.1-mini"


def get_request_route_chatbot_name() -> str | None:
    header_chatbot_name = normalize_chatbot_name(request.headers.get("X-Chatbot-Name"))
    if header_chatbot_name in KNOWN_CHATBOT_NAMES:
        return header_chatbot_name

    referer = request.headers.get("Referer")
    if referer:
        referer_segments = urlparse(referer).path.strip("/").split("/")
        referer_first_segment = normalize_chatbot_name(referer_segments[0] if referer_segments else None)
        if referer_first_segment in KNOWN_CHATBOT_NAMES:
            return referer_first_segment
        # Anonymized embed route (/embed/<publicId>): map the public ID back to the real bot so
        # route-name resolution matches the old /<name>?embed=1 referer behavior.
        if referer_first_segment == "embed" and len(referer_segments) > 1:
            resolved_chatbot_name = resolve_public_id(referer_segments[1])
            if resolved_chatbot_name in KNOWN_CHATBOT_NAMES:
                return resolved_chatbot_name

    return None


def get_internal_source_bot_options() -> list[dict[str, str]]:
    return [
        {"id": chatbot_name, "label": chatbot_name}
        for chatbot_name in sorted(get_registered_chatbot_names())
        if chatbot_name not in INTERNAL_INVALID_SOURCE_BOTS
    ]


def get_internal_allowed_source_bot_names() -> set[str]:
    return {entry["id"] for entry in get_internal_source_bot_options()}


def get_chatbot_upload_manager(chatbot_name: str) -> ChatbotUploadStrategy:
    managers: dict[str, ChatbotUploadStrategy] = current_app.config.get(CONFIG_CHATBOT_UPLOAD_MANAGERS, {})
    normalized_chatbot_name = normalize_chatbot_name(chatbot_name) or chatbot_name.strip().lower()
    manager = managers.get(normalized_chatbot_name)
    if manager is None:
        abort(404)
    return manager


def get_category_upload_manager() -> CategoryUploadStrategy:
    manager = current_app.config.get(CONFIG_CATEGORY_UPLOAD_MANAGER)
    if manager is None:
        raise RuntimeError("Category upload manager is not configured")
    return cast(CategoryUploadStrategy, manager)


def parse_positive_int_query_param(
    param_name: str, default: int, min_value: int = 1, max_value: int | None = None
) -> int:
    raw_value = (request.args.get(param_name) or "").strip()
    if not raw_value:
        return default
    try:
        parsed_value = int(raw_value)
    except ValueError as error:
        raise ValueError(f"{param_name} must be an integer.") from error
    if parsed_value < min_value:
        raise ValueError(f"{param_name} must be at least {min_value}.")
    if max_value is not None and parsed_value > max_value:
        raise ValueError(f"{param_name} must be at most {max_value}.")
    return parsed_value


def get_chatbot_name_from_request_json(request_json: dict[str, Any]) -> str | None:
    context = request_json.get("context", {})
    overrides = context.get("overrides", {}) if isinstance(context, dict) else {}
    include_category = overrides.get("include_category")
    if not isinstance(include_category, str):
        return None
    return normalize_chatbot_name(include_category.split(",", 1)[0])


def normalize_chatbot_category_list(raw_value: str) -> str:
    normalized_categories: list[str] = []
    for raw_category in raw_value.split(","):
        stripped_category = raw_category.strip()
        if not stripped_category:
            continue
        normalized_categories.append(normalize_chatbot_name(stripped_category) or stripped_category.lower())
    return ",".join(normalized_categories)


def normalize_chatbot_request_overrides(request_json: dict[str, Any]) -> None:
    if not isinstance(request_json, dict):
        return

    context = request_json.get("context")
    if not isinstance(context, dict):
        context = {}
        request_json["context"] = context

    overrides = context.get("overrides")
    if not isinstance(overrides, dict):
        overrides = {}
        context["overrides"] = overrides

    for key in ("include_category", "exclude_category"):
        raw_value = overrides.get(key)
        if isinstance(raw_value, str):
            overrides[key] = normalize_chatbot_category_list(raw_value)

    if get_request_route_chatbot_name() != INTERNAL_ROUTER_CHATBOT_NAME:
        return

    raw_source_chatbot = overrides.get("source_chatbot")
    normalized_source_chatbot = (
        normalize_chatbot_name(raw_source_chatbot) if isinstance(raw_source_chatbot, str) else None
    )
    if normalized_source_chatbot is None:
        raise ValueError("Internal Bot requires a source bot selection.")
    if normalized_source_chatbot not in get_internal_allowed_source_bot_names():
        raise ValueError("Internal Bot source bot is invalid.")

    overrides["source_chatbot"] = normalized_source_chatbot
    overrides["include_category"] = normalized_source_chatbot
    overrides.pop("exclude_category", None)


def get_openlit_chatbot_attributes(request_json: dict[str, Any], requested_chatbot_name: str | None) -> dict[str, str]:
    context = request_json.get("context", {})
    overrides = context.get("overrides", {}) if isinstance(context, dict) else {}
    route_chatbot_name = get_request_route_chatbot_name()
    chatbot_name = route_chatbot_name or requested_chatbot_name

    attributes: dict[str, str] = {}
    if chatbot_name:
        attributes["chatbot.name"] = chatbot_name
    if requested_chatbot_name:
        attributes["chatbot.effective_name"] = requested_chatbot_name

    source_chatbot = overrides.get("source_chatbot") if isinstance(overrides, dict) else None
    normalized_source_chatbot = normalize_chatbot_name(source_chatbot) if isinstance(source_chatbot, str) else None
    if normalized_source_chatbot:
        attributes["chatbot.source_name"] = normalized_source_chatbot

    return attributes


def openlit_chatbot_attributes_context(attributes: dict[str, str]):
    if not attributes or not os.getenv("OPENLIT_ENDPOINT"):
        return nullcontext()

    try:
        import openlit

        using_attributes = getattr(openlit, "using_attributes", None)
        if not callable(using_attributes):
            return nullcontext()
        context_manager = using_attributes(attributes)
        if not hasattr(context_manager, "__enter__") or not hasattr(context_manager, "__exit__"):
            return nullcontext()
        return context_manager
    except Exception as error:
        current_app.logger.warning("Failed to attach OpenLIT chatbot attributes: %s", error)
        return nullcontext()


async def stream_with_openlit_chatbot_attributes(
    stream: AsyncGenerator[dict, None], attributes: dict[str, str]
) -> AsyncGenerator[dict, None]:
    with openlit_chatbot_attributes_context(attributes):
        try:
            async for event in stream:
                yield event
        finally:
            # `async for` does NOT close its iterator, and closing a generator does not cascade to
            # what it wraps -- the inner is left to garbage collection, which runs its `finally` at an
            # arbitrary later moment. Every wrapper in this chain has to close what it wraps, or an
            # abandoned stream unwinds outside-in and the innermost cleanup runs too late to matter.
            with contextlib.suppress(Exception):
                await stream.aclose()


# Module level, not `current_app.logger`: `finish_telemetry_turn` runs from the streaming path, which
# executes outside the app context (see its docstring).
telemetry_logger = logging.getLogger("telemetry")


def unwrap_current_app() -> Any:
    """The real app object behind the `current_app` proxy.

    Needed because the streaming telemetry write happens after the app context has been popped, so
    the proxy would raise there; the caller has to capture the object itself while the context is
    still live. `current_app` is a `LocalProxy` at runtime but is typed as `Quart`, so the unwrap is
    invisible to the type checker.
    """
    return getattr(current_app, "_get_current_object")()


def open_telemetry_turn(request_json: dict[str, Any], *, route: str, streaming: bool):
    """Open the per-request telemetry envelope and attach whatever identity is already known.

    Deliberately opened here, right after the JSON is parsed and BEFORE the chatbot gates: both chat
    routes run override normalization, the free/rak login check and the provisioned-bot session quota
    before any model work, and every one of those can return early. Opening the envelope after them
    would make each of those failures invisible -- and an operator investigating "customer says the
    bot is broken" needs the 401s and the quota rejections most of all.
    """
    record = telemetry.begin_turn(route=route, streaming=streaming)
    if record is not None:
        telemetry.set_identity_from_attributes(get_openlit_chatbot_attributes(request_json, None))
        telemetry.set_request_details(
            messages=request_json.get("messages"),
            overrides=(request_json.get("context") or {}).get("overrides"),
        )
    return record


def finish_telemetry_turn(app_object, store, record, *, status: str, error: BaseException | None = None) -> None:
    """Finalize and hand the write to a background task.

    `app_object` and `store` are bound by the CALLER, while the request context is still live. Quart
    pops the request and app contexts when the view returns, and a streaming response body is
    iterated afterwards by the ASGI layer -- outside any context -- so `current_app` raises
    `RuntimeError: Working outside of application context` there. (The repo already carries the scar:
    `format_as_ndjson` uses a module-level logger rather than `current_app.logger`, unlike every other
    error path in this file.) `add_background_task` pushes its own app context, so the write itself is
    fine; it just cannot be *looked up* from inside the generator.

    A background task rather than an awaited write, so a client disconnect -- which raises
    `CancelledError` into the generator's `finally` -- cannot cancel the write half way through.

    Idempotent on `finalized_at`, which `telemetry.finalize` stamps. Both chat routes call this on
    their success path AND from a belt-and-braces `finally`, and without the guard every request would
    issue two identical blob PUTs.
    """
    if record is None or record.finalized_at is not None:
        return
    try:
        price_table = getattr(store, "price_table", None) if store is not None else None
        telemetry.finalize(record, status=status, error=error, price_table=price_table)
        if store is not None and app_object is not None:
            app_object.add_background_task(store.write, record)
    except Exception:
        telemetry_logger.exception("Failed to schedule the telemetry write")
    finally:
        telemetry.clear_current()


async def stream_with_telemetry(stream: AsyncGenerator[dict, None], app_object, store, record):
    """Wrap the response generator so the turn is finalized when the stream ends, however it ends.

    This is the only construct that spans the whole streaming lifetime: `run_stream` merely builds the
    generator, and the actual model work happens later, inside `format_as_ndjson`, when the ASGI layer
    iterates the response body.

    The ContextVar is set here and never reset. Async generators do not get their own context, so the
    `set` lands in whichever context is driving `__anext__`, and this `finally` can be driven from a
    different one (a Quart- or GC-scheduled `aclose()`), where `ContextVar.reset(token)` raises
    `ValueError: Token was created in a different Context`. Setting back to None is always legal.
    """
    if record is not None:
        telemetry.current_turn.set(record)
    status = telemetry_records.STATUS_OK
    failure: BaseException | None = None
    try:
        async for event in stream:
            yield event
    except GeneratorExit:
        # The client went away mid-answer. Still a real, billable turn: whatever tokens were spent
        # before the disconnect were spent.
        status = telemetry_records.STATUS_ABORTED
        raise
    except BaseException as error:  # noqa: BLE001 - re-raised immediately
        status = telemetry_records.STATUS_ERROR
        failure = error if isinstance(error, Exception) else None
        raise
    finally:
        # Close the wrapped stream FIRST. `finish_telemetry_turn` clears the ContextVar, and
        # `run_with_streaming` closes its answer step from its own `finally` -- which, without this,
        # runs after the clear (verified: the step and the response body were both silently dropped on
        # every aborted turn). Awaiting here is legal during GeneratorExit; yielding would not be.
        with contextlib.suppress(Exception):
            await stream.aclose()
        finish_telemetry_turn(app_object, store, record, status=status, error=failure)


def build_chat_model_deployments(default_model: str, default_deployment: str | None) -> dict[str, str | None]:
    deployments: dict[str, str | None] = {model: model for model in DEVELOPER_CHAT_MODELS}
    if default_model in deployments and default_deployment:
        deployments[default_model] = default_deployment
    raw_overrides = (os.getenv("AZURE_OPENAI_CHAT_MODEL_DEPLOYMENTS") or "").strip()
    if raw_overrides:
        try:
            parsed_overrides = json.loads(raw_overrides)
        except json.JSONDecodeError as error:
            raise ValueError("AZURE_OPENAI_CHAT_MODEL_DEPLOYMENTS must be valid JSON.") from error
        if not isinstance(parsed_overrides, dict):
            raise ValueError("AZURE_OPENAI_CHAT_MODEL_DEPLOYMENTS must be a JSON object.")
        for model, deployment in parsed_overrides.items():
            if model not in deployments:
                continue
            if isinstance(deployment, str) and deployment.strip():
                deployments[model] = deployment.strip()
    return deployments


def get_free_auth_service() -> FreeAuthStore:
    auth_service = current_app.config.get(CONFIG_FREE_AUTH_SERVICE)
    if auth_service is None:
        raise RuntimeError("Public-test auth service is not configured")
    return cast(FreeAuthStore, auth_service)


def get_internal_admin_auth_service() -> InternalAdminAuthStore:
    auth_service = current_app.config.get(CONFIG_INTERNAL_ADMIN_AUTH_SERVICE)
    if auth_service is None:
        raise RuntimeError("Internal admin auth service is not configured")
    return cast(InternalAdminAuthStore, auth_service)


def get_simple_chatbot_auth_service() -> SimpleChatbotAuthStore:
    auth_service = current_app.config.get(CONFIG_SIMPLE_CHATBOT_AUTH_SERVICE)
    if auth_service is None:
        raise RuntimeError("Simple chatbot auth service is not configured")
    return cast(SimpleChatbotAuthStore, auth_service)


def get_chatbot_prompt_store() -> ChatbotPromptStore:
    prompt_store = current_app.config.get(CONFIG_CHATBOT_PROMPT_STORE)
    if prompt_store is None:
        raise RuntimeError("Chatbot prompt store is not configured")
    return cast(ChatbotPromptStore, prompt_store)


def get_chatbot_embed_config_store() -> ChatbotEmbedConfigStore:
    embed_config_store = current_app.config.get(CONFIG_CHATBOT_EMBED_CONFIG_STORE)
    if embed_config_store is None:
        raise RuntimeError("Chatbot embed config store is not configured")
    return cast(ChatbotEmbedConfigStore, embed_config_store)


def get_chatbot_registry_store() -> ChatbotRegistryStore:
    registry_store = current_app.config.get(CONFIG_CHATBOT_REGISTRY_STORE)
    if registry_store is None:
        raise RuntimeError("Chatbot registry store is not configured")
    return cast(ChatbotRegistryStore, registry_store)


def get_chatbot_session_counter_store() -> ChatbotSessionCounterStore:
    counter_store = current_app.config.get(CONFIG_CHATBOT_SESSION_COUNTER_STORE)
    if counter_store is None:
        raise RuntimeError("Chatbot session counter store is not configured")
    return cast(ChatbotSessionCounterStore, counter_store)


EXAMPLE_DYNAMIC_BOT_NAME = "example"
EXAMPLE_DYNAMIC_BOT_DEFAULTS: dict[str, Any] = {
    "display_name": "Example",
    "active": True,
    "number_sessions": UNLIMITED_SESSIONS,
    "prompt": (
        "You are Example, a helpful general-purpose assistant. Answer clearly and concisely in the "
        "user's language. If you do not know, say so instead of guessing."
    ),
    "modes": {"qa": True, "tutor": False, "assessment": False},
    "design": {"color_primary": "#4b5563"},
    "languages": ["English", "Deutsch", "Nederlands"],
    "greeting": {
        "English": "Welcome to Example. How can I help?",
        "Deutsch": "Willkommen bei Example. Wie kann ich helfen?",
        "Nederlands": "Welkom bij Example. Waar kan ik je mee helpen?",
    },
    "disclaimer": {
        "English": "Example is an AI assistant. Responses are generated automatically.",
        "Deutsch": "Example ist ein KI-Assistent. Antworten werden automatisch generiert.",
        "Nederlands": "Example is een AI-assistent. Antwoorden worden automatisch gegenereerd.",
    },
    "features": {"disclaimer": True, "history": True, "sources": False},
}


async def ensure_example_dynamic_bot_seeded() -> None:
    """Create the shipped /example dynamic bot once if it does not already exist."""

    store = get_chatbot_registry_store()
    if await store.load_record(EXAMPLE_DYNAMIC_BOT_NAME) is not None:
        return
    # Seeded outside the provisioning API, so mint its widget identity here too — otherwise the
    # shipped example is the one dynamic bot that cannot be embedded. Deliberately generate_public_id
    # rather than mint_public_id: the latter LISTS the registry to check for collisions, and a blob
    # listing during app startup would push cold starts past the startup timeout. Excluding only the
    # committed built-in IDs is enough here (a collision with another dynamic bot is ~1 in 36^9, and
    # this runs at most once per deployment).
    fields = {**EXAMPLE_DYNAMIC_BOT_DEFAULTS, "embed_public_id": generate_public_id()}
    await store.save_record(EXAMPLE_DYNAMIC_BOT_NAME, fields=fields)
    current_app.logger.info("Seeded example dynamic chatbot at /example")


# Minimal neutral system prompt for a dynamic bot whose control panel sent an empty `prompt`.
# Real bots override this by sending their own prompt; the placeholders are substituted by
# render_chatbot_prompt. Built-in bots never use this — they keep their source prompts.
# DYNAMIC_CITATION_GUARDS (core/dynamic_tutor_prompt.py) explains why these rules are needed here.
DEFAULT_DYNAMIC_PROMPT = (
    "You are a helpful assistant. Answer the user's question using only the facts in the sources "
    "below. If the sources do not contain the answer, say you don't know — do not invent anything. "
    "Answer in {{language_locale}}. Cite each source you use in square brackets right after the fact "
    "it supports, e.g. [info1.pdf]; never combine multiple sources in one bracket. "
    + " ".join(DYNAMIC_CITATION_GUARDS)
    + " {{POSSIBLE_CITATIONS_PROMPT}}"
)


async def resolve_active_dynamic_record(chatbot_name: str | None) -> ChatbotRegistryRecord | None:
    """Return the active provisioned (dynamic) record for a name, or None.

    Built-in bots NEVER resolve here: a name already owned by a built-in is returned as None so its
    source-defined identity always wins (hard isolation invariant). Inactive (stopped) and unknown
    dynamic names also return None, so they are not servable.
    """
    normalized = normalize_chatbot_name(chatbot_name)
    if normalized is None or normalized in KNOWN_CHATBOT_NAMES:
        return None
    record = await get_chatbot_registry_store().load_record(normalized)
    if record is None or not record.active:
        return None
    return record


async def resolve_dynamic_record_any_state(chatbot_name: str | None) -> ChatbotRegistryRecord | None:
    """Like resolve_active_dynamic_record, but STOPPED bots resolve too.

    For admin surfaces that must see a provisioned bot regardless of its start/stop flag (the
    directory listing, the embed whitelist editor). The isolation short-circuit on built-in names
    is identical, so this never returns a built-in either. Serving paths must keep using
    resolve_active_dynamic_record — a stopped bot is not servable.
    """
    normalized = normalize_chatbot_name(chatbot_name)
    if normalized is None or normalized in KNOWN_CHATBOT_NAMES:
        return None
    return await get_chatbot_registry_store().load_record(normalized)


async def is_embeddable_chatbot(chatbot_name: str | None) -> bool:
    """True if a bot has an embed identity: a committed public ID (built-in) or a registry record.

    Dynamic bots are embeddable purely by existing — provisioning mints their public ID at create,
    and a record without one (created before that) is backfilled on first admin access. Stopped
    bots count as embeddable so an admin can prepare the whitelist before starting the bot; the
    admin UI is what declines to hand out a snippet for a bot that is not currently servable.
    """
    if is_embeddable(chatbot_name):
        return True
    return await resolve_dynamic_record_any_state(chatbot_name) is not None


def resolve_dynamic_chat_model(record: ChatbotRegistryRecord, deployed_models: dict[str, Any] | None) -> str:
    """The chat model a dynamic bot actually runs on.

    Honors the provisioned `llm` only if it maps to a model deployed here; otherwise falls back to
    the mode-aware default (tutor -> reasoning model, Q&A -> general model), so a wrong, undeployed,
    or empty `llm` self-heals instead of 404ing at call time. Shared by the chat path and the admin
    directory so the directory shows what will really serve.
    """
    is_tutor = derive_chatbot_mode(record.modes) == "tutor-qna"
    default_model = DEFAULT_DYNAMIC_TUTOR_MODEL if is_tutor else DEFAULT_DYNAMIC_QNA_MODEL
    provisioned_llm = record.llm.strip() if isinstance(record.llm, str) else ""
    return provisioned_llm if provisioned_llm in (deployed_models or {}) else default_model


def resolve_dynamic_reasoning_effort(record: ChatbotRegistryRecord, chat_model: str | None) -> str | None:
    """The reasoning effort a dynamic bot actually runs at, or None if its model has no reasoning.

    A missing or unsupported provisioned `reasoning_effort` falls back to "medium" (or the model's
    last supported tier). Non-reasoning models (e.g. gpt-4.1) return None — effort is dropped for
    them downstream.
    """
    reasoning_support = Approach.GPT_REASONING_MODELS.get(chat_model) if isinstance(chat_model, str) else None
    if reasoning_support is None:
        return None
    supported_efforts = reasoning_support.supported_efforts
    provisioned_effort = (record.reasoning_effort or "").strip().lower()
    if provisioned_effort in supported_efforts:
        return provisioned_effort
    return "medium" if "medium" in supported_efforts else supported_efforts[-1]


async def enforce_dynamic_chatbot_gate(
    requested_chatbot_name: str | None, *, is_new_session: bool = False
) -> tuple[Any, int] | None:
    """Pre-chat gate for DYNAMIC (provisioned) bots. Returns None to proceed, or an
    (error response, status) tuple to reject before any model work or session creation.

    Built-in bots short-circuit before any registry load, so they are never gated (hard isolation
    invariant). Enforces two things for dynamic bots:

      * active flag — a stopped (active=false) bot is refused with 403 `chatbot_inactive` (without
        this, resolve_active_dynamic_record returns None for an inactive bot and the request would
        silently fall back to the default prompt instead of being refused).
      * number_sessions quota — when this request opens a NEW session (is_new_session) and the bot
        has a finite cap, a new session is admitted only while the cumulative count is below the cap;
        otherwise 403 `quota_exceeded`. Unlimited (-1) short-circuits before any counter I/O, so
        built-in and unlimited bots never touch the session counter store.
    """
    normalized = normalize_chatbot_name(requested_chatbot_name)
    if normalized is None or normalized in KNOWN_CHATBOT_NAMES:
        return None
    record = await get_chatbot_registry_store().load_record(normalized)
    if record is None:
        # Unknown dynamic name — routing already handles it; don't 403 a name we don't own.
        return None
    if not record.active:
        return jsonify({"error": "chatbot_inactive", "chatbotName": normalized}), 403
    if is_new_session and record.number_sessions != UNLIMITED_SESSIONS:
        counter_store = get_chatbot_session_counter_store()
        used = await counter_store.get_count(normalized)
        if used >= record.number_sessions:
            return (
                jsonify({"error": "quota_exceeded", "chatbotName": normalized, "limit": record.number_sessions}),
                403,
            )
        # Admit and count this new session. The check→increment gap can let concurrent new sessions
        # exceed the cap by a hair (benign); the increment itself is atomic so counts are never lost.
        await counter_store.increment(normalized)
    return None


async def get_authenticated_free_user() -> FreeSession | None:
    auth_service = get_free_auth_service()
    return await auth_service.load_session(request.cookies.get(auth_service.session_cookie_name))


def build_free_session_payload(session: FreeSession) -> dict[str, Any]:
    # expiresAt/daysRemaining ride along on every session response so the Free Bot can show the
    # trial countdown (profile row + expiry banner) without a second round trip.
    return {
        "displayName": session.display_name,
        "email": session.email,
        "expiresAt": session.expires_at,
        "daysRemaining": session.days_remaining,
    }


async def get_authenticated_internal_admin():
    auth_service = get_internal_admin_auth_service()
    return await auth_service.load_session(request.cookies.get(auth_service.session_cookie_name))


def get_authenticated_simple_chatbot_session(chatbot_name: str) -> SimpleChatbotSession | None:
    auth_service = get_simple_chatbot_auth_service()
    normalized_chatbot_name = normalize_chatbot_name(chatbot_name) or chatbot_name.strip().lower()
    if not auth_service.is_protected_chatbot(normalized_chatbot_name):
        return None
    return auth_service.load_session(
        normalized_chatbot_name,
        request.cookies.get(auth_service.get_session_cookie_name(normalized_chatbot_name)),
    )


def get_simple_auth_required_chatbot_name(requested_chatbot_name: str | None = None) -> str | None:
    auth_service = get_simple_chatbot_auth_service()
    route_chatbot_name = get_request_route_chatbot_name()
    if auth_service.is_protected_chatbot(route_chatbot_name):
        return route_chatbot_name
    if auth_service.is_protected_chatbot(requested_chatbot_name):
        return requested_chatbot_name
    return None


def build_simple_auth_required_response(chatbot_name: str):
    return jsonify({"message": SIMPLE_CHATBOT_AUTH_REQUIRED_MESSAGE, "chatbotName": chatbot_name}), 401


def require_simple_chatbot_route_session(chatbot_name: str):
    normalized_chatbot_name = normalize_chatbot_name(chatbot_name) or chatbot_name.strip().lower()
    auth_service = get_simple_chatbot_auth_service()
    if (
        auth_service.is_protected_chatbot(normalized_chatbot_name)
        and get_authenticated_simple_chatbot_session(normalized_chatbot_name) is None
    ):
        return build_simple_auth_required_response(normalized_chatbot_name)
    return None


def normalize_rak_username(raw_username: str | None) -> str | None:
    normalized_username = (raw_username or "").strip()
    if not normalized_username:
        return None
    return normalized_username if normalized_username in RAK_ALLOWED_USERNAMES else None


async def get_user_scoped_chatbot_user(chatbot_name: str, *, allow_query_param: bool = False) -> str | None:
    chatbot_name = normalize_chatbot_name(chatbot_name) or chatbot_name.strip().lower()
    if chatbot_name == FREE_CHATBOT_NAME:
        free_user = await get_authenticated_free_user()
        return free_user.email if free_user is not None else None

    if chatbot_name == RAK_CHATBOT_NAME:
        rak_session = get_authenticated_simple_chatbot_session(chatbot_name)
        if rak_session is None:
            return None

        requested_username = normalize_rak_username(request.headers.get("X-Chatbot-User"))
        if requested_username is None and allow_query_param:
            requested_username = normalize_rak_username(request.args.get("chatbot_user"))
        if requested_username is not None and requested_username != rak_session.user:
            return None
        return rak_session.user

    return None


def should_set_secure_session_cookie() -> bool:
    forwarded_proto = request.headers.get("X-Forwarded-Proto", "")
    if forwarded_proto:
        return forwarded_proto.split(",", 1)[0].strip().lower() == "https"
    return (
        request.scheme == "https"
        or os.getenv("WEBSITE_HOSTNAME") is not None
        or os.getenv("RUNNING_IN_PRODUCTION") is not None
    )


def resolve_requested_chatbot_name(
    request_json: dict[str, Any] | None = None, *, fallback_to_default: bool = False
) -> str | None:
    requested_chatbot_name = get_chatbot_name_from_request_json(request_json or {})
    if requested_chatbot_name:
        return requested_chatbot_name

    route_chatbot_name = get_request_route_chatbot_name()
    if route_chatbot_name in KNOWN_CHATBOT_NAMES:
        return route_chatbot_name

    return DEFAULT_CHATBOT_NAME if fallback_to_default else None


async def apply_saved_chatbot_prompt_override(request_json: dict[str, Any]) -> str | None:
    if not isinstance(request_json, dict):
        return None

    context = request_json.get("context")
    if not isinstance(context, dict):
        context = {}
        request_json["context"] = context

    overrides = context.get("overrides")
    if not isinstance(overrides, dict):
        overrides = {}
        context["overrides"] = overrides

    existing_prompt_template = overrides.get("prompt_template")
    if isinstance(existing_prompt_template, str):
        return resolve_requested_chatbot_name(request_json)

    requested_chatbot_name = resolve_requested_chatbot_name(request_json, fallback_to_default=True)
    if requested_chatbot_name is None:
        return None

    # Dynamic (provisioned) bots carry their identity in the registry, not in source modules.
    # Built-in bots never enter this branch (resolve_active_dynamic_record returns None for them),
    # so their prompt/model resolution is completely unchanged.
    dynamic_record = await resolve_active_dynamic_record(requested_chatbot_name)
    if dynamic_record is not None:
        # Effective prompt = the bot's custom prompt, or the mode-aware default (tutor vs neutral Q&A)
        # when empty, + its configured `ansprache` (formal/informal) addressing directive.
        overrides["__saved_prompt_template"] = build_dynamic_system_prompt(dynamic_record, DEFAULT_DYNAMIC_PROMPT)

        # Model fallback: resolve_dynamic_chat_model owns the rule (provisioned `llm` if deployed,
        # else the mode-aware default). An explicit non-empty client `chat_model` (if the frontend
        # ever sends one) is respected.
        deployed_models = current_app.config.get(CONFIG_CHAT_MODEL_DEPLOYMENTS) or {}
        incoming_model = overrides.get("chat_model")
        if not (isinstance(incoming_model, str) and incoming_model.strip()):
            overrides["chat_model"] = resolve_dynamic_chat_model(dynamic_record, deployed_models)

        # Reasoning-effort fallback: if the chosen model supports reasoning, keep a valid incoming
        # effort (e.g. from Settings); otherwise fall back to the bot's provisioned effort. A
        # non-reasoning model (e.g. gpt-4.1) is left untouched (normalize drops effort for it).
        effective_model = overrides.get("chat_model")
        reasoning_support = (
            Approach.GPT_REASONING_MODELS.get(effective_model) if isinstance(effective_model, str) else None
        )
        if reasoning_support is not None:
            incoming_effort = str(overrides.get("reasoning_effort") or "").strip().lower()
            if incoming_effort not in reasoning_support.supported_efforts:
                overrides["reasoning_effort"] = resolve_dynamic_reasoning_effort(dynamic_record, effective_model)
        return requested_chatbot_name

    prompt_override = await get_chatbot_prompt_store().load_prompt(requested_chatbot_name)
    if prompt_override is not None:
        overrides["__saved_prompt_template"] = prompt_override.prompt
    return requested_chatbot_name


def build_prompt_admin_payload(
    chatbot_name: str,
    default_prompt: str | None,
    prompt_override: ChatbotPromptOverride | None,
) -> dict[str, Any]:
    current_prompt = prompt_override.prompt if prompt_override is not None else (default_prompt or "")
    return {
        "chatbotName": chatbot_name,
        "source": "override" if prompt_override is not None else "default",
        "currentPrompt": current_prompt,
        "defaultPrompt": default_prompt or "",
        "updatedAt": prompt_override.updated_at if prompt_override is not None else None,
    }


async def serve_spa_index(chatbot_name: str | None = None, embed_public_id: str | None = None):
    # Allow the app to be embedded in a cross-origin iframe (the embeddable widget). When a chatbot
    # is in scope we lock `frame-ancestors` to that bot's whitelist (origins only — CSP cannot match
    # paths); with no whitelist (or no bot) framing stays permissive (`*`).
    frame_ancestors = "*"
    if chatbot_name is not None:
        embed_config_store = current_app.config.get(CONFIG_CHATBOT_EMBED_CONFIG_STORE)
        if embed_config_store is not None:
            allowed_rules = await embed_config_store.load_allowed_rules(chatbot_name)
            frame_ancestors = rules_to_frame_ancestors(allowed_rules)

    # Avoid caching index.html so route changes and new bundles are picked up immediately.
    if embed_public_id is not None and chatbot_name is not None:
        # The anonymized iframe route serves a templated index.html that tells the SPA which bot to
        # mount, so the readable name never appears in the host page DOM or the iframe `src`. This
        # marker lives inside the cross-origin iframe document, which the host page cannot read.
        index_html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
        injection = (
            "<script>"
            f"window.__EMBED_CHATBOT_NAME__={json.dumps(chatbot_name)};"
            f"window.__EMBED_PUBLIC_ID__={json.dumps(embed_public_id)};"
            "</script>"
        )
        index_html = (
            index_html.replace("</head>", injection + "</head>", 1)
            if "</head>" in index_html
            else injection + index_html
        )
        response = await make_response(index_html)
        response.headers["Content-Type"] = "text/html; charset=utf-8"
    else:
        response = await send_from_directory(STATIC_ROOT, "index.html")
    response.cache_control.no_store = True
    response.cache_control.max_age = 0
    response.headers["Pragma"] = "no-cache"
    # We never set X-Frame-Options, but strip it defensively in case a proxy injects one.
    response.headers.pop("X-Frame-Options", None)
    response.headers["Content-Security-Policy"] = f"frame-ancestors {frame_ancestors}"
    return response


@bp.route("/")
async def index():
    return await serve_spa_index()


# Empty page is recommended for login redirect to work.
# See https://github.com/AzureAD/microsoft-authentication-library-for-js/blob/dev/lib/msal-browser/docs/initialization.md#redirecturi-considerations for more information
@bp.route("/redirect")
async def redirect_page():
    return ""


@bp.route("/favicon.ico")
async def favicon():
    return await bp.send_static_file("favicon.ico")


@bp.route("/assets/<path:path>")
async def assets(path):
    return await send_from_directory(STATIC_ROOT / "assets", path)


@bp.route("/widget.js")
async def widget_loader():
    # Tiny dependency-free loader that website owners embed via a single <script> tag. Served
    # with a short cache so widget updates propagate automatically without customer changes.
    # The "." in the path means the /<chatbot_name> catch-all would 404 it, but this literal
    # route is matched first. Cross-origin <script> loading needs no CORS headers.
    response = await send_from_directory(STATIC_ROOT, "widget.js")
    response.headers["Content-Type"] = "application/javascript; charset=utf-8"
    response.cache_control.no_store = False
    response.cache_control.public = True
    response.cache_control.max_age = 300
    return response


# Bots that are not directly embeddable as a standalone page (router shell / redirects elsewhere).
EMBED_DEMO_EXCLUDED_CHATBOTS = {"internal", "public-test"}
EMBED_DEMO_DEFAULT_CHATBOT = "publishone"


@bp.route("/embed-demo")
async def embed_demo():
    # Live demo of the embeddable widget with a chatbot picker. The option list is injected from
    # KNOWN_CHATBOT_NAMES so it never drifts; the page itself loads /widget.js from this origin.
    template = (Path(__file__).resolve().parent / "embed_demo.html").read_text(encoding="utf-8")
    names = sorted(name for name in KNOWN_CHATBOT_NAMES if name not in EMBED_DEMO_EXCLUDED_CHATBOTS)
    default = EMBED_DEMO_DEFAULT_CHATBOT if EMBED_DEMO_DEFAULT_CHATBOT in names else DEFAULT_CHATBOT_NAME
    if default in names:
        names.remove(default)
        names.insert(0, default)
    options = "\n".join(
        f'<option value="{get_public_id(name)}">{name}</option>'
        for name in names
        if is_embeddable(name)
    )
    response = await make_response(template.replace("{{CHATBOT_OPTIONS}}", options))
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    response.cache_control.no_store = True
    return response


# Per-bot launcher bubble background colors returned by the widget config endpoint. Mirrors the
# `primary` values in app/frontend/src/chatbots/shared/theme/chatbotThemes.ts — keep in sync, except
# where a bot's visible chrome differs from its abstract primary (see hyrox-assessment below).
# Anything not listed falls back to EMBED_LAUNCHER_DEFAULT_COLOR (matches the widget's own fallback).
EMBED_LAUNCHER_DEFAULT_COLOR = "#4f46e5"
EMBED_LAUNCHER_COLORS = {
    "agindo": "#e2c200",
    # bbsa's navbar is white (its nav wordmark is dark-on-white), so the launcher uses the brand
    # dark teal rather than the visible chrome — a white bubble would vanish on a host page.
    "bbsa": "#032D3C",
    "bensberg": "#005155",
    "demo": "#313335",
    "fbn": "#00cc96",
    "fhg": "#669d24",
    # hyrox-assessment's brand is black chrome + yellow accent (its theme overrides the navbar to a
    # black background with #FFED00 text). The launcher mirrors that chrome rather than the abstract
    # yellow primary: a black bubble with a yellow icon (see EMBED_LAUNCHER_ICON_COLORS below).
    "hyrox-assessment": "#000000",
    "knoll": "#0199fe",
    "lemon": "#fec701",
    "moodle": "#f98012",
    "nerilio": "#ac44c6",
    "snap": "#ac44c6",
    "free": "#AC44C6",
    "publishone": "#212529",
    "publishone2": "#212529",
    "rak": "#e30613",
    "sartorius": "#ffed00",
    "steuertipps": "#ffe016",
    "vjoonk4": "#00cc96",
}

# Optional per-bot launcher icon (foreground) color. Unset => the widget's default white icon. Use
# only when the bubble background is dark/branded enough that a colored icon reads better than white,
# e.g. hyrox-assessment's yellow icon on the black bubble, matching its navbar accent.
EMBED_LAUNCHER_ICON_COLORS = {
    "hyrox-assessment": "#FFED00",
    # Bright-yellow bubbles whose chrome already uses a black foreground (their navbar text resolves
    # to black); a white launcher icon washes out, so match the chrome with a dark icon. lemon and
    # agindo are intentionally left on the default white icon.
    "sartorius": "#000000",
    "steuertipps": "#000000",
}


async def resolve_servable_embed_target(public_id: str) -> tuple[str | None, ChatbotRegistryRecord | None]:
    """Resolve a widget public ID to a bot that may actually be served in an iframe.

    Returns ``(chatbot_name, dynamic_record)`` — the record is None for built-in bots. Built-in IDs
    resolve from the committed map with no I/O; dynamic IDs come from the registry and must be
    ACTIVE, so a stopped bot's live embeds go dark exactly like its `/<botName>` route does. The
    registry store is read defensively (None when unconfigured) because this is a public path.
    """
    registry_store = current_app.config.get(CONFIG_CHATBOT_REGISTRY_STORE)
    chatbot_name = await resolve_public_id_async(public_id, registry_store)
    if chatbot_name is None:
        return None, None
    if chatbot_name in KNOWN_CHATBOT_NAMES:
        return chatbot_name, None
    dynamic_record = await resolve_active_dynamic_record(chatbot_name)
    if dynamic_record is None:
        return None, None
    return chatbot_name, dynamic_record


def embed_launcher_colors(chatbot_name: str, dynamic_record: ChatbotRegistryRecord | None) -> tuple[str, str | None]:
    """The (bubble, icon) launcher colors for a bot. Dynamic bots use their provisioned primary."""
    if dynamic_record is not None:
        design = dynamic_record.design if isinstance(dynamic_record.design, dict) else {}
        provisioned_color = design.get("color_primary")
        color = provisioned_color if isinstance(provisioned_color, str) and provisioned_color.strip() else None
        return color or EMBED_LAUNCHER_DEFAULT_COLOR, None
    return (
        EMBED_LAUNCHER_COLORS.get(chatbot_name, EMBED_LAUNCHER_DEFAULT_COLOR),
        EMBED_LAUNCHER_ICON_COLORS.get(chatbot_name),
    )


@bp.route("/embed/<public_id>/config")
async def embed_widget_config(public_id: str):
    # Public, CORS-enabled config the widget fetches cross-origin from the host page before it
    # renders anything. Returns only non-secret data (launcher color + whitelist rules) and never
    # the chatbot name, so the host page cannot recover the bot identity from this response.
    chatbot_name, dynamic_record = await resolve_servable_embed_target(public_id)
    if chatbot_name is None:
        response = jsonify({"ok": False})
        response.status_code = 404
    else:
        embed_config_store = current_app.config.get(CONFIG_CHATBOT_EMBED_CONFIG_STORE)
        allowed_rules = await embed_config_store.load_allowed_rules(chatbot_name) if embed_config_store else []
        primary_color, launcher_icon_color = embed_launcher_colors(chatbot_name, dynamic_record)
        response = jsonify(
            {
                "ok": True,
                "primaryColor": primary_color,
                "launcherIconColor": launcher_icon_color,
                "allowAll": len(allowed_rules) == 0,
                "rules": allowed_rules,
            }
        )
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.route("/embed/<public_id>")
async def embed_chatbot_entry(public_id: str):
    # Anonymized iframe target. Resolves the public ID server-side and serves the SPA with the
    # resolved bot injected, so the readable chatbot name never appears in the host page DOM or the
    # iframe `src`. Per-bot `frame-ancestors` is applied via serve_spa_index. Dynamic (provisioned)
    # bots resolve here too; the SPA mounts them through the generic bot route.
    chatbot_name, _dynamic_record = await resolve_servable_embed_target(public_id)
    if chatbot_name is None:
        return quart_redirect("/")
    return await serve_spa_index(chatbot_name=chatbot_name, embed_public_id=public_id)


@bp.route("/chatbots")
@bp.route("/chatbots/")
@bp.route("/chatbots/<path:subpath>")
async def chatbot_directory(subpath: str | None = None):
    return await serve_spa_index()


@bp.route("/upload-files")
@bp.route("/upload-files/")
@bp.route("/upload-files/<path:subpath>")
async def upload_files_page(subpath: str | None = None):
    return await serve_spa_index()


@bp.route("/free-users")
@bp.route("/free-users/")
@bp.route("/free-users/<path:subpath>")
@bp.route("/public-test-users")
@bp.route("/public-test-users/")
@bp.route("/public-test-users/<path:subpath>")
async def free_users_page(subpath: str | None = None):
    if request.path.startswith("/public-test-users"):
        target = f"/free-users{f'/{subpath}' if subpath else ''}"
        return quart_redirect(target)
    return await serve_spa_index()


@bp.route("/manage-prompts")
@bp.route("/manage-prompts/")
@bp.route("/manage-prompts/<path:subpath>")
async def manage_prompts_page(subpath: str | None = None):
    return await serve_spa_index()


@bp.route("/admin")
@bp.route("/admin/")
@bp.route("/admin/<path:subpath>")
async def admin_page(subpath: str | None = None):
    # Single SPA shell for the consolidated internal admin tools (Chatbots, Prompts, Uploads,
    # nerilio users, Embed demo). Deep links like /admin/prompts serve index.html so the React
    # router can mount the right tab; the old per-tool routes above still serve the SPA and the
    # frontend redirects them into the matching /admin/* tab.
    return await serve_spa_index()


@bp.route("/<chatbot_name>")
@bp.route("/<chatbot_name>/<path:subpath>")
async def chatbot_entry(chatbot_name: str, subpath: str | None = None):
    # Avoid treating API/static endpoints as chatbot names.
    if chatbot_name in NON_CHATBOT_FRONTEND_PREFIXES or "." in chatbot_name:
        abort(404)
    if chatbot_name == "public-test":
        target = f"/{FREE_CHATBOT_ROUTE_NAME}{f'/{subpath}' if subpath else ''}"
        return quart_redirect(target)
    # Built-in bots route as before; active provisioned (dynamic) bots are also routable. Stopped or
    # unknown names redirect home (so `stop` immediately makes a dynamic bot's route unreachable).
    if chatbot_name not in KNOWN_CHATBOT_NAMES and await resolve_active_dynamic_record(chatbot_name) is None:
        return quart_redirect("/")
    # Lock framing on the canonical route too (origins only), so a determined embedder cannot dodge
    # the whitelist by iframing /<name>?embed=1 directly instead of the anonymized /embed route.
    return await serve_spa_index(chatbot_name=normalize_chatbot_name(chatbot_name))


@bp.route("/content/<path:path>")
@authenticated_path
async def content_file(path: str, auth_claims: dict[str, Any]):
    """
    Serve content files from blob storage from within the app to keep the example self-contained.
    *** NOTE *** if you are using app services authentication, this route will return unauthorized to all users that are not logged in
    if AZURE_ENFORCE_ACCESS_CONTROL is not set or false, logged in users can access all files regardless of access control
    if AZURE_ENFORCE_ACCESS_CONTROL is set to true, logged in users can only access files they have access to
    This is also slow and memory hungry.
    """
    # Remove page number from path, filename-1.txt -> filename.txt
    # This shouldn't typically be necessary as browsers don't send hash fragments to servers
    if path.find("#page=") > 0:
        path_parts = path.rsplit("#page=", 1)
        path = path_parts[0]
    current_app.logger.info("Opening file %s", path)
    result = None
    chatbot_upload_managers: dict[str, ChatbotUploadStrategy] = current_app.config.get(
        CONFIG_CHATBOT_UPLOAD_MANAGERS, {}
    )
    requested_chatbot_name = normalize_chatbot_name(request.args.get("chatbot_name"))
    normalized_path = path
    path_chatbot_name = None
    if "/" in path:
        path_first_segment, remaining_path = path.split("/", 1)
        normalized_path_first_segment = normalize_chatbot_name(path_first_segment)
        if normalized_path_first_segment in KNOWN_CHATBOT_NAMES and remaining_path:
            path_chatbot_name = normalized_path_first_segment
            requested_chatbot_name = path_chatbot_name
            normalized_path = remaining_path

    if requested_chatbot_name is None:
        referer = request.headers.get("Referer")
        if referer:
            referer_first_segment = normalize_chatbot_name(urlparse(referer).path.strip("/").split("/", 1)[0])
            if referer_first_segment in KNOWN_CHATBOT_NAMES:
                requested_chatbot_name = referer_first_segment
    simple_auth_chatbot_name = get_simple_auth_required_chatbot_name(requested_chatbot_name)
    if simple_auth_chatbot_name and get_authenticated_simple_chatbot_session(simple_auth_chatbot_name) is None:
        abort(401)

    requested_user_identifier = None
    if requested_chatbot_name in {FREE_CHATBOT_NAME, RAK_CHATBOT_NAME}:
        requested_user_identifier = await get_user_scoped_chatbot_user(requested_chatbot_name, allow_query_param=True)
        if requested_user_identifier is None:
            abort(401)

    if requested_chatbot_name:
        chatbot_upload_manager = chatbot_upload_managers.get(requested_chatbot_name)
        if chatbot_upload_manager is not None:
            if requested_chatbot_name in {FREE_CHATBOT_NAME, RAK_CHATBOT_NAME}:
                result = await chatbot_upload_manager.download_file(
                    normalized_path,
                    user_identifier=requested_user_identifier,
                )
            else:
                result = await chatbot_upload_manager.download_file(normalized_path)

    if result is None and requested_chatbot_name is None:
        auth_service = get_simple_chatbot_auth_service()
        for chatbot_name, chatbot_upload_manager in chatbot_upload_managers.items():
            if chatbot_name in {FREE_CHATBOT_NAME, RAK_CHATBOT_NAME}:
                continue
            if (
                auth_service.is_protected_chatbot(chatbot_name)
                and get_authenticated_simple_chatbot_session(chatbot_name) is None
            ):
                continue
            result = await chatbot_upload_manager.download_file(normalized_path)
            if result is not None:
                break

    if result is None:
        blob_manager: BlobManager = current_app.config[CONFIG_GLOBAL_BLOB_MANAGER]

        if requested_chatbot_name and path_chatbot_name is None:
            result = await blob_manager.download_blob(f"{requested_chatbot_name}/{normalized_path}")

        if result is None:
            # Get bytes and properties from the blob manager
            result = await blob_manager.download_blob(path)

    if result is None:
        current_app.logger.info("Path not found in general Blob container: %s", path)
        if current_app.config[CONFIG_USER_UPLOAD_ENABLED]:
            user_oid = auth_claims["oid"]
            user_blob_manager: AdlsBlobManager = current_app.config[CONFIG_USER_BLOB_MANAGER]
            result = await user_blob_manager.download_blob(path, user_oid=user_oid)
            if result is None:
                current_app.logger.exception("Path not found in DataLake: %s", path)

    if not result:
        abort(404)

    content, properties = result

    if not properties or "content_settings" not in properties:
        abort(404)

    mime_type = properties["content_settings"]["content_type"]
    if mime_type == "application/octet-stream":
        mime_type = mimetypes.guess_type(path)[0] or "application/octet-stream"

    # Create a BytesIO object from the bytes
    blob_file = io.BytesIO(content)
    return await send_file(blob_file, mimetype=mime_type, as_attachment=False, attachment_filename=path)


@bp.route("/content2/<path:path>")
@authenticated_path
async def content2_file(path: str, auth_claims: dict[str, Any]):
    """
    Serve source files for provisioned ("generic") chatbots from the dedicated `content2`
    container (layout content2/<bot_name>/<file>). The content2 auto-indexer indexes these
    files in place and never mirrors them into the `content` container, so the standard
    /content route cannot resolve them; this route reads directly from `content2`.
    """
    # Remove page number from path, filename-1.txt -> filename.txt
    if path.find("#page=") > 0:
        path = path.rsplit("#page=", 1)[0]
    current_app.logger.info("Opening content2 file %s", path)
    blob_manager: BlobManager = current_app.config[CONFIG_GLOBAL_BLOB_MANAGER]
    result = await blob_manager.download_blob(path, container=CONTENT2_STORAGE_CONTAINER)

    if not result:
        abort(404)

    content, properties = result

    if not properties or "content_settings" not in properties:
        abort(404)

    mime_type = properties["content_settings"]["content_type"]
    if mime_type == "application/octet-stream":
        mime_type = mimetypes.guess_type(path)[0] or "application/octet-stream"

    blob_file = io.BytesIO(content)
    return await send_file(blob_file, mimetype=mime_type, as_attachment=False, attachment_filename=path)


class JSONEncoder(json.JSONEncoder):
    def default(self, o):
        if dataclasses.is_dataclass(o) and not isinstance(o, type):
            as_dict = dataclasses.asdict(o)
            if isinstance(o, DataPoints):
                # Drop optional data point collections that are not populated to keep API surface stable
                return {k: v for k, v in as_dict.items() if v is not None}
            data_points_payload = as_dict.get("data_points") if isinstance(as_dict, dict) else None
            if isinstance(data_points_payload, dict) and data_points_payload.get("citation_activity_details") is None:
                data_points_payload.pop("citation_activity_details")
            return as_dict
        return super().default(o)


async def format_as_ndjson(
    r: AsyncGenerator[dict, None], error_context: ErrorContext | None = None
) -> AsyncGenerator[str, None]:
    try:
        async for event in r:
            yield json.dumps(event, ensure_ascii=False, cls=JSONEncoder) + "\n"
    except Exception as error:
        logging.exception("Exception while generating response stream: %s", error)
        yield json.dumps(error_dict(error, error_context=error_context), ensure_ascii=False)


async def get_speech_service_token():
    speech_token = current_app.config.get(CONFIG_SPEECH_SERVICE_TOKEN)
    if speech_token is None or speech_token.expires_on < time.time() + 60:
        speech_token = await current_app.config[CONFIG_CREDENTIAL].get_token(
            "https://cognitiveservices.azure.com/.default"
        )
        current_app.config[CONFIG_SPEECH_SERVICE_TOKEN] = speech_token
    return speech_token


def get_speech_service_auth_token() -> str:
    return (
        "aad#"
        + current_app.config[CONFIG_SPEECH_SERVICE_ID]
        + "#"
        + current_app.config[CONFIG_SPEECH_SERVICE_TOKEN].token
    )


def resolve_speech_voice(chatbot_name: str | None) -> str:
    """Pick the speak-answer voice for a chatbot, falling back to the deployment default.

    AZURE_SPEECH_SERVICE_VOICE is shared by every speech-enabled bot, so a bot that needs a
    different voice sets `speech_voice` in its own config.py rather than moving the env var and
    silently repointing all the others.
    """
    default_voice = current_app.config[CONFIG_SPEECH_SERVICE_VOICE]
    if not chatbot_name:
        return default_voice

    normalized_name = normalize_chatbot_name(chatbot_name)
    # Gate on the known set before touching the config registry. This value comes straight off a
    # public query string, and `load_chatbot_config` feeds it into `import_module` and logs a full
    # traceback for anything that doesn't resolve — so without this an unknown name is both an
    # arbitrary import attempt and a way to flood the logs.
    if not normalized_name or normalized_name not in KNOWN_CHATBOT_NAMES:
        return default_voice

    chatbot_config = load_chatbot_config(normalized_name)
    return (chatbot_config.speech_voice if chatbot_config else None) or default_voice


@bp.post("/free-auth/signup")
@bp.post("/public-test-auth/signup")
async def free_signup():
    if not request.is_json:
        return jsonify({"errorKey": "authErrors.unexpected"}), 415

    request_json = await request.get_json()
    if not isinstance(request_json, dict):
        return jsonify({"errorKey": "authErrors.unexpected"}), 400
    auth_service = get_free_auth_service()
    try:
        verification_challenge = await auth_service.start_signup(
            first_name=str(request_json.get("firstName", "")),
            last_name=str(request_json.get("lastName", "")),
            display_name=str(request_json.get("displayName", "")),
            email=str(request_json.get("email", "")),
            password=str(request_json.get("password", "")),
            confirm_password=str(request_json.get("confirmPassword", "")),
        )
    except FreeAuthError as auth_error:
        return jsonify({"errorKey": auth_error.error_key}), auth_error.status_code

    return (
        jsonify(
            {
                "verificationRequired": True,
                "email": verification_challenge.email,
                "expiresInSeconds": verification_challenge.expires_in_seconds,
            }
        ),
        200,
    )


@bp.post("/free-auth/signup/verify")
@bp.post("/public-test-auth/signup/verify")
async def free_signup_verify():
    if not request.is_json:
        return jsonify({"errorKey": "authErrors.unexpected"}), 415

    request_json = await request.get_json()
    if not isinstance(request_json, dict):
        return jsonify({"errorKey": "authErrors.unexpected"}), 400
    auth_service = get_free_auth_service()
    try:
        session = await auth_service.verify_signup(
            email=str(request_json.get("email", "")),
            verification_code=str(request_json.get("verificationCode", "")),
        )
    except FreeAuthError as auth_error:
        return jsonify({"errorKey": auth_error.error_key}), auth_error.status_code

    response = jsonify({"session": build_free_session_payload(session)})
    auth_service.set_session_cookie(response, session, secure=should_set_secure_session_cookie())
    return response, 200


@bp.post("/free-auth/signup/resend")
@bp.post("/public-test-auth/signup/resend")
async def free_signup_resend():
    if not request.is_json:
        return jsonify({"errorKey": "authErrors.unexpected"}), 415

    request_json = await request.get_json()
    if not isinstance(request_json, dict):
        return jsonify({"errorKey": "authErrors.unexpected"}), 400
    auth_service = get_free_auth_service()
    try:
        verification_challenge = await auth_service.resend_signup_code(
            email=str(request_json.get("email", "")),
        )
    except FreeAuthError as auth_error:
        return jsonify({"errorKey": auth_error.error_key}), auth_error.status_code

    return (
        jsonify(
            {
                "verificationRequired": True,
                "email": verification_challenge.email,
                "expiresInSeconds": verification_challenge.expires_in_seconds,
            }
        ),
        200,
    )


@bp.post("/free-auth/password-reset")
@bp.post("/public-test-auth/password-reset")
async def free_password_reset_start():
    if not request.is_json:
        return jsonify({"errorKey": "authErrors.unexpected"}), 415

    request_json = await request.get_json()
    if not isinstance(request_json, dict):
        return jsonify({"errorKey": "authErrors.unexpected"}), 400
    auth_service = get_free_auth_service()
    try:
        verification_challenge = await auth_service.start_password_reset(
            email=str(request_json.get("email", "")),
        )
    except FreeAuthError as auth_error:
        return jsonify({"errorKey": auth_error.error_key}), auth_error.status_code

    return (
        jsonify(
            {
                "verificationRequired": True,
                "email": verification_challenge.email,
                "expiresInSeconds": verification_challenge.expires_in_seconds,
            }
        ),
        200,
    )


@bp.post("/free-auth/password-reset/resend")
@bp.post("/public-test-auth/password-reset/resend")
async def free_password_reset_resend():
    if not request.is_json:
        return jsonify({"errorKey": "authErrors.unexpected"}), 415

    request_json = await request.get_json()
    if not isinstance(request_json, dict):
        return jsonify({"errorKey": "authErrors.unexpected"}), 400
    auth_service = get_free_auth_service()
    try:
        verification_challenge = await auth_service.resend_password_reset_code(
            email=str(request_json.get("email", "")),
        )
    except FreeAuthError as auth_error:
        return jsonify({"errorKey": auth_error.error_key}), auth_error.status_code

    return (
        jsonify(
            {
                "verificationRequired": True,
                "email": verification_challenge.email,
                "expiresInSeconds": verification_challenge.expires_in_seconds,
            }
        ),
        200,
    )


@bp.post("/free-auth/password-reset/verify")
@bp.post("/public-test-auth/password-reset/verify")
async def free_password_reset_verify():
    if not request.is_json:
        return jsonify({"errorKey": "authErrors.unexpected"}), 415

    request_json = await request.get_json()
    if not isinstance(request_json, dict):
        return jsonify({"errorKey": "authErrors.unexpected"}), 400
    auth_service = get_free_auth_service()
    try:
        session = await auth_service.verify_password_reset(
            email=str(request_json.get("email", "")),
            verification_code=str(request_json.get("verificationCode", "")),
            password=str(request_json.get("password", "")),
            confirm_password=str(request_json.get("confirmPassword", "")),
        )
    except FreeAuthError as auth_error:
        return jsonify({"errorKey": auth_error.error_key}), auth_error.status_code

    response = jsonify({"session": build_free_session_payload(session)})
    auth_service.set_session_cookie(response, session, secure=should_set_secure_session_cookie())
    return response, 200


@bp.post("/free-auth/login")
@bp.post("/public-test-auth/login")
async def free_login():
    if not request.is_json:
        return jsonify({"errorKey": "authErrors.unexpected"}), 415

    request_json = await request.get_json()
    if not isinstance(request_json, dict):
        return jsonify({"errorKey": "authErrors.unexpected"}), 400
    auth_service = get_free_auth_service()
    try:
        session = await auth_service.login_user(
            email=str(request_json.get("email", "")),
            password=str(request_json.get("password", "")),
        )
    except FreeAuthError as auth_error:
        return jsonify({"errorKey": auth_error.error_key}), auth_error.status_code

    response = jsonify({"session": build_free_session_payload(session)})
    auth_service.set_session_cookie(response, session, secure=should_set_secure_session_cookie())
    return response, 200


@bp.get("/free-auth/session")
@bp.get("/public-test-auth/session")
async def free_session():
    auth_service = get_free_auth_service()
    session = await get_authenticated_free_user()
    if session is None:
        response = jsonify({"errorKey": "authErrors.invalidCredentials"})
        auth_service.clear_session_cookie(response)
        return response, 401

    return jsonify({"session": build_free_session_payload(session)}), 200


@bp.get("/free-auth/profile")
@bp.get("/public-test-auth/profile")
async def free_profile():
    auth_service = get_free_auth_service()
    session = await get_authenticated_free_user()
    if session is None:
        response = jsonify({"errorKey": "authErrors.invalidCredentials"})
        auth_service.clear_session_cookie(response)
        return response, 401

    account = await auth_service.load_account(session.email)
    if account is None:
        response = jsonify({"errorKey": "authErrors.accountNotFound"})
        auth_service.clear_session_cookie(response)
        return response, 404

    account_expiry = describe_account_expiry(account)
    return (
        jsonify(
            {
                "profile": {
                    "displayName": account.display_name,
                    "email": account.email,
                    "createdAt": account.created_at,
                    "updatedAt": account.updated_at,
                    "expiresAt": account_expiry.expires_at,
                    "daysRemaining": account_expiry.days_remaining,
                }
            }
        ),
        200,
    )


@bp.post("/free-auth/logout")
@bp.post("/public-test-auth/logout")
async def free_logout():
    auth_service = get_free_auth_service()
    response = jsonify({"ok": True})
    auth_service.clear_session_cookie(response)
    return response, 200


@bp.post("/internal-admin/login")
async def internal_admin_login():
    if not request.is_json:
        return jsonify({"message": "Request must be JSON."}), 415

    request_json = await request.get_json()
    if not isinstance(request_json, dict):
        return jsonify({"message": "Request payload must be an object."}), 400

    auth_service = get_internal_admin_auth_service()
    if not auth_service.has_password_configured():
        return jsonify({"message": INTERNAL_ADMIN_PASSWORD_MISSING_MESSAGE, "authenticated": False}), 503

    password = str(request_json.get("password", ""))
    if not auth_service.verify_password(password):
        return jsonify({"message": INTERNAL_ADMIN_INVALID_PASSWORD_MESSAGE, "authenticated": False}), 401

    response = jsonify({"authenticated": True})
    auth_service.set_session_cookie(response, secure=should_set_secure_session_cookie())
    return response, 200


@bp.get("/internal-admin/session")
async def internal_admin_session():
    auth_service = get_internal_admin_auth_service()
    if not auth_service.has_password_configured():
        return jsonify({"message": INTERNAL_ADMIN_PASSWORD_MISSING_MESSAGE, "authenticated": False}), 503

    internal_admin_session = await get_authenticated_internal_admin()
    return jsonify({"authenticated": internal_admin_session is not None}), 200


@bp.post("/internal-admin/logout")
async def internal_admin_logout():
    auth_service = get_internal_admin_auth_service()
    response = jsonify({"authenticated": False})
    auth_service.clear_session_cookie(response)
    return response, 200


@bp.get("/internal-admin/prompts")
@internal_admin_required
async def list_internal_admin_prompts():
    prompt_store = get_chatbot_prompt_store()
    overrides = await prompt_store.list_prompts()
    prompt_payload = [
        build_prompt_admin_payload(
            chatbot_name,
            get_chatbot_prompt(chatbot_name),
            overrides.get(chatbot_name),
        )
        for chatbot_name in get_registered_chatbot_names()
    ]
    return jsonify({"prompts": prompt_payload}), 200


@bp.put("/internal-admin/prompts/<chatbot_name>")
@internal_admin_required
async def save_internal_admin_prompt(chatbot_name: str):
    if not request.is_json:
        return jsonify({"message": "Request must be JSON."}), 415

    request_json = await request.get_json()
    if not isinstance(request_json, dict):
        return jsonify({"message": "Request payload must be an object."}), 400

    normalized_chatbot_name = chatbot_name.strip().lower()
    if normalized_chatbot_name not in set(get_registered_chatbot_names()):
        return jsonify({"message": "Unknown chatbot."}), 404

    prompt = request_json.get("prompt")
    if not isinstance(prompt, str):
        return jsonify({"message": "Prompt must be a string."}), 400

    default_prompt = get_chatbot_prompt(normalized_chatbot_name)
    prompt_store = get_chatbot_prompt_store()
    try:
        prompt_override = await prompt_store.save_prompt(
            normalized_chatbot_name,
            prompt,
            default_prompt=default_prompt,
        )
    except ValueError as error:
        return jsonify({"message": str(error)}), 400

    message = "Prompt saved successfully." if prompt_override is not None else "Prompt reset to default."
    return (
        jsonify(
            {
                "message": message,
                "prompt": build_prompt_admin_payload(normalized_chatbot_name, default_prompt, prompt_override),
            }
        ),
        200,
    )


@bp.delete("/internal-admin/prompts/<chatbot_name>")
@internal_admin_required
async def delete_internal_admin_prompt(chatbot_name: str):
    normalized_chatbot_name = chatbot_name.strip().lower()
    if normalized_chatbot_name not in set(get_registered_chatbot_names()):
        return jsonify({"message": "Unknown chatbot."}), 404

    prompt_store = get_chatbot_prompt_store()
    await prompt_store.delete_prompt(normalized_chatbot_name)
    default_prompt = get_chatbot_prompt(normalized_chatbot_name)
    return (
        jsonify(
            {
                "message": "Prompt reset to default.",
                "prompt": build_prompt_admin_payload(normalized_chatbot_name, default_prompt, None),
            }
        ),
        200,
    )


def build_embed_admin_payload(chatbot_name: str, config, *, public_id: str | None = None) -> dict[str, Any]:
    """Embed panel payload. ``public_id`` carries a dynamic bot's minted ID; built-ins fall back to
    the committed map."""
    return {
        "chatbotName": chatbot_name,
        "publicId": public_id if public_id is not None else get_public_id(chatbot_name),
        "allowedRules": list(config.allowed_rules) if config is not None else [],
        "updatedAt": config.updated_at if config is not None else None,
    }


async def resolve_embed_admin_public_id(chatbot_name: str) -> str | None:
    """The public ID the admin surfaces should show for a bot, minting one if a dynamic bot lacks it.

    Built-in bots read straight from the committed map. A dynamic bot normally has its ID from
    create; one provisioned before dynamic embedding existed is backfilled here, on an
    admin-triggered (i.e. rare, human-paced) request rather than on a hot path.
    """
    builtin_public_id = get_public_id(chatbot_name)
    if builtin_public_id is not None:
        return builtin_public_id
    record = await resolve_dynamic_record_any_state(chatbot_name)
    if record is None:
        return None
    record = await ensure_embed_public_id(get_chatbot_registry_store(), record)
    return get_record_public_id(record)


def build_builtin_chatbot_admin_payload(chatbot_name: str, approach: Approach) -> dict[str, Any]:
    """One built-in bot's EFFECTIVE chat settings, read off the approach a chat call would use.

    Startup only builds a per-bot `ChatReadRetrieveReadApproach` when that bot's `config.py`
    differs from the deployment defaults, so the bots whose config leaves `chatgpt_model` /
    `reasoning_effort` unset fall through to the default approach. Resolving through the same
    `chatbot_approaches.get(name, CONFIG_CHAT_APPROACH)` lookup as `/chat` therefore reports what a
    real request runs at, with no second copy of the resolution rules to drift — which is the whole
    point: the frontend directory used to hand-mirror these values from the deployment `.env`.

    `reasoningEffort` is None for a non-reasoning model (e.g. gpt-4.1), mirroring
    `resolve_dynamic_reasoning_effort` and the fact that effort is dropped downstream for them.

    `/internal` is reported as having no model of its own: it is a router shell whose
    `include_category` — and therefore the approach lookup that follows from it — resolves to the
    SELECTED source bot, so an internal session runs on that bot's model and effort. It also has no
    entry in `CHATBOT_PROMPT_MODULES`, so its `config.py` is never loaded and startup builds it no
    approach; naming any single model here would advertise one no internal session actually uses.
    """
    if chatbot_name == INTERNAL_ROUTER_CHATBOT_NAME:
        return {"name": chatbot_name, "llm": None, "reasoningEffort": None, "variesBySourceBot": True}

    chat_model = getattr(approach, "chatgpt_model", None)
    reasoning_effort = getattr(approach, "reasoning_effort", None)
    supports_reasoning = Approach.GPT_REASONING_MODELS.get(chat_model) if isinstance(chat_model, str) else None
    return {
        "name": chatbot_name,
        "llm": chat_model,
        "reasoningEffort": reasoning_effort if supports_reasoning is not None else None,
        "variesBySourceBot": False,
    }


@bp.get("/internal-admin/builtin-chatbots")
@internal_admin_required
async def list_internal_admin_builtin_chatbots():
    """Effective model/effort for every built-in bot, so the admin directory can stop hardcoding it.

    Deliberately a separate endpoint from `/internal-admin/dynamic-chatbots`, which stays
    provisioned-only — mixing the two sources there would blur the built-in/dynamic isolation
    invariant. Names are reported as the frontend routes them and resolved through
    `normalize_chatbot_name`, so the `public-test` alias reports `free`'s settings exactly as a
    chat request through that alias would.

    `mode` and the agentic-retrieval default are NOT here: both are frontend behavior with no
    backend fact behind them (the bot's own `Chat.tsx` owns the initial toggle state, and backend
    `prompt_mode` is `inject`/`override`, unrelated to Q&A vs Tutor).
    """
    chatbot_approaches: dict[str, Approach] = current_app.config.get(CONFIG_CHATBOT_CHAT_APPROACHES, {})
    default_approach: Approach = current_app.config[CONFIG_CHAT_APPROACH]
    chatbots = [
        build_builtin_chatbot_admin_payload(
            chatbot_name,
            chatbot_approaches.get(normalize_chatbot_name(chatbot_name) or chatbot_name, default_approach),
        )
        for chatbot_name in sorted(KNOWN_CHATBOT_NAMES)
    ]
    return jsonify({"chatbots": chatbots}), 200


def build_dynamic_chatbot_admin_payload(
    record: ChatbotRegistryRecord, deployed_models: dict[str, Any] | None
) -> dict[str, Any]:
    """One provisioned bot as the admin directory shows it.

    `llm`/`reasoningEffort` are the EFFECTIVE values (what a chat call would really use), not the
    raw provisioned strings, so a bot whose control panel sent an undeployed model does not display
    a model that cannot serve. `publicId` may be None only for a record whose backfill has not run
    yet; the frontend hides the Embed action in that case.
    """
    chat_model = resolve_dynamic_chat_model(record, deployed_models)
    return {
        "botName": record.bot_name,
        "displayName": record.display_name,
        "active": record.active,
        "publicId": get_record_public_id(record),
        "llm": chat_model,
        "reasoningEffort": resolve_dynamic_reasoning_effort(record, chat_model),
        "mode": derive_chatbot_mode(record.modes),
        "plan": record.plan,
        "numberSessions": record.number_sessions,
        "createdAt": record.created_at,
        "updatedAt": record.updated_at,
    }


@bp.get("/internal-admin/dynamic-chatbots")
@internal_admin_required
async def list_internal_admin_dynamic_chatbots():
    """Every provisioned (dynamic) bot, for the admin directory and the embed-demo picker.

    Built-in bots are NOT included — the frontend already has them compiled in, and mixing the two
    sources here would blur the isolation invariant. Stopped bots ARE included (flagged by
    `active`) so the directory shows the full estate; consumers that hand out embed snippets filter
    to active ones themselves. Any record missing a public ID is backfilled so the whole listing is
    immediately embeddable.
    """
    registry_store = get_chatbot_registry_store()
    records = await registry_store.list_records()
    deployed_models = current_app.config.get(CONFIG_CHAT_MODEL_DEPLOYMENTS) or {}
    chatbots: list[dict[str, Any]] = []
    for record in records.values():
        healed_record = await ensure_embed_public_id(registry_store, record)
        chatbots.append(build_dynamic_chatbot_admin_payload(healed_record, deployed_models))
    chatbots.sort(key=lambda entry: entry["botName"])
    return jsonify({"chatbots": chatbots}), 200


@bp.get("/internal-admin/embed-config/<chatbot_name>")
@internal_admin_required
async def get_internal_admin_embed_config(chatbot_name: str):
    normalized_chatbot_name = normalize_chatbot_name(chatbot_name)
    if not normalized_chatbot_name or not await is_embeddable_chatbot(normalized_chatbot_name):
        return jsonify({"message": "Unknown or non-embeddable chatbot."}), 404
    public_id = await resolve_embed_admin_public_id(normalized_chatbot_name)
    config = await get_chatbot_embed_config_store().load_config(normalized_chatbot_name)
    return (
        jsonify({"embedConfig": build_embed_admin_payload(normalized_chatbot_name, config, public_id=public_id)}),
        200,
    )


@bp.put("/internal-admin/embed-config/<chatbot_name>")
@internal_admin_required
async def save_internal_admin_embed_config(chatbot_name: str):
    if not request.is_json:
        return jsonify({"message": "Request must be JSON."}), 415

    request_json = await request.get_json()
    if not isinstance(request_json, dict):
        return jsonify({"message": "Request payload must be an object."}), 400

    normalized_chatbot_name = normalize_chatbot_name(chatbot_name)
    if not normalized_chatbot_name or not await is_embeddable_chatbot(normalized_chatbot_name):
        return jsonify({"message": "Unknown or non-embeddable chatbot."}), 404

    raw_rules = request_json.get("allowedRules")
    if not isinstance(raw_rules, list) or not all(isinstance(rule, str) for rule in raw_rules):
        return jsonify({"message": "allowedRules must be a list of strings."}), 400

    public_id = await resolve_embed_admin_public_id(normalized_chatbot_name)
    config = await get_chatbot_embed_config_store().save_rules(normalized_chatbot_name, raw_rules)
    return (
        jsonify(
            {
                "message": "Embed whitelist saved.",
                "embedConfig": build_embed_admin_payload(normalized_chatbot_name, config, public_id=public_id),
            }
        ),
        200,
    )


@bp.get("/free-admin/users")
@bp.get("/public-test-admin/users")
@internal_admin_required
async def list_free_admin_users():
    auth_service = get_free_auth_service()
    upload_manager = get_chatbot_upload_manager(FREE_CHATBOT_NAME)
    users_payload: list[dict[str, Any]] = []

    for account in await auth_service.list_accounts():
        uploaded_files = await upload_manager.list_files(user_identifier=account.email)
        account_expiry = describe_account_expiry(account)
        users_payload.append(
            {
                "displayName": account.display_name,
                "email": account.email,
                "createdAt": account.created_at,
                "updatedAt": account.updated_at,
                "uploadCount": len(uploaded_files),
                "uploadedFiles": uploaded_files,
                # Expired accounts stay in this list; the admin page splits them into its archive
                # tab instead of hiding them, because their email can no longer be re-registered.
                "expiresAt": account_expiry.expires_at,
                "isExpired": account_expiry.is_expired,
                "daysRemaining": account_expiry.days_remaining,
                "daysExpired": account_expiry.days_expired,
            }
        )

    return jsonify({"users": users_payload}), 200


@bp.delete("/free-admin/users/<path:email>")
@bp.delete("/public-test-admin/users/<path:email>")
@internal_admin_required
async def delete_free_admin_user(email: str):
    normalized_email = normalize_free_email(email)
    if normalized_email is None:
        return jsonify({"message": "Valid email is required."}), 400

    upload_manager = get_chatbot_upload_manager(FREE_CHATBOT_NAME)
    deleted_uploads, failed_uploads = await upload_manager.remove_all_files(user_identifier=normalized_email)
    if failed_uploads:
        return (
            jsonify(
                {
                    "message": "Unable to delete the user's uploaded files.",
                    "deletedUploadCount": len(deleted_uploads),
                    "failedUploads": failed_uploads,
                }
            ),
            500,
        )

    auth_service = get_free_auth_service()
    deleted_account = await auth_service.delete_account(normalized_email)
    if not deleted_account:
        return jsonify({"message": "nerilio user not found.", "deletedUploadCount": len(deleted_uploads)}), 404

    return (
        jsonify({"message": "nerilio user deleted successfully.", "deletedUploadCount": len(deleted_uploads)}),
        200,
    )


@bp.post("/free-admin/users/<path:email>/password")
@bp.post("/public-test-admin/users/<path:email>/password")
@internal_admin_required
async def reset_free_admin_user_password(email: str):
    if not request.is_json:
        return jsonify({"message": "Request must be JSON."}), 415

    request_json = await request.get_json()
    if not isinstance(request_json, dict):
        return jsonify({"message": "Request payload must be an object."}), 400

    auth_service = get_free_auth_service()
    try:
        updated_account = await auth_service.reset_account_password(
            email=email,
            password=str(request_json.get("password", "")),
            confirm_password=str(request_json.get("confirmPassword", "")),
        )
    except FreeAuthError as auth_error:
        return jsonify({"message": auth_error.error_key}), auth_error.status_code

    return (
        jsonify(
            {
                "message": "nerilio user password updated successfully.",
                "email": updated_account.email,
                "updatedAt": updated_account.updated_at,
            }
        ),
        200,
    )


@bp.post("/free-admin/users/<path:email>/reactivate")
@bp.post("/public-test-admin/users/<path:email>/reactivate")
@internal_admin_required
async def reactivate_free_admin_user(email: str):
    """Grant an archived account another access window, counted from now."""
    auth_service = get_free_auth_service()
    try:
        updated_account = await auth_service.reactivate_account(email=email)
    except FreeAuthError as auth_error:
        return jsonify({"message": auth_error.error_key}), auth_error.status_code

    account_expiry = describe_account_expiry(updated_account)
    return (
        jsonify(
            {
                "message": f"nerilio user reactivated for {FREE_ACCOUNT_LIFETIME_DAYS} days.",
                "email": updated_account.email,
                "updatedAt": updated_account.updated_at,
                "expiresAt": account_expiry.expires_at,
                "isExpired": account_expiry.is_expired,
                "daysRemaining": account_expiry.days_remaining,
                "daysExpired": account_expiry.days_expired,
            }
        ),
        200,
    )


@bp.route("/chat", methods=["POST"])
@authenticated
async def chat(auth_claims: dict[str, Any]):
    if not request.is_json:
        return jsonify({"error": "request must be json"}), 415
    request_json = await request.get_json()
    error_context = get_request_error_context(request_json)
    telemetry_app = unwrap_current_app()
    telemetry_store = current_app.config.get(CONFIG_TELEMETRY_STORE)
    telemetry_record = open_telemetry_turn(request_json, route="/chat", streaming=False)
    try:
        try:
            normalize_chatbot_request_overrides(request_json)
        except ValueError as error:
            finish_telemetry_turn(
                telemetry_app, telemetry_store, telemetry_record, status=telemetry_records.STATUS_REJECTED
            )
            return jsonify({"error": str(error)}), 400
        context = request_json.get("context", {})
        requested_chatbot_name = await apply_saved_chatbot_prompt_override(request_json)
        telemetry.set_identity_from_attributes(
            get_openlit_chatbot_attributes(request_json, requested_chatbot_name)
        )
        if requested_chatbot_name in {FREE_CHATBOT_NAME, RAK_CHATBOT_NAME}:
            chatbot_user = await get_user_scoped_chatbot_user(requested_chatbot_name)
            if chatbot_user is None:
                finish_telemetry_turn(
                    telemetry_app, telemetry_store, telemetry_record, status=telemetry_records.STATUS_REJECTED
                )
                return jsonify({"error": f"{requested_chatbot_name} requires login"}), 401
            overrides = context.setdefault("overrides", {})
            overrides["user"] = chatbot_user
        context["auth_claims"] = auth_claims
        # Reject stopped (inactive) dynamic bots and enforce the number_sessions quota before any model
        # work; built-in bots are never gated. A new session = the first turn of a chat (len(messages)<=1).
        is_new_session = len(request_json.get("messages") or []) <= 1
        gate = await enforce_dynamic_chatbot_gate(requested_chatbot_name, is_new_session=is_new_session)
        if gate is not None:
            finish_telemetry_turn(
                telemetry_app, telemetry_store, telemetry_record, status=telemetry_records.STATUS_REJECTED
            )
            return gate
        try:
            chatbot_approaches: dict[str, Approach] = current_app.config.get(CONFIG_CHATBOT_CHAT_APPROACHES, {})
            approach: Approach = (
                chatbot_approaches.get(requested_chatbot_name, current_app.config[CONFIG_CHAT_APPROACH])
                if requested_chatbot_name
                else current_app.config[CONFIG_CHAT_APPROACH]
            )

            # If session state is provided, persists the session state,
            # else creates a new session_id depending on the chat history options enabled.
            session_state = request_json.get("session_state")
            if session_state is None:
                session_state = create_session_id(
                    current_app.config[CONFIG_CHAT_HISTORY_COSMOS_ENABLED],
                    current_app.config[CONFIG_CHAT_HISTORY_BROWSER_ENABLED],
                )
            telemetry.set_session_id(session_state)
            openlit_attributes = get_openlit_chatbot_attributes(request_json, requested_chatbot_name)
            with openlit_chatbot_attributes_context(openlit_attributes):
                result = await approach.run(
                    request_json["messages"],
                    context=context,
                    session_state=session_state,
                )
            finish_telemetry_turn(
                telemetry_app, telemetry_store, telemetry_record, status=telemetry_records.STATUS_OK
            )
            return jsonify(result)
        except Exception as error:
            finish_telemetry_turn(
                telemetry_app,
                telemetry_store,
                telemetry_record,
                status=telemetry_records.STATUS_ERROR,
                error=error,
            )
            return error_response(error, "/chat", error_context=error_context)
    finally:
        # Belt and braces: `finish_telemetry_turn` is idempotent, so a path that somehow returned
        # without calling it still gets its row rather than leaking the envelope into the next
        # request on this task.
        finish_telemetry_turn(
            telemetry_app, telemetry_store, telemetry_record, status=telemetry_records.STATUS_OK
        )


@bp.route("/chat/stream", methods=["POST"])
@authenticated
async def chat_stream(auth_claims: dict[str, Any]):
    if not request.is_json:
        return jsonify({"error": "request must be json"}), 415
    request_json = await request.get_json()
    error_context = get_request_error_context(request_json)
    # Bound while the request context is still live -- see `finish_telemetry_turn` for why the
    # streaming path cannot look either of these up later.
    telemetry_app = unwrap_current_app()
    telemetry_store = current_app.config.get(CONFIG_TELEMETRY_STORE)
    telemetry_record = open_telemetry_turn(request_json, route="/chat/stream", streaming=True)
    try:
        normalize_chatbot_request_overrides(request_json)
    except ValueError as error:
        finish_telemetry_turn(
            telemetry_app, telemetry_store, telemetry_record, status=telemetry_records.STATUS_REJECTED
        )
        return jsonify({"error": str(error)}), 400
    context = request_json.get("context", {})
    requested_chatbot_name = await apply_saved_chatbot_prompt_override(request_json)
    telemetry.set_identity_from_attributes(get_openlit_chatbot_attributes(request_json, requested_chatbot_name))
    if requested_chatbot_name in {FREE_CHATBOT_NAME, RAK_CHATBOT_NAME}:
        chatbot_user = await get_user_scoped_chatbot_user(requested_chatbot_name)
        if chatbot_user is None:
            finish_telemetry_turn(
                telemetry_app, telemetry_store, telemetry_record, status=telemetry_records.STATUS_REJECTED
            )
            return jsonify({"error": f"{requested_chatbot_name} requires login"}), 401
        overrides = context.setdefault("overrides", {})
        overrides["user"] = chatbot_user
    context["auth_claims"] = auth_claims
    # Reject stopped (inactive) dynamic bots and enforce the number_sessions quota before any model
    # work; built-in bots are never gated. A new session = the first turn of a chat (len(messages)<=1).
    is_new_session = len(request_json.get("messages") or []) <= 1
    gate = await enforce_dynamic_chatbot_gate(requested_chatbot_name, is_new_session=is_new_session)
    if gate is not None:
        finish_telemetry_turn(
            telemetry_app, telemetry_store, telemetry_record, status=telemetry_records.STATUS_REJECTED
        )
        return gate
    try:
        chatbot_approaches: dict[str, Approach] = current_app.config.get(CONFIG_CHATBOT_CHAT_APPROACHES, {})
        approach: Approach = (
            chatbot_approaches.get(requested_chatbot_name, current_app.config[CONFIG_CHAT_APPROACH])
            if requested_chatbot_name
            else current_app.config[CONFIG_CHAT_APPROACH]
        )

        # If session state is provided, persists the session state,
        # else creates a new session_id depending on the chat history options enabled.
        session_state = request_json.get("session_state")
        if session_state is None:
            session_state = create_session_id(
                current_app.config[CONFIG_CHAT_HISTORY_COSMOS_ENABLED],
                current_app.config[CONFIG_CHAT_HISTORY_BROWSER_ENABLED],
            )
        telemetry.set_session_id(session_state)
        openlit_attributes = get_openlit_chatbot_attributes(request_json, requested_chatbot_name)
        with openlit_chatbot_attributes_context(openlit_attributes):
            result = await approach.run_stream(
                request_json["messages"],
                context=context,
                session_state=session_state,
            )
        result = stream_with_openlit_chatbot_attributes(result, openlit_attributes)
        # Outermost, so it spans the entire stream: `run_stream` above only BUILDS the generator, and
        # every token of model work happens later, when the ASGI layer iterates the response body.
        result = stream_with_telemetry(result, telemetry_app, telemetry_store, telemetry_record)
        response = await make_response(format_as_ndjson(result, error_context=error_context))
        response.timeout = None  # type: ignore
        response.mimetype = "application/json-lines"
        return response
    except Exception as error:
        finish_telemetry_turn(
            telemetry_app, telemetry_store, telemetry_record, status=telemetry_records.STATUS_ERROR, error=error
        )
        return error_response(error, "/chat", error_context=error_context)


# Send MSAL.js settings to the client UI
@bp.route("/auth_setup", methods=["GET"])
def auth_setup():
    auth_helper = current_app.config[CONFIG_AUTH_CLIENT]
    return jsonify(auth_helper.get_auth_setup_for_client())


@bp.post("/chatbot-auth/<chatbot_name>/login")
async def simple_chatbot_login(chatbot_name: str):
    normalized_chatbot_name = normalize_chatbot_name(chatbot_name) or chatbot_name.strip().lower()
    auth_service = get_simple_chatbot_auth_service()
    if not auth_service.is_protected_chatbot(normalized_chatbot_name):
        return jsonify({"message": "Unknown protected chatbot.", "authenticated": False}), 404
    if not request.is_json:
        return jsonify({"message": "Request must be JSON.", "authenticated": False}), 415

    request_json = await request.get_json()
    if not isinstance(request_json, dict):
        return jsonify({"message": "Request payload must be an object.", "authenticated": False}), 400

    username = str(request_json.get("username", ""))
    password = str(request_json.get("password", ""))
    session = auth_service.verify_credentials(normalized_chatbot_name, username, password)
    if session is None:
        return jsonify({"message": SIMPLE_CHATBOT_AUTH_INVALID_CREDENTIALS_MESSAGE, "authenticated": False}), 401

    response = jsonify({"authenticated": True, "user": session.user})
    auth_service.set_session_cookie(response, session, secure=should_set_secure_session_cookie())
    return response, 200


@bp.get("/chatbot-auth/<chatbot_name>/session")
async def simple_chatbot_session(chatbot_name: str):
    normalized_chatbot_name = normalize_chatbot_name(chatbot_name) or chatbot_name.strip().lower()
    auth_service = get_simple_chatbot_auth_service()
    if not auth_service.is_protected_chatbot(normalized_chatbot_name):
        return jsonify({"message": "Unknown protected chatbot.", "authenticated": False}), 404

    session = get_authenticated_simple_chatbot_session(normalized_chatbot_name)
    if session is None:
        return jsonify({"authenticated": False}), 200
    return jsonify({"authenticated": True, "user": session.user}), 200


@bp.post("/chatbot-auth/<chatbot_name>/logout")
async def simple_chatbot_logout(chatbot_name: str):
    normalized_chatbot_name = normalize_chatbot_name(chatbot_name) or chatbot_name.strip().lower()
    auth_service = get_simple_chatbot_auth_service()
    if not auth_service.is_protected_chatbot(normalized_chatbot_name):
        return jsonify({"message": "Unknown protected chatbot.", "authenticated": False}), 404

    response = jsonify({"authenticated": False})
    auth_service.clear_session_cookie(response, normalized_chatbot_name, secure=should_set_secure_session_cookie())
    return response, 200


@bp.route("/bot-config/<chatbot_name>", methods=["GET"])
async def bot_config(chatbot_name: str):
    """Public bootstrap config for an ACTIVE DYNAMIC bot (theme, greeting, disclaimer, mode, login).

    Dynamic bots only — built-in bots resolve to None here (their config is baked into the frontend),
    so this never exposes a built-in. The system prompt and other internals are intentionally not
    returned. Unauthenticated, like /config, so the bot page can bootstrap before any login gate.
    """
    record = await resolve_active_dynamic_record(chatbot_name)
    if record is None:
        abort(404)
    return jsonify(build_bot_config_payload(record))


@bp.route("/config", methods=["GET"])
def config():
    return jsonify(
        {
            "showMultimodalOptions": current_app.config[CONFIG_MULTIMODAL_ENABLED],
            "showSemanticRankerOption": current_app.config[CONFIG_SEMANTIC_RANKER_DEPLOYED],
            "showQueryRewritingOption": current_app.config[CONFIG_QUERY_REWRITING_ENABLED],
            "showReasoningEffortOption": current_app.config[CONFIG_REASONING_EFFORT_ENABLED],
            "streamingEnabled": current_app.config[CONFIG_STREAMING_ENABLED],
            "availableChatModels": current_app.config[CONFIG_AVAILABLE_CHAT_MODELS],
            "defaultChatModel": current_app.config[CONFIG_DEFAULT_CHAT_MODEL],
            "defaultReasoningEffort": current_app.config[CONFIG_DEFAULT_REASONING_EFFORT],
            "defaultRetrievalReasoningEffort": current_app.config[CONFIG_DEFAULT_RETRIEVAL_REASONING_EFFORT],
            "reasoningCapableChatModels": current_app.config[CONFIG_REASONING_CHAT_MODELS],
            "chatModelReasoningEfforts": current_app.config[CONFIG_CHAT_MODEL_REASONING_EFFORTS],
            "showVectorOption": current_app.config[CONFIG_VECTOR_SEARCH_ENABLED],
            "showUserUpload": current_app.config[CONFIG_USER_UPLOAD_ENABLED],
            "showLanguagePicker": current_app.config[CONFIG_LANGUAGE_PICKER_ENABLED],
            "showSpeechInput": current_app.config[CONFIG_SPEECH_INPUT_ENABLED],
            "showSpeechOutputBrowser": current_app.config[CONFIG_SPEECH_OUTPUT_BROWSER_ENABLED],
            "showSpeechOutputAzure": current_app.config[CONFIG_SPEECH_OUTPUT_AZURE_ENABLED],
            "showSpeechAvatar": current_app.config[CONFIG_SPEECH_AVATAR_ENABLED],
            "showChatHistoryBrowser": current_app.config[CONFIG_CHAT_HISTORY_BROWSER_ENABLED],
            "showChatHistoryCosmos": current_app.config[CONFIG_CHAT_HISTORY_COSMOS_ENABLED],
            "showAgenticRetrievalOption": current_app.config[CONFIG_AGENTIC_KNOWLEDGEBASE_ENABLED],
            "showLlmWikiOption": current_app.config[CONFIG_LLM_WIKI_ENABLED],
            "ragSearchTextEmbeddings": current_app.config[CONFIG_RAG_SEARCH_TEXT_EMBEDDINGS],
            "ragSearchImageEmbeddings": current_app.config[CONFIG_RAG_SEARCH_IMAGE_EMBEDDINGS],
            "ragSendTextSources": current_app.config[CONFIG_RAG_SEND_TEXT_SOURCES],
            "ragSendImageSources": current_app.config[CONFIG_RAG_SEND_IMAGE_SOURCES],
            "webSourceEnabled": current_app.config[CONFIG_WEB_SOURCE_ENABLED],
            "sharepointSourceEnabled": current_app.config[CONFIG_SHAREPOINT_SOURCE_ENABLED],
            "internalSourceBots": get_internal_source_bot_options(),
        }
    )


@bp.route("/speech", methods=["POST"])
async def speech():
    if not request.is_json:
        return jsonify({"error": "request must be json"}), 415

    request_json = await request.get_json()
    text = request_json["text"]
    try:
        await get_speech_service_token()
        # Construct a token as described in documentation:
        # https://learn.microsoft.com/azure/ai-services/speech-service/how-to-configure-azure-ad-auth?pivots=programming-language-python
        speech_config = SpeechConfig(
            auth_token=get_speech_service_auth_token(),
            region=current_app.config[CONFIG_SPEECH_SERVICE_LOCATION],
        )
        speech_config.speech_synthesis_voice_name = current_app.config[CONFIG_SPEECH_SERVICE_VOICE]
        speech_config.set_speech_synthesis_output_format(SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3)
        synthesizer = SpeechSynthesizer(speech_config=speech_config, audio_config=None)
        result: SpeechSynthesisResult = synthesizer.speak_text_async(text).get()
        if result.reason == ResultReason.SynthesizingAudioCompleted:
            return result.audio_data, 200, {"Content-Type": "audio/mp3"}
        elif result.reason == ResultReason.Canceled:
            cancellation_details = result.cancellation_details
            current_app.logger.error(
                "Speech synthesis canceled: %s %s", cancellation_details.reason, cancellation_details.error_details
            )
            raise Exception("Speech synthesis canceled. Check logs for details.")
        else:
            current_app.logger.error("Unexpected result reason: %s", result.reason)
            raise Exception("Speech synthesis failed. Check logs for details.")
    except Exception as e:
        current_app.logger.exception("Exception in /speech")
        return jsonify({"error": str(e)}), 500


@bp.route("/speech/token", methods=["GET"])
async def speech_token():
    if CONFIG_SPEECH_SERVICE_ID not in current_app.config or CONFIG_SPEECH_SERVICE_LOCATION not in current_app.config:
        return jsonify({"error": "Speech service is not enabled."}), 400

    try:
        speech_token = await get_speech_service_token()
        return jsonify(
            {
                "token": get_speech_service_auth_token(),
                "region": current_app.config[CONFIG_SPEECH_SERVICE_LOCATION],
                "voice": resolve_speech_voice(request.args.get("chatbot")),
                "expiresAt": speech_token.expires_on,
            }
        )
    except Exception as error:
        current_app.logger.exception("Exception in /speech/token")
        return jsonify({"error": str(error)}), 500


@bp.route("/speech/avatar-token", methods=["GET"])
async def speech_avatar_token():
    """Issue everything a browser needs to open a real-time TTS avatar session.

    This is deliberately a separate endpoint from /speech/token rather than extra fields on it:
    the relay call is a live outbound request to Azure on every hit, and /speech/token is called
    by every bot that shows the "speak answer" button. Folding the two together would put that
    request in the path of plain text-to-speech, which needs no ICE servers at all.

    The avatar has its own voice setting. AZURE_SPEECH_SERVICE_VOICE is deployment-wide and shared
    by every speech-enabled bot, so reusing it here would change the existing speak-answer voice
    everywhere the moment the avatar voice was tuned.
    """
    if not current_app.config[CONFIG_SPEECH_AVATAR_ENABLED]:
        return jsonify({"error": "Speech avatar is not enabled."}), 400

    if CONFIG_SPEECH_SERVICE_ID not in current_app.config or CONFIG_SPEECH_SERVICE_LOCATION not in current_app.config:
        return jsonify({"error": "Speech service is not enabled."}), 400

    try:
        speech_token = await get_speech_service_token()
        ice_servers = await fetch_avatar_ice_servers(
            speech_service_id=current_app.config[CONFIG_SPEECH_SERVICE_ID],
            bearer_token=speech_token.token,
        )
        return jsonify(
            {
                "token": get_speech_service_auth_token(),
                "region": current_app.config[CONFIG_SPEECH_SERVICE_LOCATION],
                "voice": current_app.config[CONFIG_SPEECH_AVATAR_VOICE],
                "character": current_app.config[CONFIG_SPEECH_AVATAR_CHARACTER],
                "style": current_app.config[CONFIG_SPEECH_AVATAR_STYLE],
                "iceServers": ice_servers,
                "expiresAt": speech_token.expires_on,
            }
        )
    except Exception as error:
        current_app.logger.exception("Exception in /speech/avatar-token")
        return jsonify({"error": str(error)}), 500


@bp.post("/upload")
@authenticated
async def upload(auth_claims: dict[str, Any]):
    request_files = await request.files
    if "file" not in request_files:
        return jsonify({"message": "No file part in the request", "status": "failed"}), 400

    try:
        user_oid = auth_claims["oid"]
        file = request_files.getlist("file")[0]
        adls_manager: AdlsBlobManager = current_app.config[CONFIG_USER_BLOB_MANAGER]
        file_url = await adls_manager.upload_blob(file, file.filename, user_oid)
        ingester: UploadUserFileStrategy = current_app.config[CONFIG_INGESTER]
        await ingester.add_file(File(content=file, url=file_url, acls={"oids": [user_oid]}), user_oid=user_oid)
        return jsonify({"message": "File uploaded successfully"}), 200
    except Exception as error:
        current_app.logger.error("Error uploading file: %s", error)
        return jsonify({"message": "Error uploading file, check server logs for details.", "status": "failed"}), 500


@bp.post("/delete_uploaded")
@authenticated
async def delete_uploaded(auth_claims: dict[str, Any]):
    request_json = await request.get_json()
    filename = request_json.get("filename")
    user_oid = auth_claims["oid"]
    adls_manager: AdlsBlobManager = current_app.config[CONFIG_USER_BLOB_MANAGER]
    await adls_manager.remove_blob(filename, user_oid)
    ingester: UploadUserFileStrategy = current_app.config[CONFIG_INGESTER]
    await ingester.remove_file(filename, user_oid)
    return jsonify({"message": f"File {filename} deleted successfully"}), 200


@bp.get("/list_uploaded")
@authenticated
async def list_uploaded(auth_claims: dict[str, Any]):
    """Lists the uploaded documents for the current user.
    Only returns files directly in the user's directory, not in subdirectories.
    Excludes image files and the images directory."""
    user_oid = auth_claims["oid"]
    adls_manager: AdlsBlobManager = current_app.config[CONFIG_USER_BLOB_MANAGER]
    files = await adls_manager.list_blobs(user_oid)
    return jsonify(files), 200


@bp.get("/chatbot_uploads/<chatbot_name>")
async def list_chatbot_uploaded(chatbot_name: str):
    chatbot_upload_manager = get_chatbot_upload_manager(chatbot_name)
    simple_auth_response = require_simple_chatbot_route_session(chatbot_name)
    if simple_auth_response is not None:
        return simple_auth_response
    user_identifier = None
    if chatbot_name in {FREE_CHATBOT_NAME, RAK_CHATBOT_NAME}:
        user_identifier = await get_user_scoped_chatbot_user(chatbot_name)
        if user_identifier is None:
            return jsonify({"message": f"{chatbot_name} requires login"}), 401
    files = await chatbot_upload_manager.list_files(user_identifier=user_identifier)
    return jsonify(files), 200


@bp.post("/chatbot_uploads/<chatbot_name>")
async def upload_chatbot_files(chatbot_name: str):
    simple_auth_response = require_simple_chatbot_route_session(chatbot_name)
    if simple_auth_response is not None:
        return simple_auth_response

    request_files = await request.files
    uploaded_files = request_files.getlist("files") or request_files.getlist("file")
    uploaded_files = [file for file in uploaded_files if file and file.filename]
    if not uploaded_files:
        return jsonify({"message": "No file part in the request", "status": "failed"}), 400

    chatbot_upload_manager = get_chatbot_upload_manager(chatbot_name)
    user_identifier = None
    if chatbot_name in {FREE_CHATBOT_NAME, RAK_CHATBOT_NAME}:
        user_identifier = await get_user_scoped_chatbot_user(chatbot_name)
        if user_identifier is None:
            return jsonify({"message": f"{chatbot_name} requires login"}), 401
    succeeded: list[str] = []
    failed: list[dict[str, str]] = []
    upload_id = (request.headers.get("X-Upload-Id") or "").strip() or None

    try:
        for file_index, uploaded_file in enumerate(uploaded_files):
            if upload_id and await chatbot_upload_manager.is_cancel_requested(
                upload_id,
                user_identifier=user_identifier,
            ):
                failed.append({"filename": uploaded_file.filename, "message": "Upload canceled"})
                for skipped_file in uploaded_files[file_index + 1 :]:
                    failed.append({"filename": skipped_file.filename, "message": "Upload canceled"})
                break
            try:
                await chatbot_upload_manager.add_file(
                    File(content=uploaded_file),
                    upload_id=upload_id,
                    user_identifier=user_identifier,
                )
                succeeded.append(uploaded_file.filename)
            except ChatbotUploadCancelled:
                failed.append({"filename": uploaded_file.filename, "message": "Upload canceled"})
                for skipped_file in uploaded_files[file_index + 1 :]:
                    failed.append({"filename": skipped_file.filename, "message": "Upload canceled"})
                break
            except ValueError as error:
                failed.append({"filename": uploaded_file.filename, "message": str(error)})
            except Exception as error:
                current_app.logger.error("Error uploading chatbot file '%s': %s", uploaded_file.filename, error)
                failed.append({"filename": uploaded_file.filename, "message": "Unexpected upload failure"})
    finally:
        if upload_id:
            await chatbot_upload_manager.clear_cancel_request(upload_id, user_identifier=user_identifier)

    if succeeded and failed:
        message = f"Uploaded {len(succeeded)} file(s); {len(failed)} file(s) failed."
        return jsonify({"message": message, "uploadedFiles": succeeded, "failedFiles": failed}), 207
    if failed:
        status_code = 409 if all(file["message"] == "Upload canceled" for file in failed) else 400
        return jsonify({"message": failed[0]["message"], "uploadedFiles": [], "failedFiles": failed}), status_code

    message = (
        f"{len(succeeded)} file uploaded successfully."
        if len(succeeded) == 1
        else f"{len(succeeded)} files uploaded successfully."
    )
    return jsonify({"message": message, "uploadedFiles": succeeded, "failedFiles": []}), 200


@bp.post("/chatbot_uploads/<chatbot_name>/cancel/<upload_id>")
async def cancel_chatbot_upload(chatbot_name: str, upload_id: str):
    simple_auth_response = require_simple_chatbot_route_session(chatbot_name)
    if simple_auth_response is not None:
        return simple_auth_response

    upload_id = upload_id.strip()
    if not upload_id:
        return jsonify({"message": "Upload id is required"}), 400

    chatbot_upload_manager = get_chatbot_upload_manager(chatbot_name)
    user_identifier = None
    if chatbot_name in {FREE_CHATBOT_NAME, RAK_CHATBOT_NAME}:
        user_identifier = await get_user_scoped_chatbot_user(chatbot_name)
        if user_identifier is None:
            return jsonify({"message": f"{chatbot_name} requires login"}), 401
    await chatbot_upload_manager.request_cancel(upload_id, user_identifier=user_identifier)
    return jsonify({"message": "Upload cancellation requested"}), 202


@bp.delete("/chatbot_uploads/<chatbot_name>/<path:filename>")
async def delete_chatbot_uploaded(chatbot_name: str, filename: str):
    chatbot_upload_manager = get_chatbot_upload_manager(chatbot_name)
    simple_auth_response = require_simple_chatbot_route_session(chatbot_name)
    if simple_auth_response is not None:
        return simple_auth_response
    user_identifier = None
    if chatbot_name in {FREE_CHATBOT_NAME, RAK_CHATBOT_NAME}:
        user_identifier = await get_user_scoped_chatbot_user(chatbot_name)
        if user_identifier is None:
            return jsonify({"message": f"{chatbot_name} requires login"}), 401
    filename = os.path.basename(filename)
    await chatbot_upload_manager.remove_file(filename, user_identifier=user_identifier)
    return jsonify({"message": f"File {filename} deleted successfully"}), 200


@bp.delete("/chatbot_uploads/<chatbot_name>")
async def delete_all_chatbot_uploaded(chatbot_name: str):
    chatbot_upload_manager = get_chatbot_upload_manager(chatbot_name)
    simple_auth_response = require_simple_chatbot_route_session(chatbot_name)
    if simple_auth_response is not None:
        return simple_auth_response
    user_identifier = None
    if chatbot_name in {FREE_CHATBOT_NAME, RAK_CHATBOT_NAME}:
        user_identifier = await get_user_scoped_chatbot_user(chatbot_name)
        if user_identifier is None:
            return jsonify({"message": f"{chatbot_name} requires login"}), 401
    deleted, failed = await chatbot_upload_manager.remove_all_files(user_identifier=user_identifier)

    if deleted and failed:
        message = f"Deleted {len(deleted)} file(s); {len(failed)} file(s) failed."
        return jsonify({"message": message, "deletedFiles": deleted, "failedFiles": failed}), 207
    if failed:
        return (
            jsonify({"message": "Unable to delete uploaded files.", "deletedFiles": [], "failedFiles": failed}),
            500,
        )
    if not deleted:
        return jsonify({"message": "No uploaded files to delete.", "deletedFiles": [], "failedFiles": []}), 200

    message = (
        f"{len(deleted)} file deleted successfully."
        if len(deleted) == 1
        else f"{len(deleted)} files deleted successfully."
    )
    return jsonify({"message": message, "deletedFiles": deleted, "failedFiles": []}), 200


@bp.get("/managed_uploads")
@internal_admin_required
async def list_managed_uploads():
    category = (request.args.get("category") or "").strip() or None
    query = (request.args.get("query") or "").strip() or None
    include_categories = (request.args.get("includeCategories") or "true").strip().lower() != "false"
    manager = get_category_upload_manager()
    try:
        normalized_category = manager.normalize_category(category) if category is not None else None
        page = parse_positive_int_query_param("page", default=1)
        page_size = parse_positive_int_query_param("pageSize", default=15, max_value=100)
        page_result = await manager.list_entries_page(
            category=normalized_category,
            query=query,
            page=page,
            page_size=page_size,
        )
        category_counts = await manager.list_category_counts() if include_categories else {}
    except ValueError as error:
        return jsonify({"message": str(error)}), 400
    return (
        jsonify(
            {
                "files": [dataclasses.asdict(entry) for entry in page_result.entries],
                "categories": sorted(category_counts),
                "categoryCounts": category_counts,
                # Upload targets are the built-in bots only; provisioned/dynamic bots get their
                # knowledge-base files from a separate backend, not this admin uploader.
                "knownCategories": sorted(KNOWN_CHATBOT_NAMES) if include_categories else [],
                "totalCount": page_result.total_count,
                "totalAllCount": sum(category_counts.values()) if include_categories else None,
                "page": page_result.page,
                "pageSize": page_result.page_size,
                "totalPages": max(1, (page_result.total_count + page_result.page_size - 1) // page_result.page_size),
            }
        ),
        200,
    )


@bp.post("/managed_uploads")
@internal_admin_required
async def upload_managed_files():
    form = await request.form
    category = (form.get("category") or "").strip()
    if not category:
        return jsonify({"message": "Category is required.", "uploadedFiles": [], "failedFiles": []}), 400

    manager = get_category_upload_manager()
    try:
        category = manager.normalize_category(category)
    except ValueError as error:
        return jsonify({"message": str(error), "uploadedFiles": [], "failedFiles": []}), 400

    request_files = await request.files
    uploaded_files = request_files.getlist("files") or request_files.getlist("file")
    uploaded_files = [file for file in uploaded_files if file and file.filename]
    if not uploaded_files:
        return jsonify({"message": "No file part in the request", "uploadedFiles": [], "failedFiles": []}), 400

    succeeded: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    upload_id = (request.headers.get("X-Upload-Id") or "").strip() or None

    try:
        for file_index, uploaded_file in enumerate(uploaded_files):
            if upload_id and await manager.is_cancel_requested(category, upload_id):
                failed.append({"category": category, "filename": uploaded_file.filename, "message": "Upload canceled"})
                for skipped_file in uploaded_files[file_index + 1 :]:
                    failed.append(
                        {"category": category, "filename": skipped_file.filename, "message": "Upload canceled"}
                    )
                break
            try:
                upload_result = await manager.add_file(
                    File(content=uploaded_file),
                    category=category,
                    upload_id=upload_id,
                )
                succeeded.append(
                    {
                        **dataclasses.asdict(upload_result.entry),
                        "replacedExisting": upload_result.replaced_existing,
                    }
                )
            except ChatbotUploadCancelled:
                failed.append({"category": category, "filename": uploaded_file.filename, "message": "Upload canceled"})
                for skipped_file in uploaded_files[file_index + 1 :]:
                    failed.append(
                        {"category": category, "filename": skipped_file.filename, "message": "Upload canceled"}
                    )
                break
            except ValueError as error:
                failed.append({"category": category, "filename": uploaded_file.filename, "message": str(error)})
            except Exception as error:
                current_app.logger.error(
                    "Error uploading managed file '%s' into '%s': %s", uploaded_file.filename, category, error
                )
                failed.append(
                    {"category": category, "filename": uploaded_file.filename, "message": "Unexpected upload failure"}
                )
    finally:
        if upload_id:
            await manager.clear_cancel_request(category, upload_id)

    if succeeded and failed:
        message = f"Uploaded {len(succeeded)} file(s); {len(failed)} file(s) failed."
        return jsonify({"message": message, "uploadedFiles": succeeded, "failedFiles": failed}), 207
    if failed:
        status_code = 409 if all(file["message"] == "Upload canceled" for file in failed) else 400
        return jsonify({"message": failed[0]["message"], "uploadedFiles": [], "failedFiles": failed}), status_code

    message = (
        f"{len(succeeded)} file uploaded successfully."
        if len(succeeded) == 1
        else f"{len(succeeded)} files uploaded successfully."
    )
    return jsonify({"message": message, "uploadedFiles": succeeded, "failedFiles": []}), 200


@bp.post("/managed_uploads/cancel/<upload_id>")
@internal_admin_required
async def cancel_managed_upload(upload_id: str):
    upload_id = upload_id.strip()
    category = (request.args.get("category") or "").strip()
    if not upload_id:
        return jsonify({"message": "Upload id is required"}), 400
    if not category:
        return jsonify({"message": "Category is required."}), 400

    manager = get_category_upload_manager()
    try:
        normalized_category = manager.normalize_category(category)
        await manager.request_cancel(normalized_category, upload_id)
    except ValueError as error:
        return jsonify({"message": str(error)}), 400
    return jsonify({"message": "Upload cancellation requested"}), 202


@bp.delete("/managed_uploads/<path:filename>")
@internal_admin_required
async def delete_managed_uploaded_file(filename: str):
    category = (request.args.get("category") or "").strip()
    if not category:
        return jsonify({"message": "Category is required."}), 400

    manager = get_category_upload_manager()
    try:
        normalized_filename = os.path.basename(filename)
        normalized_category = manager.normalize_category(category)
        await manager.remove_file(normalized_filename, normalized_category)
    except ValueError as error:
        return jsonify({"message": str(error)}), 400
    return jsonify({"message": f"File {normalized_filename} deleted successfully"}), 200


@bp.delete("/managed_uploads")
@internal_admin_required
async def delete_managed_uploaded_files():
    category = (request.args.get("category") or "").strip() or None
    manager = get_category_upload_manager()
    try:
        normalized_category = manager.normalize_category(category) if category is not None else None
        deleted, failed = await manager.remove_all_files(category=normalized_category)
    except ValueError as error:
        return jsonify({"message": str(error), "deletedFiles": [], "failedFiles": []}), 400

    deleted_payload = [dataclasses.asdict(entry) for entry in deleted]
    if deleted_payload and failed:
        message = f"Deleted {len(deleted_payload)} file(s); {len(failed)} file(s) failed."
        return jsonify({"message": message, "deletedFiles": deleted_payload, "failedFiles": failed}), 207
    if failed:
        return jsonify({"message": "Unable to delete uploaded files.", "deletedFiles": [], "failedFiles": failed}), 500
    if not deleted_payload:
        return jsonify({"message": "No uploaded files to delete.", "deletedFiles": [], "failedFiles": []}), 200

    message = (
        f"{len(deleted_payload)} file deleted successfully."
        if len(deleted_payload) == 1
        else f"{len(deleted_payload)} files deleted successfully."
    )
    return jsonify({"message": message, "deletedFiles": deleted_payload, "failedFiles": []}), 200


# HYROX assessment visit tracking: one public ping the bot fires on load, plus the admin listing and
# CSV export built from it (see approaches/chatbots/hyrox_assessment/visits.py).
# How many rows the admin page previews; the CSV download is never truncated.
HYROX_VISIT_PREVIEW_LIMIT = 200


@bp.post("/hyrox-assessment/visit")
async def record_hyrox_assessment_visit():
    """Record one visit to the HYROX assessment bot (user id + timestamp) for the admin export.

    Ungated on purpose: the bot itself has no login — the Lemon LMS launches it with the learner's
    account_id on the query string — so requiring a session here would record nothing. `record_visit`
    owns the two policies (a Lemon launch only, production only; see visits.py) and is best-effort,
    and this always answers 204, so neither a dropped visit nor a storage outage can surface in the
    learner's page.
    """
    request_json = await request.get_json(silent=True)
    account_id = None
    if isinstance(request_json, dict):
        raw_account_id = request_json.get("account_id")
        if isinstance(raw_account_id, (str, int)):
            account_id = str(raw_account_id)

    blob_manager: BlobManager = current_app.config[CONFIG_GLOBAL_BLOB_MANAGER]
    await record_visit(blob_manager, account_id, host=request.host)
    return "", 204


@bp.get("/internal-admin/hyrox-visits")
@internal_admin_required
async def list_hyrox_assessment_visits():
    """Month summaries for the picker plus a capped preview of the selected month's rows."""
    month = (request.args.get("month") or "").strip()
    if month and month != ALL_MONTHS and not is_valid_month(month):
        return jsonify({"message": "Month must be in YYYY-MM format."}), 400

    blob_manager: BlobManager = current_app.config[CONFIG_GLOBAL_BLOB_MANAGER]
    all_rows = await collect_rows(blob_manager)
    selected_rows = filter_rows_by_month(all_rows, month)
    # Newest first for reading; the CSV keeps chronological order.
    preview_rows = list(reversed(selected_rows))[:HYROX_VISIT_PREVIEW_LIMIT]
    return (
        jsonify(
            {
                "months": month_summaries(all_rows),
                "selectedMonth": month or ALL_MONTHS,
                "rowCount": len(selected_rows),
                "totalCount": len(all_rows),
                "rows": [{"userId": row.user_id, "timestamp": row.timestamp.isoformat()} for row in preview_rows],
                "previewLimit": HYROX_VISIT_PREVIEW_LIMIT,
                "previewTruncated": len(selected_rows) > len(preview_rows),
            }
        ),
        200,
    )


@bp.get("/internal-admin/hyrox-visits.csv")
@internal_admin_required
async def download_hyrox_assessment_visits_csv():
    """The export: one CSV of user id + timestamp for a month (or every month)."""
    month = (request.args.get("month") or "").strip()
    if month and month != ALL_MONTHS and not is_valid_month(month):
        return jsonify({"message": "Month must be in YYYY-MM format."}), 400

    blob_manager: BlobManager = current_app.config[CONFIG_GLOBAL_BLOB_MANAGER]
    rows = filter_rows_by_month(await collect_rows(blob_manager), month)
    csv_file = io.BytesIO(render_visits_csv(rows).encode("utf-8"))
    return await send_file(
        csv_file,
        mimetype="text/csv",
        as_attachment=True,
        attachment_filename=csv_filename(month),
    )


# ---------------------------------------------------------------------------------------------
# LLM telemetry dashboard (/admin/telemetry). Every route is admin-gated by the same
# `internal_tools_admin_session` cookie the rest of the admin shell uses, and every read degrades to
# an empty payload rather than a 500 -- a dashboard that shows fewer rows beats one that shows an
# error. See core/telemetry/ for the recording side.

TELEMETRY_DEFAULT_RANGE = "7d"
TELEMETRY_MAX_REQUEST_PAGE = 200
# Stands in for `range=all` until the store can say when recording actually began. It is never
# queried: `telemetry_resolve_range_async` replaces it before the range reaches the store.
TELEMETRY_ALL_TIME_PLACEHOLDER = "2020-01-01"
TELEMETRY_RANGE_DAYS = {"24h": 1, "7d": 7, "30d": 30, "90d": 90}


def telemetry_resolve_range(args) -> tuple[str, str, str | None]:
    """(from_day, to_day, error). `from`/`to` win over `range`; both are inclusive UTC days."""
    today = datetime.now(timezone.utc).date()
    explicit_from = (args.get("from") or "").strip()
    explicit_to = (args.get("to") or "").strip()

    if explicit_from or explicit_to:
        if not telemetry_records.is_valid_day(explicit_from) or not telemetry_records.is_valid_day(explicit_to):
            return "", "", "from and to must both be dates in YYYY-MM-DD format."
        if explicit_to < explicit_from:
            return "", "", "The end of the range must not be before its start."
        return explicit_from, explicit_to, None

    requested = (args.get("range") or TELEMETRY_DEFAULT_RANGE).strip()
    if requested == "all":
        # A placeholder only. `all` means "from the first day recording produced anything", which
        # only the store knows -- `telemetry_resolve_range_async` is what resolves it, and every
        # route must go through that. See the note there for what a compiled date did instead.
        return TELEMETRY_ALL_TIME_PLACEHOLDER, today.isoformat(), None
    if requested == "month":
        return today.replace(day=1).isoformat(), today.isoformat(), None
    days = TELEMETRY_RANGE_DAYS.get(requested)
    if days is None:
        return "", "", "range must be one of 24h, 7d, 30d, 90d, month, all."
    return (today - timedelta(days=days - 1)).isoformat(), today.isoformat(), None


def telemetry_parse_facets(args) -> dict[str, set[str]]:
    """CSV per facet. Composition is OR within a facet and AND across facets -- the rule the UI
    states on the filter bar."""
    facets: dict[str, set[str]] = {}
    for param, field in (("chatbot", "chatbot"), ("model", "model"), ("path", "path"), ("status", "status")):
        raw = (args.get(param) or "").strip()
        if not raw or raw == "all":
            continue
        values = {value.strip() for value in raw.split(",") if value.strip()}
        if values:
            facets[field] = values
    return facets


async def telemetry_earliest_day(store) -> str | None:
    if store is None:
        return None
    return await store.earliest_day()


def telemetry_range_is_all_time(args) -> bool:
    """`all` only applies when no explicit `from`/`to` was given -- those always win."""
    if (args.get("from") or "").strip() or (args.get("to") or "").strip():
        return False
    return (args.get("range") or TELEMETRY_DEFAULT_RANGE).strip() == "all"


async def telemetry_effective_range(args, store, from_day: str, to_day: str) -> tuple[str, str]:
    """The range actually queried: `all` resolved against the data, then the store's own clamp.

    Called after `telemetry_resolve_range` has validated the arguments, so a bad range still 400s
    before an unconfigured store 503s.

    `all` used to resolve to a compiled `2020-01-01`. `day_range` then clamped that to the FIRST
    MAX_RANGE_DAYS days -- a 400-day window ending in February 2021 -- so every tab drew an empty
    dashboard, and each click folded a rollup for all 400 data-less days (400 such blobs were found
    in the live container). Anchoring to the first recorded day makes the range mean what the button
    says and touch only days that can hold data.

    Applying the clamp here too means a route reports the window it queried rather than the one it
    was asked for, which matters because the UI prints that range and sizes its axis from it.
    """
    if telemetry_range_is_all_time(args):
        # No data yet is a real state, not an error: fall back to a single day so an empty dashboard
        # renders against today rather than against a placeholder decades in the past.
        from_day = await telemetry_earliest_day(store) or to_day
    return clamp_day_range(from_day, to_day) or (from_day, to_day)


def telemetry_previous_window(from_day: str, to_day: str) -> tuple[str, str]:
    """The equal-length window immediately before this one, for the KPI deltas."""
    start = date.fromisoformat(from_day)
    end = date.fromisoformat(to_day)
    span = (end - start).days + 1
    return (start - timedelta(days=span)).isoformat(), (start - timedelta(days=1)).isoformat()


@bp.get("/internal-admin/telemetry/summary")
@internal_admin_required
async def get_telemetry_summary():
    """Everything the Overview and Costs tabs draw, in one call."""
    from_day, to_day, error = telemetry_resolve_range(request.args)
    if error:
        return jsonify({"message": error}), 400
    granularity_arg = (request.args.get("granularity") or "auto").strip()
    if granularity_arg not in {"auto", "hour", "day", "week", "month"}:
        return jsonify({"message": "granularity must be one of auto, hour, day, week, month."}), 400

    store: TelemetryStore | None = current_app.config.get(CONFIG_TELEMETRY_STORE)
    if store is None:
        return jsonify({"message": "Telemetry is not configured."}), 503
    from_day, to_day = await telemetry_effective_range(request.args, store, from_day, to_day)


    facets = telemetry_parse_facets(request.args)
    span_days = (date.fromisoformat(to_day) - date.fromisoformat(from_day)).days + 1
    granularity = telemetry_aggregate.resolve_granularity(
        None if granularity_arg == "auto" else granularity_arg, span_days
    )

    result = await store.summarize(
        from_day=from_day, to_day=to_day, granularity=granularity, filters=facets
    )
    aggregate = result["aggregate"]

    data_starts_at = await telemetry_earliest_day(store)
    previous_from, previous_to = telemetry_previous_window(from_day, to_day)
    # A comparison window that predates recording is not "zero" -- it is "no comparison", and saying
    # so is the difference between an honest empty state and every KPI reading +100% for a fortnight.
    has_comparison = bool(data_starts_at) and previous_from >= data_starts_at
    previous_kpis = None
    if has_comparison:
        previous = await store.summarize(
            from_day=previous_from, to_day=previous_to, granularity=granularity, filters=facets
        )
        previous_kpis = previous["aggregate"].kpis()

    return jsonify(
        {
            "range": {
                "from": from_day,
                "to": to_day,
                "granularity": granularity_arg,
                "resolvedGranularity": granularity,
            },
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "dataStartsAt": data_starts_at,
            "currency": telemetry_currency(store),
            "kpis": aggregate.kpis(),
            "previousTotals": previous_kpis,
            "noComparisonPeriod": not has_comparison,
            "series": aggregate.series_rows(),
            "seriesByChatbot": aggregate.split_series_rows(aggregate.series_by_chatbot, "chatbot"),
            "seriesByModel": aggregate.split_series_rows(aggregate.series_by_model, "model"),
            "byChatbot": aggregate.facet_rows(aggregate.by_chatbot, "chatbot"),
            "byModel": aggregate.facet_rows(aggregate.by_model, "model"),
            "byPath": aggregate.facet_rows(aggregate.by_path, "path"),
            "byStep": aggregate.step_rows(),
            "latencyHistogram": telemetry_aggregate.histogram_display_buckets(aggregate.latency),
            "errors": sorted(aggregate.errors.values(), key=lambda entry: -entry["count"]),
            "unpricedModels": [
                {"model": model, "requests": count}
                for model, count in sorted(aggregate.unpriced_models.items(), key=lambda item: -item[1])
            ],
            "approximate": True,
            "maxRelativeError": telemetry_aggregate.MAX_RELATIVE_ERROR,
            "minSamplesForPercentile": telemetry_aggregate.MIN_SAMPLES_FOR_PERCENTILE,
            "partial": result["partial"],
        }
    )


def telemetry_currency(store) -> str:
    price_table = getattr(store, "price_table", None)
    if price_table is None:
        return "EUR"
    return getattr(price_table, "currency", None) or "EUR"


@bp.get("/internal-admin/telemetry/requests")
@internal_admin_required
async def list_telemetry_requests():
    from_day, to_day, error = telemetry_resolve_range(request.args)
    if error:
        return jsonify({"message": error}), 400

    store: TelemetryStore | None = current_app.config.get(CONFIG_TELEMETRY_STORE)
    if store is None:
        return jsonify({"message": "Telemetry is not configured."}), 503
    from_day, to_day = await telemetry_effective_range(request.args, store, from_day, to_day)


    try:
        limit = int((request.args.get("limit") or "50").strip())
    except ValueError:
        return jsonify({"message": "limit must be a number."}), 400
    limit = max(1, min(TELEMETRY_MAX_REQUEST_PAGE, limit))

    result = await store.list_requests(
        from_day=from_day,
        to_day=to_day,
        filters=telemetry_parse_facets(request.args),
        query=(request.args.get("q") or "").strip(),
        limit=limit,
        cursor=(request.args.get("cursor") or "").strip() or None,
    )
    return jsonify(
        {
            "rows": result["rows"],
            "cursor": result["cursor"],
            "hasMore": result["hasMore"],
            "scannedDays": result["scannedDays"],
            "currency": telemetry_currency(store),
        }
    )


async def load_telemetry_record(trace_id: str):
    """One full turn record, or None. `blob` comes from a listing row, but it is re-parsed through the
    same codec that produced it before any read, and the trace id in the path must match what the name
    encodes -- so a caller-supplied value cannot address a blob outside the requests prefix."""
    if not telemetry_records.is_valid_trace_id(trace_id):
        return None, "traceId must be 16 hex characters."
    store: TelemetryStore | None = current_app.config.get(CONFIG_TELEMETRY_STORE)
    if store is None:
        return None, "Telemetry is not configured."

    blob_name = (request.args.get("blob") or "").strip()
    key = telemetry_records.parse_request_blob_name(blob_name)
    if key is None:
        return None, "A valid blob reference from the request list is required."
    if key.trace_id != trace_id:
        return None, "The blob reference does not match the requested trace id."
    return await store.read_request(key.blob_name), None


@bp.get("/internal-admin/telemetry/requests/<trace_id>")
@internal_admin_required
async def get_telemetry_request(trace_id: str):
    record, error = await load_telemetry_record(trace_id)
    if error:
        return jsonify({"message": error}), 400
    if record is None:
        return jsonify({"message": "That request is no longer stored.", "traceId": trace_id}), 404
    return jsonify(record)


@bp.get("/internal-admin/telemetry/requests/<trace_id>.json")
@internal_admin_required
async def download_telemetry_request(trace_id: str):
    """The same body as a file, for attaching one failing turn to a bug report."""
    record, error = await load_telemetry_record(trace_id)
    if error:
        return jsonify({"message": error}), 400
    if record is None:
        return jsonify({"message": "That request is no longer stored.", "traceId": trace_id}), 404
    payload = io.BytesIO(json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8"))
    return await send_file(
        payload,
        mimetype="application/json",
        as_attachment=True,
        attachment_filename=f"telemetry-{trace_id}.json",
    )


@bp.get("/internal-admin/telemetry/filters")
@internal_admin_required
async def get_telemetry_filters():
    """The chatbot and model pickers. Built-ins come from the compiled name set and provisioned bots
    from the registry, the same two sources the chatbot directory merges."""
    store: TelemetryStore | None = current_app.config.get(CONFIG_TELEMETRY_STORE)
    chatbots = [{"name": name, "kind": "builtin"} for name in sorted(KNOWN_CHATBOT_NAMES)]

    registry_store: ChatbotRegistryStore | None = current_app.config.get(CONFIG_CHATBOT_REGISTRY_STORE)
    if registry_store is not None:
        try:
            # list_records returns a MAPPING of bot name -> record; iterating it directly yields the
            # string keys, not the records.
            for record in (await registry_store.list_records()).values():
                chatbots.append(
                    {
                        "name": record.bot_name,
                        "displayName": record.display_name or record.bot_name,
                        "kind": "dynamic",
                    }
                )
        except Exception:
            telemetry_logger.exception("Could not list provisioned bots for the telemetry filters")

    return jsonify(
        {
            "chatbots": chatbots,
            "models": sorted(current_app.config.get(CONFIG_AVAILABLE_CHAT_MODELS, []) or []),
            "paths": list(telemetry_records.ALL_PATHS),
            "statuses": list(telemetry_records.ALL_STATUSES),
            "dataStartsAt": await telemetry_earliest_day(store),
            "currency": telemetry_currency(store),
            "timezone": "UTC",
            "storesBodies": telemetry.should_store_bodies(),
        }
    )


@bp.get("/internal-admin/telemetry/pricing")
@internal_admin_required
async def get_telemetry_pricing():
    store: TelemetryStore | None = current_app.config.get(CONFIG_TELEMETRY_STORE)
    if store is None:
        return jsonify({"message": "Telemetry is not configured."}), 503
    await store.refresh_price_table()
    return jsonify(store.price_table.as_payload())


@bp.put("/internal-admin/telemetry/pricing")
@internal_admin_required
async def save_telemetry_pricing():
    """The only write route on the dashboard. Editing a price never rewrites history -- stored rows
    keep the cost that was computed at the time, stamped with the price version."""
    if not request.is_json:
        return jsonify({"message": "request must be json"}), 415
    body = await request.get_json()
    prices = body.get("prices") if isinstance(body, dict) else None
    if not isinstance(prices, dict) or not prices:
        return jsonify({"message": "A prices object is required."}), 400
    parsed = parse_price_mapping(prices, source="blob")
    if not parsed:
        return jsonify({"message": "No valid prices were supplied. Each model needs input and output."}), 400

    store: TelemetryStore | None = current_app.config.get(CONFIG_TELEMETRY_STORE)
    if store is None:
        return jsonify({"message": "Telemetry is not configured."}), 503
    await store.save_price_overrides(
        {model: price.as_dict() for model, price in parsed.items()},
        note=str(body.get("note") or "")[:500],
    )
    return jsonify(store.price_table.as_payload())


TELEMETRY_CSV_VIEWS = {"chatbot", "model", "path", "step", "requests"}


@bp.get("/internal-admin/telemetry/export.csv")
@internal_admin_required
async def download_telemetry_csv():
    """Aggregates and request rows, never message text. The single-request JSON download is the
    deliberate one-at-a-time exception for reading a conversation."""
    from_day, to_day, error = telemetry_resolve_range(request.args)
    if error:
        return jsonify({"message": error}), 400
    view = (request.args.get("view") or "chatbot").strip()
    if view not in TELEMETRY_CSV_VIEWS:
        return jsonify({"message": f"view must be one of {', '.join(sorted(TELEMETRY_CSV_VIEWS))}."}), 400

    store: TelemetryStore | None = current_app.config.get(CONFIG_TELEMETRY_STORE)
    if store is None:
        return jsonify({"message": "Telemetry is not configured."}), 503
    from_day, to_day = await telemetry_effective_range(request.args, store, from_day, to_day)


    facets = telemetry_parse_facets(request.args)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    currency = telemetry_currency(store)

    if view == "requests":
        result = await store.list_requests(
            from_day=from_day, to_day=to_day, filters=facets, limit=TELEMETRY_MAX_REQUEST_PAGE
        )
        writer.writerow(
            [
                "timestamp_utc",
                "trace_id",
                "chatbot",
                "path",
                "model",
                "status",
                "duration_ms",
                "tokens_in",
                "tokens_out",
                "tokens_cached",
                f"estimated_cost_{currency.lower()}",
            ]
        )
        for row in result["rows"]:
            writer.writerow(
                [
                    row["startedAt"],
                    row["traceId"],
                    row["chatbot"],
                    row["path"],
                    row["model"] or "",
                    row["status"],
                    row["durationMs"],
                    row["tokensIn"],
                    row["tokensOut"],
                    row["tokensCached"],
                    format_micros_for_csv(row["estCostMicros"]),
                ]
            )
    else:
        span_days = (date.fromisoformat(to_day) - date.fromisoformat(from_day)).days + 1
        granularity = telemetry_aggregate.resolve_granularity(None, span_days)
        result = await store.summarize(
            from_day=from_day, to_day=to_day, granularity=granularity, filters=facets
        )
        aggregate = result["aggregate"]
        if view == "step":
            writer.writerow(
                ["path", "step", "type", "calls", "avg_ms", "p95_ms", "total_ms", "tokens_in", "tokens_out"]
            )
            for row in aggregate.step_rows():
                writer.writerow(
                    [
                        row["path"],
                        row["step"],
                        row["type"],
                        row["calls"],
                        row["avgMs"],
                        "" if row["p95Ms"] is None else round(row["p95Ms"]),
                        row["totalMs"],
                        row["tokensIn"],
                        row["tokensOut"],
                    ]
                )
        else:
            facet_map = {
                "chatbot": (aggregate.by_chatbot, "chatbot"),
                "model": (aggregate.by_model, "model"),
                "path": (aggregate.by_path, "path"),
            }[view]
            writer.writerow(
                [
                    view,
                    "requests",
                    "tokens_in",
                    "tokens_out",
                    "tokens_cached",
                    f"estimated_cost_{currency.lower()}",
                    "avg_ms",
                    "p95_ms",
                ]
            )
            for row in aggregate.facet_rows(*facet_map):
                writer.writerow(
                    [
                        row[facet_map[1]],
                        row["requests"],
                        row["tokensIn"],
                        row["tokensOut"],
                        row["tokensCached"],
                        format_micros_for_csv(row["estCostMicros"]),
                        row["avgMs"],
                        "" if row["p95Ms"] is None else round(row["p95Ms"]),
                    ]
                )

    payload = io.BytesIO(buffer.getvalue().encode("utf-8"))
    return await send_file(
        payload,
        mimetype="text/csv",
        as_attachment=True,
        attachment_filename=f"telemetry-{view}-{from_day}-to-{to_day}.csv",
    )


def format_micros_for_csv(micros) -> str:
    """Six decimals, so a sub-cent per-step cost is not rounded away to 0.00 in a spreadsheet."""
    value = micros_to_units(micros)
    return "" if value is None else f"{value:.6f}"


@bp.before_app_serving
async def setup_clients():
    # Replace these with your own values, either in environment variables or directly here
    AZURE_STORAGE_ACCOUNT = os.environ["AZURE_STORAGE_ACCOUNT"]
    AZURE_STORAGE_CONTAINER = os.environ["AZURE_STORAGE_CONTAINER"]
    AZURE_IMAGESTORAGE_CONTAINER = os.environ.get("AZURE_IMAGESTORAGE_CONTAINER")
    AZURE_USERSTORAGE_ACCOUNT = os.environ.get("AZURE_USERSTORAGE_ACCOUNT")
    AZURE_USERSTORAGE_CONTAINER = os.environ.get("AZURE_USERSTORAGE_CONTAINER")
    AZURE_SEARCH_SERVICE = os.environ["AZURE_SEARCH_SERVICE"]
    AZURE_SEARCH_ENDPOINT = f"https://{AZURE_SEARCH_SERVICE}.search.windows.net"
    AZURE_SEARCH_INDEX = os.environ["AZURE_SEARCH_INDEX"]
    AZURE_SEARCH_KNOWLEDGEBASE_NAME = os.getenv("AZURE_SEARCH_KNOWLEDGEBASE_NAME", "")
    # Shared by all OpenAI deployments
    OPENAI_HOST = OpenAIHost(os.getenv("OPENAI_HOST", "azure"))
    OPENAI_CHATGPT_MODEL = os.environ["AZURE_OPENAI_CHATGPT_MODEL"]
    AZURE_OPENAI_KNOWLEDGEBASE_MODEL = os.getenv("AZURE_OPENAI_KNOWLEDGEBASE_MODEL")
    AZURE_OPENAI_KNOWLEDGEBASE_DEPLOYMENT = os.getenv("AZURE_OPENAI_KNOWLEDGEBASE_DEPLOYMENT")
    OPENAI_EMB_MODEL = os.getenv("AZURE_OPENAI_EMB_MODEL_NAME", "text-embedding-ada-002")
    OPENAI_EMB_DIMENSIONS = int(os.getenv("AZURE_OPENAI_EMB_DIMENSIONS") or 1536)
    OPENAI_REASONING_EFFORT = os.getenv("AZURE_OPENAI_REASONING_EFFORT")
    # Used with Azure OpenAI deployments
    AZURE_OPENAI_SERVICE = os.getenv("AZURE_OPENAI_SERVICE")
    AZURE_OPENAI_CHATGPT_DEPLOYMENT = (
        os.getenv("AZURE_OPENAI_CHATGPT_DEPLOYMENT")
        if OPENAI_HOST in [OpenAIHost.AZURE, OpenAIHost.AZURE_CUSTOM]
        else None
    )
    AZURE_OPENAI_EMB_DEPLOYMENT = (
        os.getenv("AZURE_OPENAI_EMB_DEPLOYMENT") if OPENAI_HOST in [OpenAIHost.AZURE, OpenAIHost.AZURE_CUSTOM] else None
    )
    AZURE_OPENAI_CUSTOM_URL = os.getenv("AZURE_OPENAI_CUSTOM_URL")
    AZURE_VISION_ENDPOINT = os.getenv("AZURE_VISION_ENDPOINT", "")
    AZURE_OPENAI_API_KEY_OVERRIDE = os.getenv("AZURE_OPENAI_API_KEY_OVERRIDE")
    # Used only with non-Azure OpenAI deployments
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_ORGANIZATION = os.getenv("OPENAI_ORGANIZATION")

    AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID")
    AZURE_USE_AUTHENTICATION = os.getenv("AZURE_USE_AUTHENTICATION", "").lower() == "true"
    AZURE_ENFORCE_ACCESS_CONTROL = os.getenv("AZURE_ENFORCE_ACCESS_CONTROL", "").lower() == "true"
    AZURE_ENABLE_UNAUTHENTICATED_ACCESS = os.getenv("AZURE_ENABLE_UNAUTHENTICATED_ACCESS", "").lower() == "true"
    AZURE_SERVER_APP_ID = os.getenv("AZURE_SERVER_APP_ID")
    AZURE_SERVER_APP_SECRET = os.getenv("AZURE_SERVER_APP_SECRET")
    INTERNAL_TOOLS_PASSWORD = os.getenv("INTERNAL_TOOLS_PASSWORD") or os.getenv("CHATBOT_DIRECTORY_PASSWORD")
    AZURE_CLIENT_APP_ID = os.getenv("AZURE_CLIENT_APP_ID")
    AZURE_AUTH_TENANT_ID = os.getenv("AZURE_AUTH_TENANT_ID", AZURE_TENANT_ID)
    PUBLIC_TEST_SMTP_HOST = os.getenv("PUBLIC_TEST_SMTP_HOST")
    PUBLIC_TEST_SMTP_PORT = int(os.getenv("PUBLIC_TEST_SMTP_PORT", "587"))
    PUBLIC_TEST_SMTP_USERNAME = os.getenv("PUBLIC_TEST_SMTP_USERNAME")
    PUBLIC_TEST_SMTP_PASSWORD = os.getenv("PUBLIC_TEST_SMTP_PASSWORD")
    PUBLIC_TEST_EMAIL_FROM = os.getenv("PUBLIC_TEST_EMAIL_FROM")
    PUBLIC_TEST_EMAIL_FROM_NAME = os.getenv("PUBLIC_TEST_EMAIL_FROM_NAME", "nerilio")
    # Optional: a verified Free Bot signup is mirrored into HubSpot as a CRM contact. Unset means
    # the sync is simply skipped, which is the normal state for local runs.
    HUBSPOT_API_KEY = os.getenv("HUBSPOT_API_KEY")

    KB_FIELDS_CONTENT = os.getenv("KB_FIELDS_CONTENT", "content")
    KB_FIELDS_SOURCEPAGE = os.getenv("KB_FIELDS_SOURCEPAGE", "sourcepage")

    AZURE_SEARCH_QUERY_LANGUAGE = os.getenv("AZURE_SEARCH_QUERY_LANGUAGE") or "en-us"
    AZURE_SEARCH_QUERY_SPELLER = os.getenv("AZURE_SEARCH_QUERY_SPELLER") or "lexicon"
    AZURE_SEARCH_SEMANTIC_RANKER = os.getenv("AZURE_SEARCH_SEMANTIC_RANKER", "free").lower()
    AZURE_SEARCH_QUERY_REWRITING = os.getenv("AZURE_SEARCH_QUERY_REWRITING", "false").lower()
    # This defaults to the previous field name "embedding", for backwards compatibility
    AZURE_SEARCH_FIELD_NAME_EMBEDDING = os.getenv("AZURE_SEARCH_FIELD_NAME_EMBEDDING", "embedding")

    AZURE_SPEECH_SERVICE_ID = os.getenv("AZURE_SPEECH_SERVICE_ID")
    AZURE_SPEECH_SERVICE_LOCATION = os.getenv("AZURE_SPEECH_SERVICE_LOCATION")
    AZURE_SPEECH_SERVICE_VOICE = os.getenv("AZURE_SPEECH_SERVICE_VOICE") or "en-US-AndrewMultilingualNeural"

    # Real-time text-to-speech avatar. Its voice/character/style are separate from the settings
    # above because the avatar is an opt-in per-bot feature, while AZURE_SPEECH_SERVICE_VOICE is
    # shared by the speak-answer button on every speech-enabled bot.
    AZURE_SPEECH_AVATAR_VOICE = os.getenv("AZURE_SPEECH_AVATAR_VOICE") or "de-AT-JonasNeural"
    AZURE_SPEECH_AVATAR_CHARACTER = os.getenv("AZURE_SPEECH_AVATAR_CHARACTER") or "harry"
    AZURE_SPEECH_AVATAR_STYLE = os.getenv("AZURE_SPEECH_AVATAR_STYLE") or "casual"

    USE_MULTIMODAL = os.getenv("USE_MULTIMODAL", "").lower() == "true"
    RAG_SEARCH_TEXT_EMBEDDINGS = os.getenv("RAG_SEARCH_TEXT_EMBEDDINGS", "true").lower() == "true"
    RAG_SEARCH_IMAGE_EMBEDDINGS = os.getenv("RAG_SEARCH_IMAGE_EMBEDDINGS", "true").lower() == "true"
    RAG_SEND_TEXT_SOURCES = os.getenv("RAG_SEND_TEXT_SOURCES", "true").lower() == "true"
    RAG_SEND_IMAGE_SOURCES = os.getenv("RAG_SEND_IMAGE_SOURCES", "true").lower() == "true"
    USE_USER_UPLOAD = os.getenv("USE_USER_UPLOAD", "").lower() == "true"
    ENABLE_LANGUAGE_PICKER = os.getenv("ENABLE_LANGUAGE_PICKER", "").lower() == "true"
    USE_SPEECH_INPUT_BROWSER = os.getenv("USE_SPEECH_INPUT_BROWSER", "").lower() == "true"
    USE_SPEECH_OUTPUT_BROWSER = os.getenv("USE_SPEECH_OUTPUT_BROWSER", "").lower() == "true"
    USE_SPEECH_OUTPUT_AZURE = os.getenv("USE_SPEECH_OUTPUT_AZURE", "").lower() == "true"
    USE_SPEECH_AVATAR = os.getenv("USE_SPEECH_AVATAR", "").lower() == "true"
    USE_CHAT_HISTORY_BROWSER = os.getenv("USE_CHAT_HISTORY_BROWSER", "").lower() == "true"
    USE_CHAT_HISTORY_COSMOS = os.getenv("USE_CHAT_HISTORY_COSMOS", "").lower() == "true"
    USE_AGENTIC_KNOWLEDGEBASE = os.getenv("USE_AGENTIC_KNOWLEDGEBASE", "").lower() == "true"
    # LLM-Wiki retrieval mode. Defaults on for the Internal-bot pilot; the option only surfaces
    # in the Internal bot's UI and only retrieves when a wiki exists for the selected source bot.
    USE_LLM_WIKI = os.getenv("USE_LLM_WIKI", "true").lower() == "true"
    USE_WEB_SOURCE = os.getenv("USE_WEB_SOURCE", "").lower() == "true"
    USE_SHAREPOINT_SOURCE = os.getenv("USE_SHAREPOINT_SOURCE", "").lower() == "true"
    AGENTIC_KNOWLEDGEBASE_REASONING_EFFORT = os.getenv("AGENTIC_KNOWLEDGEBASE_REASONING_EFFORT", "low")
    USE_VECTORS = os.getenv("USE_VECTORS", "").lower() != "false"

    # WEBSITE_HOSTNAME is always set by App Service, RUNNING_IN_PRODUCTION is set in main.bicep
    RUNNING_ON_AZURE = os.getenv("WEBSITE_HOSTNAME") is not None or os.getenv("RUNNING_IN_PRODUCTION") is not None

    # Use the current user identity for keyless authentication to Azure services.
    # This assumes you use 'azd auth login' locally, and managed identity when deployed on Azure.
    # The managed identity is setup in the infra/ folder.
    azure_credential: ChainedTokenCredential | ManagedIdentityCredential
    azure_ai_token_provider: Callable[[], Awaitable[str]]
    if RUNNING_ON_AZURE:
        current_app.logger.info("Setting up Azure credential using ManagedIdentityCredential")
        if AZURE_CLIENT_ID := os.getenv("AZURE_CLIENT_ID"):
            # ManagedIdentityCredential should use AZURE_CLIENT_ID if set in env, but its not working for some reason,
            # so we explicitly pass it in as the client ID here. This is necessary for user-assigned managed identities.
            current_app.logger.info(
                "Setting up Azure credential using ManagedIdentityCredential with client_id %s", AZURE_CLIENT_ID
            )
            azure_credential = ManagedIdentityCredential(client_id=AZURE_CLIENT_ID)
        else:
            current_app.logger.info("Setting up Azure credential using ManagedIdentityCredential")
            azure_credential = ManagedIdentityCredential()
    # Locally, try the Azure CLI first and fall back to the Azure Developer CLI.
    #
    # `azd auth token` shells out on every token request and has been measured at 22-121 seconds on
    # a developer machine — far past any reasonable process timeout, so requests that need a token
    # fail with `CredentialUnavailableError: Timed out waiting for Azure Developer CLI` and the
    # page 500s. `az account get-access-token` returns in 1.5-3.5s for the same scopes. The chain
    # keeps the previous behaviour intact for anyone who only has azd: an unavailable or
    # unauthenticated `az` raises CredentialUnavailableError, which is exactly the signal
    # ChainedTokenCredential uses to move on to the next credential.
    elif AZURE_TENANT_ID:
        current_app.logger.info(
            "Setting up Azure credential using AzureCliCredential then AzureDeveloperCliCredential with tenant_id %s",
            AZURE_TENANT_ID,
        )
        azure_credential = ChainedTokenCredential(
            AzureCliCredential(tenant_id=AZURE_TENANT_ID, process_timeout=60),
            AzureDeveloperCliCredential(tenant_id=AZURE_TENANT_ID, process_timeout=60),
        )
    else:
        current_app.logger.info(
            "Setting up Azure credential using AzureCliCredential then AzureDeveloperCliCredential for home tenant"
        )
        azure_credential = ChainedTokenCredential(
            AzureCliCredential(process_timeout=60),
            AzureDeveloperCliCredential(process_timeout=60),
        )
    azure_ai_token_provider = get_bearer_token_provider(
        azure_credential, "https://cognitiveservices.azure.com/.default"
    )

    # Set the Azure credential in the app config for use in other parts of the app
    current_app.config[CONFIG_CREDENTIAL] = azure_credential
    current_app.config[CONFIG_CHATBOT_UPLOAD_MANAGERS] = {}

    # Set up clients for AI Search and Storage
    search_client = SearchClient(
        endpoint=AZURE_SEARCH_ENDPOINT,
        index_name=AZURE_SEARCH_INDEX,
        credential=azure_credential,
    )

    knowledgebase_client = KnowledgeBaseRetrievalClient(
        endpoint=AZURE_SEARCH_ENDPOINT, knowledge_base_name=AZURE_SEARCH_KNOWLEDGEBASE_NAME, credential=azure_credential
    )
    knowledgebase_client_with_web = None
    knowledgebase_client_with_sharepoint = None
    knowledgebase_client_with_web_and_sharepoint = None

    if AZURE_SEARCH_KNOWLEDGEBASE_NAME:
        if USE_WEB_SOURCE:
            knowledgebase_client_with_web = KnowledgeBaseRetrievalClient(
                endpoint=AZURE_SEARCH_ENDPOINT,
                knowledge_base_name=f"{AZURE_SEARCH_KNOWLEDGEBASE_NAME}-with-web",
                credential=azure_credential,
            )
        if USE_SHAREPOINT_SOURCE:
            knowledgebase_client_with_sharepoint = KnowledgeBaseRetrievalClient(
                endpoint=AZURE_SEARCH_ENDPOINT,
                knowledge_base_name=f"{AZURE_SEARCH_KNOWLEDGEBASE_NAME}-with-sp",
                credential=azure_credential,
            )
        if USE_WEB_SOURCE and USE_SHAREPOINT_SOURCE:
            knowledgebase_client_with_web_and_sharepoint = KnowledgeBaseRetrievalClient(
                endpoint=AZURE_SEARCH_ENDPOINT,
                knowledge_base_name=f"{AZURE_SEARCH_KNOWLEDGEBASE_NAME}-with-web-and-sp",
                credential=azure_credential,
            )

    # Set up the global blob storage manager (used for global content/images, but not user uploads)
    global_blob_manager = BlobManager(
        endpoint=f"https://{AZURE_STORAGE_ACCOUNT}.blob.core.windows.net",
        credential=azure_credential,
        container=AZURE_STORAGE_CONTAINER,
        image_container=AZURE_IMAGESTORAGE_CONTAINER,
    )
    current_app.config[CONFIG_GLOBAL_BLOB_MANAGER] = global_blob_manager

    # Set up authentication helper
    search_index = None
    if AZURE_USE_AUTHENTICATION:
        current_app.logger.info("AZURE_USE_AUTHENTICATION is true, setting up search index client")
        search_index_client = SearchIndexClient(
            endpoint=AZURE_SEARCH_ENDPOINT,
            credential=azure_credential,
        )
        search_index = await search_index_client.get_index(AZURE_SEARCH_INDEX)
        await search_index_client.close()
    auth_helper = AuthenticationHelper(
        search_index=search_index,
        use_authentication=AZURE_USE_AUTHENTICATION,
        server_app_id=AZURE_SERVER_APP_ID,
        server_app_secret=AZURE_SERVER_APP_SECRET,
        client_app_id=AZURE_CLIENT_APP_ID,
        tenant_id=AZURE_AUTH_TENANT_ID,
        enforce_access_control=AZURE_ENFORCE_ACCESS_CONTROL,
        enable_unauthenticated_access=AZURE_ENABLE_UNAUTHENTICATED_ACCESS,
    )

    # The avatar shares this resource: it authenticates with the same token and derives its relay
    # host from AZURE_SPEECH_SERVICE_ID, so it must keep the same startup requirements.
    if USE_SPEECH_OUTPUT_AZURE or USE_SPEECH_INPUT_BROWSER or USE_SPEECH_AVATAR:
        current_app.logger.info("Browser speech is enabled, setting up Azure speech service")
        if not AZURE_SPEECH_SERVICE_ID or AZURE_SPEECH_SERVICE_ID == "":
            raise ValueError("Azure speech resource not configured correctly, missing AZURE_SPEECH_SERVICE_ID")
        if not AZURE_SPEECH_SERVICE_LOCATION or AZURE_SPEECH_SERVICE_LOCATION == "":
            raise ValueError("Azure speech resource not configured correctly, missing AZURE_SPEECH_SERVICE_LOCATION")
        current_app.config[CONFIG_SPEECH_SERVICE_ID] = AZURE_SPEECH_SERVICE_ID
        current_app.config[CONFIG_SPEECH_SERVICE_LOCATION] = AZURE_SPEECH_SERVICE_LOCATION
        current_app.config[CONFIG_SPEECH_SERVICE_VOICE] = AZURE_SPEECH_SERVICE_VOICE
        # Wait until token is needed to fetch for the first time
        current_app.config[CONFIG_SPEECH_SERVICE_TOKEN] = None

    openai_client, azure_openai_endpoint = setup_openai_client(
        openai_host=OPENAI_HOST,
        azure_credential=azure_credential,
        azure_openai_service=AZURE_OPENAI_SERVICE,
        azure_openai_custom_url=AZURE_OPENAI_CUSTOM_URL,
        azure_openai_api_key=AZURE_OPENAI_API_KEY_OVERRIDE,
        openai_api_key=OPENAI_API_KEY,
        openai_organization=OPENAI_ORGANIZATION,
    )

    chatbot_upload_file_processors, _ = setup_file_processors(
        azure_credential=azure_credential,
        document_intelligence_service=None,
        local_pdf_parser=True,
        local_html_parser=True,
        use_content_understanding=False,
        content_understanding_endpoint=None,
        use_multimodal=False,
        openai_client=openai_client,
        openai_model=OPENAI_CHATGPT_MODEL,
        openai_deployment=AZURE_OPENAI_CHATGPT_DEPLOYMENT if OPENAI_HOST == OpenAIHost.AZURE else None,
    )
    chatbot_upload_search_info = setup_search_info(
        search_service=AZURE_SEARCH_SERVICE,
        index_name=AZURE_SEARCH_INDEX,
        azure_credential=azure_credential,
        use_agentic_knowledgebase=USE_AGENTIC_KNOWLEDGEBASE,
        azure_openai_endpoint=azure_openai_endpoint,
        knowledgebase_name=AZURE_SEARCH_KNOWLEDGEBASE_NAME,
        azure_openai_knowledgebase_deployment=AZURE_OPENAI_KNOWLEDGEBASE_DEPLOYMENT,
        azure_openai_knowledgebase_model=AZURE_OPENAI_KNOWLEDGEBASE_MODEL,
    )
    chatbot_upload_embeddings = None
    if USE_VECTORS:
        chatbot_upload_embeddings = setup_embeddings_service(
            open_ai_client=openai_client,
            openai_host=OPENAI_HOST,
            emb_model_name=OPENAI_EMB_MODEL,
            emb_model_dimensions=OPENAI_EMB_DIMENSIONS,
            azure_openai_deployment=AZURE_OPENAI_EMB_DEPLOYMENT,
            azure_openai_endpoint=azure_openai_endpoint,
        )

    # Upload limits for the free (public-test) chatbot.
    # Set one of these to None to disable that limit type.
    # To switch back to page-based limiting, set page limit and clear size limit.
    free_upload_page_limit = None  # e.g. 30 for 30 pages
    free_upload_size_limit_mb = 20  # e.g. 20 for 20 MB
    free_upload_file_count_limit = 1  # e.g. 1 for a single PDF
    chatbot_prompt_store = ChatbotPromptStore(blob_manager=global_blob_manager)
    current_app.config[CONFIG_CHATBOT_PROMPT_STORE] = chatbot_prompt_store

    # First-party LLM telemetry. The store writes into its OWN private container, never `content` --
    # `/content/<path>` is served unauthenticated in this deployment and turn records hold verbatim
    # end-user conversations. Constructed unconditionally so the write path exists from the first
    # request; TELEMETRY_ENABLED gates recording, not construction.
    telemetry_store = TelemetryStore(blob_manager=global_blob_manager)
    # Load the blob price overrides now. Without this, `TelemetryStore.__init__` leaves the table at
    # compiled+env and only the GET /pricing route ever refreshes it -- so a price saved in the editor
    # applied to the one replica that served the PUT, was lost on its next restart, and every other
    # replica went on recording that model as unpriced. Cost is frozen at write time, so those rows
    # would be permanently wrong. One blob read, and failure must not stop startup.
    try:
        await telemetry_store.refresh_price_table()
    except Exception:
        telemetry_logger.exception("Could not load the telemetry price overrides at startup")
    current_app.config[CONFIG_TELEMETRY_STORE] = telemetry_store

    current_app.config[CONFIG_CHATBOT_EMBED_CONFIG_STORE] = ChatbotEmbedConfigStore(blob_manager=global_blob_manager)

    # Dynamic chatbot provisioning (external PHP control panel). The registry store is the
    # runtime source of truth for *dynamic* bots only; built-in bots are never written here.
    current_app.config[CONFIG_CHATBOT_REGISTRY_STORE] = ChatbotRegistryStore(blob_manager=global_blob_manager)
    # Multi-replica-safe (ETag) session counter for the number_sessions quota of dynamic bots.
    current_app.config[CONFIG_CHATBOT_SESSION_COUNTER_STORE] = ChatbotSessionCounterStore(
        blob_manager=global_blob_manager
    )
    # Single source of truth for the isolation invariant: any name a built-in bot or framework
    # route already owns is off-limits to provisioning. Read by provisioning.assert_not_reserved.
    current_app.config[CONFIG_RESERVED_BOT_NAMES] = {
        normalize_chatbot_name(name) or name
        for name in (
            KNOWN_CHATBOT_NAMES
            | NON_CHATBOT_FRONTEND_PREFIXES
            | set(get_registered_chatbot_names())
            | set(CHATBOT_NAME_ALIASES)
            | {DEFAULT_CHATBOT_NAME}
        )
    }
    # STUB auth (plan Phase 0): static Bearer key from env. Final scheme TBD with the nerilio backend; when
    # promoted to an azd variable, wire it through main.parameters.json/main.bicep/pipelines.
    current_app.config[CONFIG_PROVISIONING_API_KEY] = os.getenv("PROVISIONING_API_KEY") or None
    await ensure_example_dynamic_bot_seeded()
    # Blob-backed store for the LLM-Wiki retrieval mode (pilot: Internal bot, lemon corpus).
    chatbot_wiki_store = ChatbotWikiStore(blob_manager=global_blob_manager)
    current_app.config[CONFIG_CHATBOT_WIKI_STORE] = chatbot_wiki_store

    internal_admin_auth_service = InternalAdminAuthStore(
        blob_manager=global_blob_manager,
        session_secret=AZURE_SERVER_APP_SECRET,
        admin_password=INTERNAL_TOOLS_PASSWORD,
    )
    await internal_admin_auth_service.setup()
    current_app.config[CONFIG_INTERNAL_ADMIN_AUTH_SERVICE] = internal_admin_auth_service
    simple_chatbot_session_secret = internal_admin_auth_service.session_secret
    if not simple_chatbot_session_secret:
        raise RuntimeError("Simple chatbot auth session secret is not configured")
    current_app.config[CONFIG_SIMPLE_CHATBOT_AUTH_SERVICE] = SimpleChatbotAuthStore(
        session_secret=simple_chatbot_session_secret,
        credentials=SIMPLE_CHATBOT_AUTH_CREDENTIALS,
    )

    free_auth_service = FreeAuthStore(
        blob_manager=global_blob_manager,
        session_secret=AZURE_SERVER_APP_SECRET,
        smtp_host=PUBLIC_TEST_SMTP_HOST,
        smtp_port=PUBLIC_TEST_SMTP_PORT,
        smtp_username=PUBLIC_TEST_SMTP_USERNAME,
        smtp_password=PUBLIC_TEST_SMTP_PASSWORD,
        email_from=PUBLIC_TEST_EMAIL_FROM,
        email_from_name=PUBLIC_TEST_EMAIL_FROM_NAME,
        running_in_production=RUNNING_ON_AZURE,
        hubspot_contact_store=HubSpotContactStore(api_key=HUBSPOT_API_KEY),
    )
    await free_auth_service.setup()
    current_app.config[CONFIG_FREE_AUTH_SERVICE] = free_auth_service
    current_app.config[CONFIG_CHATBOT_UPLOAD_MANAGERS] = {
        "demo": ChatbotUploadStrategy(
            chatbot_name="demo",
            search_info=chatbot_upload_search_info,
            file_processors=chatbot_upload_file_processors,
            embeddings=chatbot_upload_embeddings,
            search_field_name_embedding=AZURE_SEARCH_FIELD_NAME_EMBEDDING,
            blob_manager=global_blob_manager,
        ),
        "free": ChatbotUploadStrategy(
            chatbot_name="free",
            search_info=chatbot_upload_search_info,
            file_processors=chatbot_upload_file_processors,
            embeddings=chatbot_upload_embeddings,
            search_field_name_embedding=AZURE_SEARCH_FIELD_NAME_EMBEDDING,
            blob_manager=global_blob_manager,
            rules=ChatbotUploadRules(
                allowed_extensions=frozenset({".pdf"}),
                max_total_pdf_pages=free_upload_page_limit,
                max_total_file_size_mb=free_upload_size_limit_mb,
                max_total_file_count=free_upload_file_count_limit,
                user_scoped=True,
            ),
        ),
        "rak": ChatbotUploadStrategy(
            chatbot_name="rak",
            search_info=chatbot_upload_search_info,
            file_processors=chatbot_upload_file_processors,
            embeddings=chatbot_upload_embeddings,
            search_field_name_embedding=AZURE_SEARCH_FIELD_NAME_EMBEDDING,
            blob_manager=global_blob_manager,
            rules=ChatbotUploadRules(
                user_scoped=True,
            ),
        ),
    }
    current_app.config[CONFIG_CATEGORY_UPLOAD_MANAGER] = CategoryUploadStrategy(
        search_info=chatbot_upload_search_info,
        file_processors=chatbot_upload_file_processors,
        embeddings=chatbot_upload_embeddings,
        search_field_name_embedding=AZURE_SEARCH_FIELD_NAME_EMBEDDING,
        blob_manager=global_blob_manager,
        known_categories=KNOWN_CHATBOT_NAMES,
    )

    user_blob_manager = None
    if USE_USER_UPLOAD:
        current_app.logger.info("USE_USER_UPLOAD is true, setting up user upload feature")
        if not AZURE_USERSTORAGE_ACCOUNT or not AZURE_USERSTORAGE_CONTAINER:
            raise ValueError(
                "AZURE_USERSTORAGE_ACCOUNT and AZURE_USERSTORAGE_CONTAINER must be set when USE_USER_UPLOAD is true"
            )
        if not AZURE_ENFORCE_ACCESS_CONTROL:
            raise ValueError("AZURE_ENFORCE_ACCESS_CONTROL must be true when USE_USER_UPLOAD is true")
        user_blob_manager = AdlsBlobManager(
            endpoint=f"https://{AZURE_USERSTORAGE_ACCOUNT}.dfs.core.windows.net",
            container=AZURE_USERSTORAGE_CONTAINER,
            credential=azure_credential,
        )
        current_app.config[CONFIG_USER_BLOB_MANAGER] = user_blob_manager

        # Set up ingester
        file_processors, figure_processor = setup_file_processors(
            azure_credential=azure_credential,
            document_intelligence_service=os.getenv("AZURE_DOCUMENTINTELLIGENCE_SERVICE"),
            local_pdf_parser=os.getenv("USE_LOCAL_PDF_PARSER", "").lower() == "true",
            local_html_parser=os.getenv("USE_LOCAL_HTML_PARSER", "").lower() == "true",
            use_content_understanding=os.getenv("USE_CONTENT_UNDERSTANDING", "").lower() == "true",
            content_understanding_endpoint=os.getenv("AZURE_CONTENTUNDERSTANDING_ENDPOINT"),
            use_multimodal=USE_MULTIMODAL,
            openai_client=openai_client,
            openai_model=OPENAI_CHATGPT_MODEL,
            openai_deployment=AZURE_OPENAI_CHATGPT_DEPLOYMENT if OPENAI_HOST == OpenAIHost.AZURE else None,
        )
        search_info = setup_search_info(
            search_service=AZURE_SEARCH_SERVICE,
            index_name=AZURE_SEARCH_INDEX,
            azure_credential=azure_credential,
            use_agentic_knowledgebase=USE_AGENTIC_KNOWLEDGEBASE,
            azure_openai_endpoint=azure_openai_endpoint,
            knowledgebase_name=AZURE_SEARCH_KNOWLEDGEBASE_NAME,
            azure_openai_knowledgebase_deployment=AZURE_OPENAI_KNOWLEDGEBASE_DEPLOYMENT,
            azure_openai_knowledgebase_model=AZURE_OPENAI_KNOWLEDGEBASE_MODEL,
        )

        text_embeddings_service = None
        if USE_VECTORS:
            text_embeddings_service = setup_embeddings_service(
                open_ai_client=openai_client,
                openai_host=OPENAI_HOST,
                emb_model_name=OPENAI_EMB_MODEL,
                emb_model_dimensions=OPENAI_EMB_DIMENSIONS,
                azure_openai_deployment=AZURE_OPENAI_EMB_DEPLOYMENT,
                azure_openai_endpoint=azure_openai_endpoint,
            )

        image_embeddings_service = setup_image_embeddings_service(
            azure_credential=azure_credential,
            vision_endpoint=AZURE_VISION_ENDPOINT,
            use_multimodal=USE_MULTIMODAL,
        )
        ingester = UploadUserFileStrategy(
            search_info=search_info,
            file_processors=file_processors,
            embeddings=text_embeddings_service,
            image_embeddings=image_embeddings_service,
            search_field_name_embedding=AZURE_SEARCH_FIELD_NAME_EMBEDDING,
            blob_manager=user_blob_manager,
            figure_processor=figure_processor,
        )
        current_app.config[CONFIG_INGESTER] = ingester

    image_embeddings_client = None
    if USE_MULTIMODAL:
        image_embeddings_client = ImageEmbeddings(AZURE_VISION_ENDPOINT, azure_ai_token_provider)

    current_app.config[CONFIG_OPENAI_CLIENT] = openai_client
    current_app.config[CONFIG_SEARCH_CLIENT] = search_client
    current_app.config[CONFIG_KNOWLEDGEBASE_CLIENT] = knowledgebase_client
    current_app.config[CONFIG_KNOWLEDGEBASE_CLIENT_WITH_WEB] = knowledgebase_client_with_web
    current_app.config[CONFIG_KNOWLEDGEBASE_CLIENT_WITH_SHAREPOINT] = knowledgebase_client_with_sharepoint
    current_app.config[CONFIG_KNOWLEDGEBASE_CLIENT_WITH_WEB_AND_SHAREPOINT] = (
        knowledgebase_client_with_web_and_sharepoint
    )
    current_app.config[CONFIG_AUTH_CLIENT] = auth_helper

    current_app.config[CONFIG_SEMANTIC_RANKER_DEPLOYED] = AZURE_SEARCH_SEMANTIC_RANKER != "disabled"
    current_app.config[CONFIG_QUERY_REWRITING_ENABLED] = (
        AZURE_SEARCH_QUERY_REWRITING == "true" and AZURE_SEARCH_SEMANTIC_RANKER != "disabled"
    )
    chat_model_deployments = build_chat_model_deployments(
        OPENAI_CHATGPT_MODEL,
        AZURE_OPENAI_CHATGPT_DEPLOYMENT if OPENAI_HOST == OpenAIHost.AZURE else None,
    )
    current_app.config[CONFIG_AVAILABLE_CHAT_MODELS] = list(DEVELOPER_CHAT_MODELS)
    current_app.config[CONFIG_DEFAULT_CHAT_MODEL] = DEFAULT_DEVELOPER_CHAT_MODEL
    current_app.config[CONFIG_REASONING_CHAT_MODELS] = [
        model for model in DEVELOPER_CHAT_MODELS if model in Approach.GPT_REASONING_MODELS
    ]
    current_app.config[CONFIG_CHAT_MODEL_REASONING_EFFORTS] = {
        model: list(Approach.GPT_REASONING_MODELS[model].supported_efforts)
        for model in DEVELOPER_CHAT_MODELS
        if model in Approach.GPT_REASONING_MODELS
    }
    current_app.config[CONFIG_CHAT_MODEL_DEPLOYMENTS] = chat_model_deployments
    current_app.config[CONFIG_DEFAULT_REASONING_EFFORT] = OPENAI_REASONING_EFFORT
    current_app.config[CONFIG_DEFAULT_RETRIEVAL_REASONING_EFFORT] = AGENTIC_KNOWLEDGEBASE_REASONING_EFFORT
    current_app.config[CONFIG_REASONING_EFFORT_ENABLED] = OPENAI_CHATGPT_MODEL in Approach.GPT_REASONING_MODELS
    current_app.config[CONFIG_STREAMING_ENABLED] = (
        OPENAI_CHATGPT_MODEL not in Approach.GPT_REASONING_MODELS
        or Approach.GPT_REASONING_MODELS[OPENAI_CHATGPT_MODEL].streaming
    )
    current_app.config[CONFIG_VECTOR_SEARCH_ENABLED] = bool(USE_VECTORS)
    current_app.config[CONFIG_USER_UPLOAD_ENABLED] = bool(USE_USER_UPLOAD)
    current_app.config[CONFIG_LANGUAGE_PICKER_ENABLED] = ENABLE_LANGUAGE_PICKER
    current_app.config[CONFIG_SPEECH_INPUT_ENABLED] = USE_SPEECH_INPUT_BROWSER
    current_app.config[CONFIG_SPEECH_OUTPUT_BROWSER_ENABLED] = USE_SPEECH_OUTPUT_BROWSER
    current_app.config[CONFIG_SPEECH_OUTPUT_AZURE_ENABLED] = USE_SPEECH_OUTPUT_AZURE
    current_app.config[CONFIG_SPEECH_AVATAR_ENABLED] = USE_SPEECH_AVATAR
    current_app.config[CONFIG_SPEECH_AVATAR_VOICE] = AZURE_SPEECH_AVATAR_VOICE
    current_app.config[CONFIG_SPEECH_AVATAR_CHARACTER] = AZURE_SPEECH_AVATAR_CHARACTER
    current_app.config[CONFIG_SPEECH_AVATAR_STYLE] = AZURE_SPEECH_AVATAR_STYLE
    current_app.config[CONFIG_CHAT_HISTORY_BROWSER_ENABLED] = USE_CHAT_HISTORY_BROWSER
    current_app.config[CONFIG_CHAT_HISTORY_COSMOS_ENABLED] = USE_CHAT_HISTORY_COSMOS
    current_app.config[CONFIG_AGENTIC_KNOWLEDGEBASE_ENABLED] = USE_AGENTIC_KNOWLEDGEBASE
    current_app.config[CONFIG_LLM_WIKI_ENABLED] = USE_LLM_WIKI
    current_app.config[CONFIG_MULTIMODAL_ENABLED] = USE_MULTIMODAL
    current_app.config[CONFIG_RAG_SEARCH_TEXT_EMBEDDINGS] = RAG_SEARCH_TEXT_EMBEDDINGS
    current_app.config[CONFIG_RAG_SEARCH_IMAGE_EMBEDDINGS] = RAG_SEARCH_IMAGE_EMBEDDINGS
    current_app.config[CONFIG_RAG_SEND_TEXT_SOURCES] = RAG_SEND_TEXT_SOURCES
    current_app.config[CONFIG_RAG_SEND_IMAGE_SOURCES] = RAG_SEND_IMAGE_SOURCES
    current_app.config[CONFIG_WEB_SOURCE_ENABLED] = USE_WEB_SOURCE
    if AGENTIC_KNOWLEDGEBASE_REASONING_EFFORT == "minimal" and current_app.config[CONFIG_WEB_SOURCE_ENABLED]:
        raise ValueError("Web source cannot be used with minimal retrieval reasoning effort")
    current_app.config[CONFIG_SHAREPOINT_SOURCE_ENABLED] = USE_SHAREPOINT_SOURCE

    prompt_manager = PromptManager()

    # ChatReadRetrieveReadApproach is used by /chat for multi-turn conversation
    current_app.config[CONFIG_CHAT_APPROACH] = ChatReadRetrieveReadApproach(
        search_client=search_client,
        search_index_name=AZURE_SEARCH_INDEX,
        knowledgebase_model=AZURE_OPENAI_KNOWLEDGEBASE_MODEL,
        knowledgebase_deployment=AZURE_OPENAI_KNOWLEDGEBASE_DEPLOYMENT,
        knowledgebase_client=knowledgebase_client,
        knowledgebase_client_with_web=knowledgebase_client_with_web,
        knowledgebase_client_with_sharepoint=knowledgebase_client_with_sharepoint,
        knowledgebase_client_with_web_and_sharepoint=knowledgebase_client_with_web_and_sharepoint,
        openai_client=openai_client,
        chatgpt_model=OPENAI_CHATGPT_MODEL,
        chatgpt_deployment=AZURE_OPENAI_CHATGPT_DEPLOYMENT,
        embedding_model=OPENAI_EMB_MODEL,
        embedding_deployment=AZURE_OPENAI_EMB_DEPLOYMENT,
        embedding_dimensions=OPENAI_EMB_DIMENSIONS,
        embedding_field=AZURE_SEARCH_FIELD_NAME_EMBEDDING,
        sourcepage_field=KB_FIELDS_SOURCEPAGE,
        content_field=KB_FIELDS_CONTENT,
        query_language=AZURE_SEARCH_QUERY_LANGUAGE,
        query_speller=AZURE_SEARCH_QUERY_SPELLER,
        prompt_manager=prompt_manager,
        reasoning_effort=OPENAI_REASONING_EFFORT,
        multimodal_enabled=USE_MULTIMODAL,
        image_embeddings_client=image_embeddings_client,
        global_blob_manager=global_blob_manager,
        user_blob_manager=user_blob_manager,
        use_web_source=current_app.config[CONFIG_WEB_SOURCE_ENABLED],
        use_sharepoint_source=current_app.config[CONFIG_SHAREPOINT_SOURCE_ENABLED],
        retrieval_reasoning_effort=AGENTIC_KNOWLEDGEBASE_REASONING_EFFORT,
        chat_model_deployments=chat_model_deployments,
        wiki_store=chatbot_wiki_store,
    )

    # Per-chatbot approach overrides — auto-discovered from each chatbot's config.py.
    # An override is needed when the bot's model, deployment, or reasoning_effort differs from global defaults.
    shared_approach_kwargs = dict(
        search_client=search_client,
        search_index_name=AZURE_SEARCH_INDEX,
        knowledgebase_model=AZURE_OPENAI_KNOWLEDGEBASE_MODEL,
        knowledgebase_deployment=AZURE_OPENAI_KNOWLEDGEBASE_DEPLOYMENT,
        knowledgebase_client=knowledgebase_client,
        knowledgebase_client_with_web=knowledgebase_client_with_web,
        knowledgebase_client_with_sharepoint=knowledgebase_client_with_sharepoint,
        knowledgebase_client_with_web_and_sharepoint=knowledgebase_client_with_web_and_sharepoint,
        openai_client=openai_client,
        embedding_model=OPENAI_EMB_MODEL,
        embedding_deployment=AZURE_OPENAI_EMB_DEPLOYMENT,
        embedding_dimensions=OPENAI_EMB_DIMENSIONS,
        embedding_field=AZURE_SEARCH_FIELD_NAME_EMBEDDING,
        sourcepage_field=KB_FIELDS_SOURCEPAGE,
        content_field=KB_FIELDS_CONTENT,
        query_language=AZURE_SEARCH_QUERY_LANGUAGE,
        query_speller=AZURE_SEARCH_QUERY_SPELLER,
        prompt_manager=prompt_manager,
        multimodal_enabled=USE_MULTIMODAL,
        image_embeddings_client=image_embeddings_client,
        global_blob_manager=global_blob_manager,
        user_blob_manager=user_blob_manager,
        use_web_source=current_app.config[CONFIG_WEB_SOURCE_ENABLED],
        use_sharepoint_source=current_app.config[CONFIG_SHAREPOINT_SOURCE_ENABLED],
        retrieval_reasoning_effort=AGENTIC_KNOWLEDGEBASE_REASONING_EFFORT,
        chat_model_deployments=chat_model_deployments,
        wiki_store=chatbot_wiki_store,
    )
    chatbot_approaches: dict[str, ChatReadRetrieveReadApproach] = {}
    for bot_name, bot_cfg in load_all_chatbot_configs().items():
        model_differs = bot_cfg.chatgpt_model and bot_cfg.chatgpt_model != OPENAI_CHATGPT_MODEL
        deployment_differs = (
            bot_cfg.chatgpt_deployment and bot_cfg.chatgpt_deployment != AZURE_OPENAI_CHATGPT_DEPLOYMENT
        )
        reasoning_differs = bot_cfg.reasoning_effort is not None and bot_cfg.reasoning_effort != OPENAI_REASONING_EFFORT
        if model_differs or deployment_differs or reasoning_differs:
            model = bot_cfg.chatgpt_model or OPENAI_CHATGPT_MODEL
            deployment = bot_cfg.chatgpt_deployment or AZURE_OPENAI_CHATGPT_DEPLOYMENT
            chatbot_approaches[bot_name] = ChatReadRetrieveReadApproach(
                chatgpt_model=model,
                chatgpt_deployment=deployment if OPENAI_HOST == OpenAIHost.AZURE else None,
                reasoning_effort=(
                    bot_cfg.reasoning_effort if bot_cfg.reasoning_effort is not None else OPENAI_REASONING_EFFORT
                ),
                **shared_approach_kwargs,
            )
    current_app.config[CONFIG_CHATBOT_CHAT_APPROACHES] = chatbot_approaches


@bp.after_app_serving
async def close_clients():
    await current_app.config[CONFIG_SEARCH_CLIENT].close()
    await current_app.config[CONFIG_GLOBAL_BLOB_MANAGER].close_clients()
    if user_blob_manager := current_app.config.get(CONFIG_USER_BLOB_MANAGER):
        await user_blob_manager.close_clients()
    await current_app.config[CONFIG_CREDENTIAL].close()


def create_app():
    app = Quart(__name__)
    app.register_blueprint(bp)
    app.register_blueprint(chat_history_cosmosdb_bp)
    app.register_blueprint(provisioning_bp)

    openlit_endpoint = os.getenv("OPENLIT_ENDPOINT")  # e.g. "http://localhost:4318"

    if os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        app.logger.info("APPLICATIONINSIGHTS_CONNECTION_STRING is set, enabling Azure Monitor")
        configure_azure_monitor(
            instrumentation_options={
                "django": {"enabled": False},
                "psycopg2": {"enabled": False},
                "fastapi": {"enabled": False},
            }
        )
        # This tracks HTTP requests made by aiohttp:
        AioHttpClientInstrumentor().instrument()
        # This tracks HTTP requests made by httpx:
        HTTPXClientInstrumentor().instrument()

        if openlit_endpoint:
            # Add OTLP exporter so traces also flow to OpenLIT's ClickHouse
            app.logger.info("OPENLIT_ENDPOINT is set (%s), enabling OpenLIT dual-export", openlit_endpoint)
            provider = trace.get_tracer_provider()
            while hasattr(provider, "_real_provider"):
                provider = provider._real_provider
            if isinstance(provider, SDKTracerProvider):
                otlp_exporter = LLMOnlySpanExporter(OTLPSpanExporter(endpoint=f"{openlit_endpoint}/v1/traces"))
                provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
            else:
                app.logger.warning("Could not add OTLP span processor — TracerProvider type: %s", type(provider))

            # OpenLIT's OpenAI instrumentor is richer (cost tracking, token breakdowns)
            # so we use it INSTEAD of the community OpenAIInstrumentor
            import openlit

            openlit.init(
                otlp_endpoint=openlit_endpoint,
                application_name=os.getenv("OPENLIT_APP_NAME", "azure-search-openai-demo"),
                environment=os.getenv("OPENLIT_ENVIRONMENT", "production"),
                disabled_instrumentors=get_openlit_llm_only_disabled_instrumentors(),
            )
            app.logger.info("OpenLIT initialized successfully")
        else:
            # No OpenLIT — use community OpenAI instrumentor as before
            OpenAIInstrumentor().instrument()

        # This middleware tracks app route requests:
        app.asgi_app = OpenTelemetryMiddleware(app.asgi_app)  # type: ignore[assignment]

    elif openlit_endpoint:
        # Standalone OpenLIT mode (no Azure Monitor)
        app.logger.info("OPENLIT_ENDPOINT is set without Azure Monitor, enabling standalone OpenLIT")
        import openlit

        openlit.init(
            otlp_endpoint=openlit_endpoint,
            application_name=os.getenv("OPENLIT_APP_NAME", "azure-search-openai-demo"),
            environment=os.getenv("OPENLIT_ENVIRONMENT", "production"),
            disabled_instrumentors=get_openlit_llm_only_disabled_instrumentors(),
        )
        # Standalone OpenLIT should stay LLM-only, so we intentionally skip
        # the generic HTTP client and ASGI request instrumentation here.

    # Log levels should be one of https://docs.python.org/3/library/logging.html#logging-levels
    # Set root level to WARNING to avoid seeing overly verbose logs from SDKS
    logging.basicConfig(level=logging.WARNING)
    # Set our own logger levels to INFO by default
    app_level = os.getenv("APP_LOG_LEVEL", "INFO")
    app.logger.setLevel(os.getenv("APP_LOG_LEVEL", app_level))
    logging.getLogger("scripts").setLevel(app_level)
    # The HYROX assessment state engine logs completion/LMS-report lines and model-marker-drift warnings
    # on this logger; without an explicit level they are swallowed by the WARNING root config above.
    logging.getLogger("hyrox_assessment").setLevel(app_level)
    # Telemetry logs unattributed turns, zero-token agentic turns (the tripwire for a search-SDK field
    # rename) and every swallowed write failure; without an explicit level the WARNING root config
    # above hides them.
    logging.getLogger("telemetry").setLevel(app_level)

    if allowed_origin := os.getenv("ALLOWED_ORIGIN"):
        allowed_origins = allowed_origin.split(";")
        if len(allowed_origins) > 0:
            app.logger.info("CORS enabled for %s", allowed_origins)
            cors(app, allow_origin=allowed_origins, allow_methods=["GET", "POST"], allow_credentials=True)

    return app
