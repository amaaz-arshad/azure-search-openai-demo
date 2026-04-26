import dataclasses
import io
import json
import logging
import mimetypes
import os
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
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
    AzureDeveloperCliCredential,
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
from approaches.chatbot_config_registry import load_all_chatbot_configs
from approaches.chatbot_prompt_registry import (
    DEFAULT_CHATBOT_NAME,
    get_chatbot_prompt,
    get_registered_chatbot_names,
    normalize_chatbot_name,
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
    CONFIG_CHAT_MODEL_REASONING_EFFORTS,
    CONFIG_CHAT_MODEL_DEPLOYMENTS,
    CONFIG_CHATBOT_PROMPT_STORE,
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
    CONFIG_PUBLIC_TEST_AUTH_SERVICE,
    CONFIG_REASONING_EFFORT_ENABLED,
    CONFIG_REASONING_CHAT_MODELS,
    CONFIG_SEARCH_CLIENT,
    CONFIG_SEMANTIC_RANKER_DEPLOYED,
    CONFIG_SHAREPOINT_SOURCE_ENABLED,
    CONFIG_SIMPLE_CHATBOT_AUTH_SERVICE,
    CONFIG_SPEECH_INPUT_ENABLED,
    CONFIG_SPEECH_OUTPUT_AZURE_ENABLED,
    CONFIG_SPEECH_OUTPUT_BROWSER_ENABLED,
    CONFIG_SPEECH_SERVICE_ID,
    CONFIG_SPEECH_SERVICE_LOCATION,
    CONFIG_SPEECH_SERVICE_TOKEN,
    CONFIG_SPEECH_SERVICE_VOICE,
    CONFIG_STREAMING_ENABLED,
    CONFIG_USER_BLOB_MANAGER,
    CONFIG_USER_UPLOAD_ENABLED,
    CONFIG_VECTOR_SEARCH_ENABLED,
    CONFIG_WEB_SOURCE_ENABLED,
)
from core.authentication import AuthenticationHelper
from core.chatbotpromptstore import ChatbotPromptOverride, ChatbotPromptStore
from core.internaladminauth import (
    INTERNAL_ADMIN_INVALID_PASSWORD_MESSAGE,
    INTERNAL_ADMIN_PASSWORD_MISSING_MESSAGE,
    InternalAdminAuthStore,
)
from core.publictestauth import PublicTestAuthError, PublicTestAuthStore, PublicTestSession, normalize_public_test_email
from core.sessionhelper import create_session_id
from core.simplechatbotauth import (
    SIMPLE_CHATBOT_AUTH_INVALID_CREDENTIALS_MESSAGE,
    SIMPLE_CHATBOT_AUTH_REQUIRED_MESSAGE,
    SimpleChatbotAuthStore,
    SimpleChatbotCredentials,
    SimpleChatbotSession,
)
from decorators import authenticated, authenticated_path, internal_admin_required
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
PUBLIC_TEST_CHATBOT_NAME = "free"
FREE_CHATBOT_ROUTE_NAME = "free"
RAK_CHATBOT_NAME = "rak"
RAK_ALLOWED_USERNAMES = frozenset({"12345", "67890"})
INTERNAL_ROUTER_CHATBOT_NAME = "internal"
INTERNAL_INVALID_SOURCE_BOTS = frozenset({INTERNAL_ROUTER_CHATBOT_NAME, PUBLIC_TEST_CHATBOT_NAME, RAK_CHATBOT_NAME})

