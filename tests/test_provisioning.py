"""Tests for the dynamic chatbot provisioning API (Phase-1 scaffolding).

Covers the ingest endpoint (auth stub, operation dispatch, reserved-name guard, and
create/update/start/stop/delete handlers) against an in-memory fake registry store, plus a
real serialize/deserialize round-trip on ChatbotRegistryStore.

ISOLATION INVARIANT under test: a botName colliding with a reserved (built-in) name is
rejected, so provisioning can never touch the 18 built-in bots.
"""

from datetime import datetime, timezone
from unittest import mock

import pytest
from quart import Quart

from approaches.chatbot_prompt_registry import normalize_chatbot_name
from config import (
    CONFIG_CHATBOT_EMBED_CONFIG_STORE,
    CONFIG_CHATBOT_REGISTRY_STORE,
    CONFIG_PROVISIONING_API_KEY,
    CONFIG_RESERVED_BOT_NAMES,
)
from core.chatbotregistrystore import (
    UNLIMITED_SESSIONS,
    ChatbotRegistryRecord,
    ChatbotRegistryStore,
    format_utc,
)
from embed_public_ids import DYNAMIC_PUBLIC_ID_INDEX, EMBED_PUBLIC_IDS, PUBLIC_ID_RE
from provisioning import build_fields_from_payload, provisioning_bp

API_KEY = "test-key"
AUTH_HEADERS = {"Authorization": f"Bearer {API_KEY}"}
RESERVED = {"demo", "internal", "free", "nerilio", "config", "chat", "embed"}


class FakeRegistryStore:
    """In-memory stand-in mirroring ChatbotRegistryStore's merge + timestamp semantics."""

    def __init__(self):
        self.records: dict[str, ChatbotRegistryRecord] = {}

    async def load_record(self, bot_name):
        return self.records.get(normalize_chatbot_name(bot_name))

    async def list_records(self):
        return dict(self.records)

    async def save_record(self, bot_name, *, fields):
        name = normalize_chatbot_name(bot_name)
        assert name is not None
        existing = self.records.get(name)
        now = format_utc(datetime.now(timezone.utc))

        def merged(key, attr, default):
            return fields.get(key, getattr(existing, attr) if existing else default)

        record = ChatbotRegistryRecord(
            bot_name=name,
            display_name=fields.get("display_name") or (existing.display_name if existing else name),
            active=bool(fields["active"]) if "active" in fields else (existing.active if existing else False),
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
            # Write-once, like the real store: a stored ID can never be rotated by an update.
            embed_public_id=(existing.embed_public_id if existing and existing.embed_public_id else None)
            or fields.get("embed_public_id"),
            plan=merged("plan", "plan", None),
            number_sessions=merged("number_sessions", "number_sessions", UNLIMITED_SESSIONS),
            ansprache=merged("ansprache", "ansprache", None),
            llm=merged("llm", "llm", None),
            reasoning_effort=merged("reasoning_effort", "reasoning_effort", None),
            prompt=merged("prompt", "prompt", ""),
            modes=merged("modes", "modes", {}),
            design=merged("design", "design", {}),
            languages=merged("languages", "languages", []),
            greeting=merged("greeting", "greeting", {}),
            disclaimer=merged("disclaimer", "disclaimer", {}),
            flagged=merged("flagged", "flagged", {}),
            features=merged("features", "features", {}),
            login=merged("login", "login", {}),
            qa=merged("qa", "qa", {}),
            tutor=merged("tutor", "tutor", {}),
            assessment=merged("assessment", "assessment", {}),
            last_session_id=merged("last_session_id", "last_session_id", None),
        )
        self.records[name] = record
        return record

    async def set_active(self, bot_name, active):
        if normalize_chatbot_name(bot_name) not in self.records:
            return None
        return await self.save_record(bot_name, fields={"active": active})

    async def delete_record(self, bot_name):
        return self.records.pop(normalize_chatbot_name(bot_name), None) is not None


class FakeEmbedConfigStore:
    """Tracks the embed-whitelist cascade on delete."""

    def __init__(self):
        self.deleted: list[str] = []

    async def delete_config(self, chatbot_name):
        self.deleted.append(chatbot_name)
        return True


@pytest.fixture(autouse=True)
def clear_public_id_index():
    # The publicId -> botName index is a module-level cache; leaking entries across tests would let
    # one test's minted ID satisfy another's assertions.
    DYNAMIC_PUBLIC_ID_INDEX.by_public_id.clear()
    DYNAMIC_PUBLIC_ID_INDEX.last_refresh = None
    yield
    DYNAMIC_PUBLIC_ID_INDEX.by_public_id.clear()
    DYNAMIC_PUBLIC_ID_INDEX.last_refresh = None


