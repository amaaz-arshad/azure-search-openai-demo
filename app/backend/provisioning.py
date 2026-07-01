"""External chatbot provisioning API.

A single ingest endpoint (`POST /provisioning/chatbots`) lets an external control panel
(the nerilio backend PHP app) create / update / start / stop / delete *dynamic* chatbots. The
request is a JSON envelope dispatched on its ``operation`` field.

ISOLATION INVARIANT (must hold): this API governs ONLY newly created dynamic bots in the
runtime :class:`ChatbotRegistryStore`. It can never create/update/start/stop/delete a
built-in bot — any ``botName`` colliding with a reserved name is rejected. The 18 built-in
bots keep their hardcoded definitions and behavior untouched.

SCAFFOLDING STATUS: this is the additive Phase-1 skeleton (store wiring + operation dispatch
+ reserved-name guard). Two pieces are intentionally stubbed pending the contract with the
nerilio backend (plan Phase 0):

  * AUTH — `provisioning_api_key_required` is a static-Bearer-key stub. The final scheme
    (static key vs HMAC-SHA256 of the raw body) is TBD. ``sessionId`` in the payload is a
    correlation/idempotency id, NOT authentication.
  * QUOTA + delete cascade + dynamic resolution — deferred to later phases; see the TODOs.
"""

import hmac
import logging
import re
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar, cast

from quart import Blueprint, current_app, jsonify, request

from approaches.chatbot_prompt_registry import normalize_chatbot_name
from config import CONFIG_CHATBOT_REGISTRY_STORE, CONFIG_PROVISIONING_API_KEY, CONFIG_RESERVED_BOT_NAMES
from core.chatbotregistrystore import UNLIMITED_SESSIONS, ChatbotRegistryRecord, ChatbotRegistryStore

logger = logging.getLogger(__name__)

provisioning_bp = Blueprint("provisioning", __name__)

VALID_OPERATIONS = {"create", "update", "start", "stop", "delete"}
# Route slug: lowercase alphanumerics and hyphens, must start with an alphanumeric.
BOT_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")

_C = TypeVar("_C", bound=Callable[..., Any])


class ProvisioningError(Exception):
    """Raised to short-circuit a handler with an HTTP status + client message."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def get_chatbot_registry_store() -> ChatbotRegistryStore:
    store = current_app.config.get(CONFIG_CHATBOT_REGISTRY_STORE)
    if store is None:
        raise RuntimeError("Chatbot registry store is not configured")
    return cast(ChatbotRegistryStore, store)


def extract_bearer_token(authorization_header: str | None) -> str | None:
    if not authorization_header:
        return None
    parts = authorization_header.split(" ", 1)
    if len(parts) == 2 and parts[0].strip().lower() == "bearer":
        token = parts[1].strip()
        return token or None
    return None


def provisioning_api_key_required(route_fn: _C) -> _C:
    """Auth gate for the provisioning API.

    INTENTIONALLY OPEN FOR NOW. Until `PROVISIONING_API_KEY` is configured, requests pass through
    unauthenticated — by agreement, auth/security is a final hardening pass once the feature is
    complete and tested. When the key IS set, a matching `Authorization: Bearer <key>` is required,
    so turning auth on later is just setting the env var (or replacing this gate with the final
    scheme, e.g. HMAC of the body).
    """

    @wraps(route_fn)
    async def auth_handler(*args, **kwargs):
        expected_key = current_app.config.get(CONFIG_PROVISIONING_API_KEY)
        if not expected_key:
            return await route_fn(*args, **kwargs)  # open: no key configured → unauthenticated access
        provided_key = extract_bearer_token(request.headers.get("Authorization"))
        if not provided_key or not hmac.compare_digest(provided_key, expected_key):
            return jsonify({"ok": False, "error": "Unauthorized."}), 401
        return await route_fn(*args, **kwargs)

    return cast(_C, auth_handler)


def validate_bot_name(raw_bot_name: Any) -> str:
    if not isinstance(raw_bot_name, str) or not raw_bot_name.strip():
        raise ProvisioningError("botName is required.", 422)
    # Validate the value as sent — botName is the immutable primary key / route slug, so we
    # reject non-canonical input rather than silently transforming it (e.g. lowercasing).
    candidate = raw_bot_name.strip()
    if not BOT_NAME_PATTERN.match(candidate):
        raise ProvisioningError(
            "botName must be 1-63 chars of lowercase letters, digits, or hyphens and start with a letter or digit.",
            422,
        )
    normalized = normalize_chatbot_name(candidate)
    if normalized is None:
        raise ProvisioningError("botName is invalid.", 422)
    return normalized


def assert_not_reserved(bot_name: str) -> None:
    """Enforce the isolation invariant: dynamic bots may never shadow a built-in name."""
    reserved: set[str] = current_app.config.get(CONFIG_RESERVED_BOT_NAMES, set())
    if bot_name in reserved:
        raise ProvisioningError(
            f"botName '{bot_name}' is reserved by a built-in chatbot and cannot be provisioned.",
            409,
        )


def build_fields_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Map the create/update envelope (config lives under ``defaults``) onto store fields.

    Only keys present in the payload are returned, so ``save_record`` preserves existing
    values for anything omitted on an update.
    """
    fields: dict[str, Any] = {}
    if isinstance(payload.get("name"), str) and payload["name"].strip():
        fields["display_name"] = payload["name"].strip()

    defaults = payload.get("defaults")
    if not isinstance(defaults, dict):
        return fields

    number_sessions = defaults.get("number_sessions")
    if isinstance(number_sessions, bool):
        # Guard against JSON true/false sneaking in as an int.
        number_sessions = None
    if isinstance(number_sessions, int):
        fields["number_sessions"] = number_sessions
    elif isinstance(number_sessions, str) and number_sessions.lstrip("-").isdigit():
        fields["number_sessions"] = int(number_sessions)

    # Scalar passthroughs.
    for src, dst in (
        ("ansprache", "ansprache"),
        ("llm", "llm"),
        ("reasoning_effort", "reasoning_effort"),
        ("prompt", "prompt"),
    ):
        if src in defaults and isinstance(defaults[src], str):
            fields[dst] = defaults[src]

    # Nested behavior objects + per-language string maps stored verbatim.
    for key in ("modes", "design", "greeting", "disclaimer", "flagged", "features", "login", "qa", "tutor", "assessment"):
        if isinstance(defaults.get(key), dict):
            fields[key] = defaults[key]
    if isinstance(defaults.get("languages"), list):
        fields["languages"] = [item for item in defaults["languages"] if isinstance(item, str)]

    return fields