NON_CHATBOT_FRONTEND_PREFIXES = {
    "assets",
    "auth_setup",
    "chat",
    "chatbot-auth",
    "chatbot_uploads",
    "chatbots",
    "chat_history",
    "config",
    "content",
    "free-admin",
    "free-auth",
    "free-users",
    "delete_uploaded",
    "favicon.ico",
    "list_uploaded",
    "managed_uploads",
    "manage-prompts",
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
    "nerilio",
    "free",
    "public-test",
    "rak",
    "sartorius",
    "steuertipps",
    "knoll",
    "lemon",
    "internal",
    "moodle",
    "publishone",
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
        referer_first_segment = normalize_chatbot_name(urlparse(referer).path.strip("/").split("/", 1)[0])
        if referer_first_segment in KNOWN_CHATBOT_NAMES:
            return referer_first_segment

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


def get_public_test_auth_service() -> PublicTestAuthStore:
    auth_service = current_app.config.get(CONFIG_PUBLIC_TEST_AUTH_SERVICE)
    if auth_service is None:
        raise RuntimeError("Public-test auth service is not configured")
    return cast(PublicTestAuthStore, auth_service)


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


async def get_authenticated_public_test_user() -> PublicTestSession | None:
    auth_service = get_public_test_auth_service()
    return await auth_service.load_session(request.cookies.get(auth_service.session_cookie_name))


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
    if chatbot_name == PUBLIC_TEST_CHATBOT_NAME:
        public_test_user = await get_authenticated_public_test_user()
        return public_test_user.email if public_test_user is not None else None

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


async def serve_spa_index():
    # Avoid caching index.html so route changes and new bundles are picked up immediately.
    response = await send_from_directory(STATIC_ROOT, "index.html")
    response.cache_control.no_store = True
    response.cache_control.max_age = 0
    response.headers["Pragma"] = "no-cache"
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
async def public_test_users_page(subpath: str | None = None):
    if request.path.startswith("/public-test-users"):
        target = f"/free-users{f'/{subpath}' if subpath else ''}"
        return quart_redirect(target)
    return await serve_spa_index()


@bp.route("/manage-prompts")
@bp.route("/manage-prompts/")
@bp.route("/manage-prompts/<path:subpath>")
async def manage_prompts_page(subpath: str | None = None):
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
    if chatbot_name not in KNOWN_CHATBOT_NAMES:
        return quart_redirect("/")
    return await serve_spa_index()


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
    if requested_chatbot_name in {PUBLIC_TEST_CHATBOT_NAME, RAK_CHATBOT_NAME}:
        requested_user_identifier = await get_user_scoped_chatbot_user(requested_chatbot_name, allow_query_param=True)
        if requested_user_identifier is None:
            abort(401)

    if requested_chatbot_name:
        chatbot_upload_manager = chatbot_upload_managers.get(requested_chatbot_name)
        if chatbot_upload_manager is not None:
            if requested_chatbot_name in {PUBLIC_TEST_CHATBOT_NAME, RAK_CHATBOT_NAME}:
                result = await chatbot_upload_manager.download_file(
                    normalized_path,
                    user_identifier=requested_user_identifier,
                )
            else:
                result = await chatbot_upload_manager.download_file(normalized_path)

    if result is None and requested_chatbot_name is None:
        auth_service = get_simple_chatbot_auth_service()
        for chatbot_name, chatbot_upload_manager in chatbot_upload_managers.items():
            if chatbot_name in {PUBLIC_TEST_CHATBOT_NAME, RAK_CHATBOT_NAME}:
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


@bp.post("/free-auth/signup")
@bp.post("/public-test-auth/signup")
async def public_test_signup():
    if not request.is_json:
        return jsonify({"errorKey": "authErrors.unexpected"}), 415

    request_json = await request.get_json()
    if not isinstance(request_json, dict):
        return jsonify({"errorKey": "authErrors.unexpected"}), 400
    auth_service = get_public_test_auth_service()
    try:
        verification_challenge = await auth_service.start_signup(
            display_name=str(request_json.get("displayName", "")),
            email=str(request_json.get("email", "")),
            password=str(request_json.get("password", "")),
            confirm_password=str(request_json.get("confirmPassword", "")),
        )
    except PublicTestAuthError as auth_error:
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
async def public_test_signup_verify():
    if not request.is_json:
        return jsonify({"errorKey": "authErrors.unexpected"}), 415

    request_json = await request.get_json()
    if not isinstance(request_json, dict):
        return jsonify({"errorKey": "authErrors.unexpected"}), 400
    auth_service = get_public_test_auth_service()
    try:
        session = await auth_service.verify_signup(
            email=str(request_json.get("email", "")),
            verification_code=str(request_json.get("verificationCode", "")),
        )
    except PublicTestAuthError as auth_error:
        return jsonify({"errorKey": auth_error.error_key}), auth_error.status_code

    response = jsonify({"session": {"displayName": session.display_name, "email": session.email}})
    auth_service.set_session_cookie(response, session, secure=should_set_secure_session_cookie())
    return response, 200


@bp.post("/free-auth/signup/resend")
@bp.post("/public-test-auth/signup/resend")
async def public_test_signup_resend():
    if not request.is_json:
        return jsonify({"errorKey": "authErrors.unexpected"}), 415

    request_json = await request.get_json()
    if not isinstance(request_json, dict):
        return jsonify({"errorKey": "authErrors.unexpected"}), 400
    auth_service = get_public_test_auth_service()
    try:
        verification_challenge = await auth_service.resend_signup_code(
            email=str(request_json.get("email", "")),
        )
    except PublicTestAuthError as auth_error:
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
async def public_test_password_reset_start():
    if not request.is_json:
        return jsonify({"errorKey": "authErrors.unexpected"}), 415

    request_json = await request.get_json()
    if not isinstance(request_json, dict):
        return jsonify({"errorKey": "authErrors.unexpected"}), 400
    auth_service = get_public_test_auth_service()
    try:
        verification_challenge = await auth_service.start_password_reset(
            email=str(request_json.get("email", "")),
        )
    except PublicTestAuthError as auth_error:
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
async def public_test_password_reset_resend():
    if not request.is_json:
        return jsonify({"errorKey": "authErrors.unexpected"}), 415

    request_json = await request.get_json()
    if not isinstance(request_json, dict):
        return jsonify({"errorKey": "authErrors.unexpected"}), 400
    auth_service = get_public_test_auth_service()
    try:
        verification_challenge = await auth_service.resend_password_reset_code(
            email=str(request_json.get("email", "")),
        )
    except PublicTestAuthError as auth_error:
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
async def public_test_password_reset_verify():
    if not request.is_json:
        return jsonify({"errorKey": "authErrors.unexpected"}), 415

    request_json = await request.get_json()
    if not isinstance(request_json, dict):
        return jsonify({"errorKey": "authErrors.unexpected"}), 400
    auth_service = get_public_test_auth_service()
    try:
        session = await auth_service.verify_password_reset(
            email=str(request_json.get("email", "")),
            verification_code=str(request_json.get("verificationCode", "")),
            password=str(request_json.get("password", "")),
            confirm_password=str(request_json.get("confirmPassword", "")),
        )
    except PublicTestAuthError as auth_error:
        return jsonify({"errorKey": auth_error.error_key}), auth_error.status_code

    response = jsonify({"session": {"displayName": session.display_name, "email": session.email}})
    auth_service.set_session_cookie(response, session, secure=should_set_secure_session_cookie())
    return response, 200


@bp.post("/free-auth/login")
@bp.post("/public-test-auth/login")
async def public_test_login():
    if not request.is_json:
        return jsonify({"errorKey": "authErrors.unexpected"}), 415

    request_json = await request.get_json()
    if not isinstance(request_json, dict):
        return jsonify({"errorKey": "authErrors.unexpected"}), 400
    auth_service = get_public_test_auth_service()
    try:
        session = await auth_service.login_user(
            email=str(request_json.get("email", "")),
            password=str(request_json.get("password", "")),
        )
    except PublicTestAuthError as auth_error:
        return jsonify({"errorKey": auth_error.error_key}), auth_error.status_code

    response = jsonify({"session": {"displayName": session.display_name, "email": session.email}})
    auth_service.set_session_cookie(response, session, secure=should_set_secure_session_cookie())
    return response, 200


@bp.get("/free-auth/session")
@bp.get("/public-test-auth/session")
async def public_test_session():
    auth_service = get_public_test_auth_service()
    session = await get_authenticated_public_test_user()
    if session is None:
        response = jsonify({"errorKey": "authErrors.invalidCredentials"})
        auth_service.clear_session_cookie(response)
        return response, 401

    return jsonify({"session": {"displayName": session.display_name, "email": session.email}}), 200


@bp.get("/free-auth/profile")
@bp.get("/public-test-auth/profile")
async def public_test_profile():
    auth_service = get_public_test_auth_service()
    session = await get_authenticated_public_test_user()
    if session is None:
        response = jsonify({"errorKey": "authErrors.invalidCredentials"})
        auth_service.clear_session_cookie(response)
        return response, 401

    account = await auth_service.load_account(session.email)
    if account is None:
        response = jsonify({"errorKey": "authErrors.accountNotFound"})
        auth_service.clear_session_cookie(response)
        return response, 404

    return (
        jsonify(
            {
                "profile": {
                    "displayName": account.display_name,
                    "email": account.email,
                    "createdAt": account.created_at,
                    "updatedAt": account.updated_at,
                }
            }
        ),
        200,
    )


@bp.post("/free-auth/logout")
@bp.post("/public-test-auth/logout")
async def public_test_logout():
    auth_service = get_public_test_auth_service()
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


@bp.get("/free-admin/users")
@bp.get("/public-test-admin/users")
@internal_admin_required
async def list_public_test_admin_users():
    auth_service = get_public_test_auth_service()
    upload_manager = get_chatbot_upload_manager(PUBLIC_TEST_CHATBOT_NAME)
    users_payload: list[dict[str, Any]] = []

    for account in await auth_service.list_accounts():
        uploaded_files = await upload_manager.list_files(user_identifier=account.email)
        users_payload.append(
            {
                "displayName": account.display_name,
                "email": account.email,
                "createdAt": account.created_at,
                "updatedAt": account.updated_at,
                "uploadCount": len(uploaded_files),
                "uploadedFiles": uploaded_files,
            }
        )

    return jsonify({"users": users_payload}), 200


@bp.delete("/free-admin/users/<path:email>")
@bp.delete("/public-test-admin/users/<path:email>")
@internal_admin_required
async def delete_public_test_admin_user(email: str):
    normalized_email = normalize_public_test_email(email)
    if normalized_email is None:
        return jsonify({"message": "Valid email is required."}), 400

    upload_manager = get_chatbot_upload_manager(PUBLIC_TEST_CHATBOT_NAME)
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

    auth_service = get_public_test_auth_service()
    deleted_account = await auth_service.delete_account(normalized_email)
    if not deleted_account:
        return jsonify({"message": "Nerilio Bot user not found.", "deletedUploadCount": len(deleted_uploads)}), 404

    return (
        jsonify({"message": "Nerilio Bot user deleted successfully.", "deletedUploadCount": len(deleted_uploads)}),
        200,
    )


@bp.post("/free-admin/users/<path:email>/password")
@bp.post("/public-test-admin/users/<path:email>/password")
@internal_admin_required
async def reset_public_test_admin_user_password(email: str):
    if not request.is_json:
        return jsonify({"message": "Request must be JSON."}), 415

    request_json = await request.get_json()
    if not isinstance(request_json, dict):
        return jsonify({"message": "Request payload must be an object."}), 400

    auth_service = get_public_test_auth_service()
    try:
        updated_account = await auth_service.reset_account_password(
            email=email,
            password=str(request_json.get("password", "")),
            confirm_password=str(request_json.get("confirmPassword", "")),
        )
    except PublicTestAuthError as auth_error:
        return jsonify({"message": auth_error.error_key}), auth_error.status_code

    return (
        jsonify(
            {
                "message": "Nerilio Bot user password updated successfully.",
                "email": updated_account.email,
                "updatedAt": updated_account.updated_at,
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
    try:
        normalize_chatbot_request_overrides(request_json)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    context = request_json.get("context", {})
    simple_auth_chatbot_name = get_simple_auth_required_chatbot_name(resolve_requested_chatbot_name(request_json))
    if simple_auth_chatbot_name and get_authenticated_simple_chatbot_session(simple_auth_chatbot_name) is None:
        return build_simple_auth_required_response(simple_auth_chatbot_name)
    requested_chatbot_name = await apply_saved_chatbot_prompt_override(request_json)
    if requested_chatbot_name in {PUBLIC_TEST_CHATBOT_NAME, RAK_CHATBOT_NAME}:
        chatbot_user = await get_user_scoped_chatbot_user(requested_chatbot_name)
        if chatbot_user is None:
            return jsonify({"error": f"{requested_chatbot_name} requires login"}), 401
        overrides = context.setdefault("overrides", {})
        overrides["user"] = chatbot_user
    context["auth_claims"] = auth_claims
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
        result = await approach.run(
            request_json["messages"],
            context=context,
            session_state=session_state,
        )
        return jsonify(result)
    except Exception as error:
        return error_response(error, "/chat", error_context=error_context)


@bp.route("/chat/stream", methods=["POST"])
@authenticated
async def chat_stream(auth_claims: dict[str, Any]):
    if not request.is_json:
        return jsonify({"error": "request must be json"}), 415
    request_json = await request.get_json()
    error_context = get_request_error_context(request_json)
    try:
        normalize_chatbot_request_overrides(request_json)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    context = request_json.get("context", {})
    simple_auth_chatbot_name = get_simple_auth_required_chatbot_name(resolve_requested_chatbot_name(request_json))
    if simple_auth_chatbot_name and get_authenticated_simple_chatbot_session(simple_auth_chatbot_name) is None:
        return build_simple_auth_required_response(simple_auth_chatbot_name)
    requested_chatbot_name = await apply_saved_chatbot_prompt_override(request_json)
    if requested_chatbot_name in {PUBLIC_TEST_CHATBOT_NAME, RAK_CHATBOT_NAME}:
        chatbot_user = await get_user_scoped_chatbot_user(requested_chatbot_name)
        if chatbot_user is None:
            return jsonify({"error": f"{requested_chatbot_name} requires login"}), 401
        overrides = context.setdefault("overrides", {})
        overrides["user"] = chatbot_user
    context["auth_claims"] = auth_claims
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
        result = await approach.run_stream(
            request_json["messages"],
            context=context,
            session_state=session_state,
        )
        response = await make_response(format_as_ndjson(result, error_context=error_context))
        response.timeout = None  # type: ignore
        response.mimetype = "application/json-lines"
        return response
    except Exception as error:
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
    auth_service.clear_session_cookie(response, normalized_chatbot_name)
    return response, 200


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
            "showChatHistoryBrowser": current_app.config[CONFIG_CHAT_HISTORY_BROWSER_ENABLED],
            "showChatHistoryCosmos": current_app.config[CONFIG_CHAT_HISTORY_COSMOS_ENABLED],
            "showAgenticRetrievalOption": current_app.config[CONFIG_AGENTIC_KNOWLEDGEBASE_ENABLED],
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
                "voice": current_app.config[CONFIG_SPEECH_SERVICE_VOICE],
                "expiresAt": speech_token.expires_on,
            }
        )
    except Exception as error:
        current_app.logger.exception("Exception in /speech/token")
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
    if chatbot_name in {PUBLIC_TEST_CHATBOT_NAME, RAK_CHATBOT_NAME}:
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
    if chatbot_name in {PUBLIC_TEST_CHATBOT_NAME, RAK_CHATBOT_NAME}:
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
    if chatbot_name in {PUBLIC_TEST_CHATBOT_NAME, RAK_CHATBOT_NAME}:
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
    if chatbot_name in {PUBLIC_TEST_CHATBOT_NAME, RAK_CHATBOT_NAME}:
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
    if chatbot_name in {PUBLIC_TEST_CHATBOT_NAME, RAK_CHATBOT_NAME}:
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
    PUBLIC_TEST_EMAIL_FROM_NAME = os.getenv("PUBLIC_TEST_EMAIL_FROM_NAME", "Nerilio Bot")

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
    USE_CHAT_HISTORY_BROWSER = os.getenv("USE_CHAT_HISTORY_BROWSER", "").lower() == "true"
    USE_CHAT_HISTORY_COSMOS = os.getenv("USE_CHAT_HISTORY_COSMOS", "").lower() == "true"
    USE_AGENTIC_KNOWLEDGEBASE = os.getenv("USE_AGENTIC_KNOWLEDGEBASE", "").lower() == "true"
    USE_WEB_SOURCE = os.getenv("USE_WEB_SOURCE", "").lower() == "true"
    USE_SHAREPOINT_SOURCE = os.getenv("USE_SHAREPOINT_SOURCE", "").lower() == "true"
    AGENTIC_KNOWLEDGEBASE_REASONING_EFFORT = os.getenv("AGENTIC_KNOWLEDGEBASE_REASONING_EFFORT", "low")
    USE_VECTORS = os.getenv("USE_VECTORS", "").lower() != "false"

    # WEBSITE_HOSTNAME is always set by App Service, RUNNING_IN_PRODUCTION is set in main.bicep
    RUNNING_ON_AZURE = os.getenv("WEBSITE_HOSTNAME") is not None or os.getenv("RUNNING_IN_PRODUCTION") is not None

    # Use the current user identity for keyless authentication to Azure services.
    # This assumes you use 'azd auth login' locally, and managed identity when deployed on Azure.
    # The managed identity is setup in the infra/ folder.
    azure_credential: AzureDeveloperCliCredential | ManagedIdentityCredential
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
    elif AZURE_TENANT_ID:
        current_app.logger.info(
            "Setting up Azure credential using AzureDeveloperCliCredential with tenant_id %s", AZURE_TENANT_ID
        )
        azure_credential = AzureDeveloperCliCredential(tenant_id=AZURE_TENANT_ID, process_timeout=60)
    else:
        current_app.logger.info("Setting up Azure credential using AzureDeveloperCliCredential for home tenant")
        azure_credential = AzureDeveloperCliCredential(process_timeout=60)
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

    if USE_SPEECH_OUTPUT_AZURE or USE_SPEECH_INPUT_BROWSER:
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
    public_test_upload_page_limit = None  # e.g. 30 for 30 pages
    public_test_upload_size_limit_mb = 5  # e.g. 5 for 5 MB
    chatbot_prompt_store = ChatbotPromptStore(blob_manager=global_blob_manager)
    current_app.config[CONFIG_CHATBOT_PROMPT_STORE] = chatbot_prompt_store

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

    public_test_auth_service = PublicTestAuthStore(
        blob_manager=global_blob_manager,
        session_secret=AZURE_SERVER_APP_SECRET,
        smtp_host=PUBLIC_TEST_SMTP_HOST,
        smtp_port=PUBLIC_TEST_SMTP_PORT,
        smtp_username=PUBLIC_TEST_SMTP_USERNAME,
        smtp_password=PUBLIC_TEST_SMTP_PASSWORD,
        email_from=PUBLIC_TEST_EMAIL_FROM,
        email_from_name=PUBLIC_TEST_EMAIL_FROM_NAME,
        running_in_production=RUNNING_ON_AZURE,
    )
    await public_test_auth_service.setup()
    current_app.config[CONFIG_PUBLIC_TEST_AUTH_SERVICE] = public_test_auth_service
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
                max_total_pdf_pages=public_test_upload_page_limit,
                max_total_file_size_mb=public_test_upload_size_limit_mb,
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
    current_app.config[CONFIG_CHAT_HISTORY_BROWSER_ENABLED] = USE_CHAT_HISTORY_BROWSER
    current_app.config[CONFIG_CHAT_HISTORY_COSMOS_ENABLED] = USE_CHAT_HISTORY_COSMOS
    current_app.config[CONFIG_AGENTIC_KNOWLEDGEBASE_ENABLED] = USE_AGENTIC_KNOWLEDGEBASE
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

    if allowed_origin := os.getenv("ALLOWED_ORIGIN"):
        allowed_origins = allowed_origin.split(";")
        if len(allowed_origins) > 0:
            app.logger.info("CORS enabled for %s", allowed_origins)
            cors(app, allow_origin=allowed_origins, allow_methods=["GET", "POST"], allow_credentials=True)

    return app