def make_app(*, api_key: str | None = API_KEY):
    app = Quart(__name__)
    app.register_blueprint(provisioning_bp)
    store = FakeRegistryStore()
    app.config[CONFIG_CHATBOT_REGISTRY_STORE] = store
    app.config[CONFIG_CHATBOT_EMBED_CONFIG_STORE] = FakeEmbedConfigStore()
    app.config[CONFIG_RESERVED_BOT_NAMES] = set(RESERVED)
    app.config[CONFIG_PROVISIONING_API_KEY] = api_key
    return app, store


def create_payload(**overrides):
    payload = {
        "sessionId": "sess-1",
        "name": "ABX",
        "botName": "bxa",
        "operation": "create",
        "defaults": {
            "ansprache": "informal",
            "llm": "gpt-5",
            "prompt": "",
            "modes": {"qa": True, "tutor": True, "assessment": False},
            "design": {"color_primary": "#AC44C6", "color_secondary": "#00cc96"},
            "languages": ["Deutsch"],
            "greeting": {"Deutsch": "Willkommen!"},
            "disclaimer": {"Deutsch": "KI-Assistent."},
            "flagged": {"Deutsch": ""},
            "features": {"disclaimer": True, "history": True, "sources": False},
            "login": {"required": False, "provider": "email"},
            "number_sessions": 10000,
        },
    }
    payload.update(overrides)
    return payload


async def post(client, payload, headers=AUTH_HEADERS):
    resp = await client.post("/provisioning/chatbots", json=payload, headers=headers)
    return resp, await resp.get_json()


# --- auth (open until a key is configured) ------------------------------------------------


@pytest.mark.asyncio
async def test_open_when_api_key_not_configured():
    # No key configured → the API is unauthenticated; a call with no auth header succeeds.
    app, store = make_app(api_key=None)
    resp, body = await post(app.test_client(), create_payload(), headers={})
    assert resp.status_code == 201
    assert body["ok"] is True
    assert "bxa" in store.records