def record_summary(record: ChatbotRegistryRecord) -> dict[str, Any]:
    return {
        "botName": record.bot_name,
        "displayName": record.display_name,
        "active": record.active,
        "plan": record.plan,
        "numberSessions": record.number_sessions,
        "updatedAt": record.updated_at,
    }


async def handle_create(payload: dict[str, Any], bot_name: str) -> tuple[dict[str, Any], int]:
    store = get_chatbot_registry_store()
    if await store.load_record(bot_name) is not None:
        # TODO(nerilio contract): confirm whether a repeated create should be a no-op/upsert.
        raise ProvisioningError(f"botName '{bot_name}' already exists.", 409)
    fields = build_fields_from_payload(payload)
    # A freshly created bot is live; the panel uses start/stop to toggle thereafter.
    # TODO(nerilio contract): confirm whether create should start active or wait for `start`.
    fields["active"] = True
    fields.setdefault("number_sessions", UNLIMITED_SESSIONS)
    fields["last_session_id"] = payload.get("sessionId")
    record = await store.save_record(bot_name, fields=fields)
    return {"ok": True, "operation": "create", **record_summary(record)}, 201


async def handle_update(payload: dict[str, Any], bot_name: str) -> tuple[dict[str, Any], int]:
    store = get_chatbot_registry_store()
    if await store.load_record(bot_name) is None:
        raise ProvisioningError(f"botName '{bot_name}' does not exist.", 404)
    fields = build_fields_from_payload(payload)  # active intentionally preserved (not in fields)
    fields["last_session_id"] = payload.get("sessionId")
    record = await store.save_record(bot_name, fields=fields)
    return {"ok": True, "operation": "update", **record_summary(record)}, 200


async def handle_set_active(payload: dict[str, Any], bot_name: str, *, active: bool) -> tuple[dict[str, Any], int]:
    store = get_chatbot_registry_store()
    record = await store.set_active(bot_name, active)
    if record is None:
        raise ProvisioningError(f"botName '{bot_name}' does not exist.", 404)
    return {"ok": True, "operation": "start" if active else "stop", **record_summary(record)}, 200


async def handle_delete(payload: dict[str, Any], bot_name: str) -> tuple[dict[str, Any], int]:
    store = get_chatbot_registry_store()
    deleted = await store.delete_record(bot_name)
    if not deleted:
        raise ProvisioningError(f"botName '{bot_name}' does not exist.", 404)
    # TODO(Phase 4): cascade cleanup — prompt blob, embed config, per-bot Cosmos chat history,
    # and content category (reuse delete_category_data.py). Destructive; gate carefully.
    return {"ok": True, "operation": "delete", "botName": bot_name}, 200


@provisioning_bp.route("/provisioning/chatbots", methods=["POST"])
@provisioning_api_key_required
async def provision_chatbot():
    if not request.is_json:
        return jsonify({"ok": False, "error": "Request must be JSON."}), 415
    # silent=True suppresses JSON *parse* errors but NOT a UTF-8 *decode* error on the raw body
    # (e.g. a Latin-1-encoded umlaut), which would otherwise escape as an unhandled 500.
    try:
        payload = await request.get_json(silent=True)
    except (UnicodeDecodeError, ValueError):
        payload = None
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "Request body must be a valid UTF-8 JSON object."}), 400

    operation = payload.get("operation")
    if operation not in VALID_OPERATIONS:
        return (
            jsonify({"ok": False, "error": f"operation must be one of {sorted(VALID_OPERATIONS)}."}),
            422,
        )

    try:
        bot_name = validate_bot_name(payload.get("botName"))
        assert_not_reserved(bot_name)

        if operation == "create":
            body, status = await handle_create(payload, bot_name)
        elif operation == "update":
            body, status = await handle_update(payload, bot_name)
        elif operation == "start":
            body, status = await handle_set_active(payload, bot_name, active=True)
        elif operation == "stop":
            body, status = await handle_set_active(payload, bot_name, active=False)
        else:  # delete
            body, status = await handle_delete(payload, bot_name)
    except ProvisioningError as error:
        return jsonify({"ok": False, "operation": operation, "error": error.message}), error.status
    except Exception:
        logger.exception("Provisioning operation %s failed for botName=%s", operation, payload.get("botName"))
        return jsonify({"ok": False, "operation": operation, "error": "Internal error."}), 500

    # Echo the correlation id back for the caller.
    session_id = payload.get("sessionId")
    if isinstance(session_id, str):
        body["sessionId"] = session_id
    return jsonify(body), status