@pytest.mark.asyncio
async def test_enforces_bearer_once_key_is_configured():
    # Setting a key flips on auth: missing/wrong Bearer → 401 (the future hardening path).
    app, _ = make_app()
    client = app.test_client()
    resp, _ = await post(client, create_payload(), headers={})
    assert resp.status_code == 401
    resp, _ = await post(client, create_payload(), headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


# --- validation / dispatch ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_operation_returns_422():
    app, _ = make_app()
    resp, body = await post(app.test_client(), create_payload(operation="restart"))
    assert resp.status_code == 422
    assert body["ok"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_name", ["", "  ", "Has Space", "UPPER", "-leading", "white/space"])
async def test_invalid_bot_name_returns_422(bad_name):
    app, _ = make_app()
    resp, _ = await post(app.test_client(), create_payload(botName=bad_name))
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_non_json_returns_415():
    app, _ = make_app()
    resp = await app.test_client().post("/provisioning/chatbots", data="not json", headers=AUTH_HEADERS)
    assert resp.status_code == 415


@pytest.mark.asyncio
async def test_non_utf8_body_returns_400_not_500():
    # A body that isn't valid UTF-8 (e.g. a Latin-1 umlaut) must be a clean 400, not an unhandled 500.
    app, _ = make_app(api_key=None)
    resp = await app.test_client().post(
        "/provisioning/chatbots",
        data=b'{"botName": "bxa", "operation": "create", "x": "\xfc"}',
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400


# --- isolation invariant ------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("reserved_name", ["demo", "internal", "nerilio", "config"])
async def test_reserved_name_is_rejected(reserved_name):
    app, store = make_app()
    resp, body = await post(app.test_client(), create_payload(botName=reserved_name))
    assert resp.status_code == 409
    assert "reserved" in body["error"].lower()
    assert store.records == {}  # nothing written for a built-in name


# --- lifecycle ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_then_duplicate():
    app, store = make_app()
    client = app.test_client()
    resp, body = await post(client, create_payload())
    assert resp.status_code == 201
    assert body["botName"] == "bxa"
    assert body["active"] is True  # created bots start live
    assert body["numberSessions"] == 10000
    assert body["sessionId"] == "sess-1"
    assert "bxa" in store.records

    resp, body = await post(client, create_payload())
    assert resp.status_code == 409
    assert body["ok"] is False


@pytest.mark.asyncio
async def test_update_preserves_active_and_created_at_changes_display_name():
    app, store = make_app()
    client = app.test_client()
    await post(client, create_payload())
    created = store.records["bxa"]

    update = create_payload(operation="update", name="ABX2", sessionId="sess-2")
    resp, body = await post(client, update)
    assert resp.status_code == 200
    record = store.records["bxa"]
    assert body["displayName"] == "ABX2"
    assert record.active is True  # update never flips the start/stop flag
    assert record.created_at == created.created_at  # created_at preserved across updates
    assert record.last_session_id == "sess-2"


@pytest.mark.asyncio
async def test_update_missing_returns_404():
    app, _ = make_app()
    resp, _ = await post(app.test_client(), create_payload(operation="update"))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_start_stop_toggle_active():
    app, store = make_app()
    client = app.test_client()
    await post(client, create_payload())

    resp, body = await post(client, {"sessionId": "s", "botName": "bxa", "operation": "stop"})
    assert resp.status_code == 200
    assert body["active"] is False
    assert store.records["bxa"].active is False

    resp, body = await post(client, {"sessionId": "s", "botName": "bxa", "operation": "start"})
    assert resp.status_code == 200
    assert body["active"] is True
    assert store.records["bxa"].active is True


@pytest.mark.asyncio
async def test_start_missing_returns_404():
    app, _ = make_app()
    resp, _ = await post(app.test_client(), {"sessionId": "s", "botName": "ghost", "operation": "start"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete():
    app, store = make_app()
    client = app.test_client()
    await post(client, create_payload())

    resp, body = await post(client, {"sessionId": "s", "botName": "bxa", "operation": "delete"})
    assert resp.status_code == 200
    assert body["botName"] == "bxa"
    assert "bxa" not in store.records

    resp, _ = await post(client, {"sessionId": "s", "botName": "bxa", "operation": "delete"})
    assert resp.status_code == 404


# --- embed identity -----------------------------------------------------------------------
#
# A provisioned bot must be embeddable from the moment it exists: create mints its anonymous public
# ID, so it shows up in the admin directory and the embed picker with no extra step.


@pytest.mark.asyncio
async def test_create_mints_a_public_id_and_returns_a_ready_snippet():
    app, store = make_app()
    resp, body = await post(app.test_client(), create_payload())
    assert resp.status_code == 201

    public_id = body["publicId"]
    assert PUBLIC_ID_RE.match(public_id), public_id
    assert public_id not in EMBED_PUBLIC_IDS.values()  # never collides with a built-in
    assert store.records["bxa"].embed_public_id == public_id  # persisted on the record
    # The panel can show the customer their embed code straight from the response.
    assert body["embedSnippet"].endswith(f'data-chatbot-id="{public_id}"></script>')
    assert "/widget.js" in body["embedSnippet"]
    # The readable route name must never leak into the snippet.
    assert "bxa" not in body["embedSnippet"]


@pytest.mark.asyncio
async def test_created_bots_get_distinct_public_ids():
    app, _ = make_app()
    client = app.test_client()
    _, first = await post(client, create_payload(botName="bxa"))
    _, second = await post(client, create_payload(botName="other"))
    assert first["publicId"] != second["publicId"]


@pytest.mark.asyncio
async def test_update_never_rotates_the_public_id():
    # Rotating it would silently break every embed snippet already pasted on a customer's site.
    app, store = make_app()
    client = app.test_client()
    _, created = await post(client, create_payload())
    _, updated = await post(client, create_payload(operation="update", name="ABX2"))
    assert updated["publicId"] == created["publicId"]
    assert store.records["bxa"].embed_public_id == created["publicId"]


@pytest.mark.asyncio
async def test_start_and_stop_preserve_the_public_id():
    app, _ = make_app()
    client = app.test_client()
    _, created = await post(client, create_payload())
    _, stopped = await post(client, {"sessionId": "s", "botName": "bxa", "operation": "stop"})
    _, started = await post(client, {"sessionId": "s", "botName": "bxa", "operation": "start"})
    assert stopped["publicId"] == created["publicId"]
    assert started["publicId"] == created["publicId"]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["update", "start", "stop"])
async def test_legacy_record_without_a_public_id_is_backfilled(operation):
    # Bots provisioned before dynamic embedding existed have no ID; any later operation heals them.
    app, store = make_app()
    await store.save_record("bxa", fields={"active": True})
    assert store.records["bxa"].embed_public_id is None

    payload = create_payload(operation=operation) if operation == "update" else {"botName": "bxa", "operation": operation}
    resp, body = await post(app.test_client(), payload)
    assert resp.status_code == 200
    assert PUBLIC_ID_RE.match(body["publicId"])
    assert store.records["bxa"].embed_public_id == body["publicId"]


@pytest.mark.asyncio
async def test_delete_removes_the_embed_whitelist_and_forgets_the_id():
    # The whitelist is keyed by bot NAME, so leaving it behind would apply one customer's allowed
    # domains to the next bot provisioned under the same name.
    app, _ = make_app()
    client = app.test_client()
    _, created = await post(client, create_payload())
    assert DYNAMIC_PUBLIC_ID_INDEX.by_public_id.get(created["publicId"]) == "bxa"

    resp, _ = await post(client, {"sessionId": "s", "botName": "bxa", "operation": "delete"})
    assert resp.status_code == 200
    assert app.config[CONFIG_CHATBOT_EMBED_CONFIG_STORE].deleted == ["bxa"]
    assert created["publicId"] not in DYNAMIC_PUBLIC_ID_INDEX.by_public_id


@pytest.mark.asyncio
async def test_delete_still_succeeds_when_the_whitelist_cleanup_fails():
    app, store = make_app()
    client = app.test_client()
    await post(client, create_payload())

    class ExplodingEmbedStore:
        async def delete_config(self, chatbot_name):
            raise RuntimeError("blob storage is down")

    app.config[CONFIG_CHATBOT_EMBED_CONFIG_STORE] = ExplodingEmbedStore()
    resp, body = await post(client, {"sessionId": "s", "botName": "bxa", "operation": "delete"})
    # The record is already gone at that point, so a cascade failure must not fail the operation.
    assert resp.status_code == 200
    assert body["ok"] is True
    assert "bxa" not in store.records


@pytest.mark.asyncio
async def test_delete_works_without_an_embed_store_configured():
    app, _ = make_app()
    client = app.test_client()
    await post(client, create_payload())
    app.config[CONFIG_CHATBOT_EMBED_CONFIG_STORE] = None
    resp, _ = await post(client, {"sessionId": "s", "botName": "bxa", "operation": "delete"})
    assert resp.status_code == 200


# --- pure helpers -------------------------------------------------------------------------


def test_build_fields_from_payload_maps_defaults():
    fields = build_fields_from_payload(create_payload())
    assert fields["display_name"] == "ABX"
    assert fields["number_sessions"] == 10000
    assert fields["llm"] == "gpt-5"
    assert fields["modes"] == {"qa": True, "tutor": True, "assessment": False}
    assert fields["languages"] == ["Deutsch"]
    assert "active" not in fields  # active is decided by the operation, not the payload


def test_build_fields_from_payload_number_sessions_variants():
    assert build_fields_from_payload({"defaults": {"number_sessions": -1}})["number_sessions"] == -1
    assert build_fields_from_payload({"defaults": {"number_sessions": "5000"}})["number_sessions"] == 5000
    # booleans must not be coerced into an int session cap
    assert "number_sessions" not in build_fields_from_payload({"defaults": {"number_sessions": True}})


def test_build_fields_from_payload_maps_reasoning_effort():
    assert build_fields_from_payload({"defaults": {"reasoning_effort": "high"}})["reasoning_effort"] == "high"
    # non-string values are ignored (only scalar strings pass through)
    assert "reasoning_effort" not in build_fields_from_payload({"defaults": {"reasoning_effort": 3}})


def test_registry_store_serialize_deserialize_round_trip():
    store = ChatbotRegistryStore(blob_manager=mock.Mock())
    record = ChatbotRegistryRecord(
        bot_name="bxa",
        display_name="ABX",
        active=True,
        created_at="2026-06-30T00:00:00+00:00",
        updated_at="2026-06-30T00:00:00+00:00",
        plan="Pro",
        number_sessions=10000,
        ansprache="informal",
        llm="gpt-5",
        reasoning_effort="high",
        prompt="hello",
        modes={"qa": True},
        languages=["Deutsch"],
        greeting={"Deutsch": "Hallo"},
    )
    round_tripped = store.deserialize_record("bxa", store.serialize_record(record))
    assert round_tripped == record


def test_registry_store_deserialize_rejects_incomplete_payload():
    store = ChatbotRegistryStore(blob_manager=mock.Mock())
    assert store.deserialize_record("bxa", {"botName": "bxa"}) is None  # missing timestamps
    assert store.deserialize_record("bxa", None) is None
