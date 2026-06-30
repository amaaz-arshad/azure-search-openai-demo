"""Tests for dynamic (provisioned) chatbot resolution in app.py.

Covers `resolve_active_dynamic_record` and the dynamic branch of
`apply_saved_chatbot_prompt_override` — i.e. an active provisioned bot serving its own prompt +
model, while built-in bots stay on their unchanged source-defined path.

ISOLATION INVARIANT under test: a built-in name (e.g. "demo") never consults the registry and
never picks up a dynamic prompt/model.
"""

import pytest
from quart import Quart

import app as app_module
from approaches.chatbot_prompt_registry import normalize_chatbot_name
from config import CONFIG_CHATBOT_PROMPT_STORE, CONFIG_CHATBOT_REGISTRY_STORE
from core.chatbotregistrystore import ChatbotRegistryRecord


class FakeRegistry:
    def __init__(self, records=None):
        self.records = records or {}
        self.load_calls: list[str | None] = []

    async def load_record(self, name):
        self.load_calls.append(normalize_chatbot_name(name))
        return self.records.get(normalize_chatbot_name(name))


class FakePromptStore:
    def __init__(self):
        self.load_calls: list[str] = []

    async def load_prompt(self, name):
        self.load_calls.append(name)
        return None


def make_record(name, *, prompt="", llm=None, active=True):
    return ChatbotRegistryRecord(
        bot_name=name,
        display_name=name,
        active=active,
        created_at="2026-06-30T00:00:00+00:00",
        updated_at="2026-06-30T00:00:00+00:00",
        prompt=prompt,
        llm=llm,
    )


def make_ctx(registry, prompt_store=None):
    quart_app = Quart(__name__)
    quart_app.config[CONFIG_CHATBOT_REGISTRY_STORE] = registry
    quart_app.config[CONFIG_CHATBOT_PROMPT_STORE] = prompt_store or FakePromptStore()
    return quart_app


def req(name, **extra_overrides):
    overrides = {"include_category": name, **extra_overrides}
    return {"context": {"overrides": overrides}}


# --- resolve_active_dynamic_record --------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_returns_record_for_active_dynamic_bot():
    registry = FakeRegistry({"bxa": make_record("bxa", prompt="P", active=True)})
    quart_app = make_ctx(registry)
    async with quart_app.app_context():
        record = await app_module.resolve_active_dynamic_record("bxa")
    assert record is not None and record.bot_name == "bxa"


@pytest.mark.asyncio
async def test_resolve_returns_none_for_inactive_and_unknown():
    registry = FakeRegistry({"bxa": make_record("bxa", active=False)})
    quart_app = make_ctx(registry)
    async with quart_app.app_context():
        assert await app_module.resolve_active_dynamic_record("bxa") is None  # stopped
        assert await app_module.resolve_active_dynamic_record("ghost") is None  # unknown


@pytest.mark.asyncio
async def test_resolve_short_circuits_builtin_without_touching_registry():
    # "demo" is a built-in; resolution must return None BEFORE consulting the registry store.
    registry = FakeRegistry({"demo": make_record("demo", prompt="HIJACK", active=True)})
    quart_app = make_ctx(registry)
    async with quart_app.app_context():
        assert await app_module.resolve_active_dynamic_record("demo") is None
    assert registry.load_calls == []  # registry never consulted for a built-in name


# --- apply_saved_chatbot_prompt_override (dynamic branch) ---------------------------------


@pytest.mark.asyncio
async def test_dynamic_bot_injects_prompt_and_model():
    registry = FakeRegistry({"bxa": make_record("bxa", prompt="CUSTOM PROMPT", llm="gpt-5", active=True)})
    quart_app = make_ctx(registry)
    async with quart_app.app_context():
        request_json = req("bxa")
        name = await app_module.apply_saved_chatbot_prompt_override(request_json)
    overrides = request_json["context"]["overrides"]
    assert name == "bxa"
    assert overrides["__saved_prompt_template"] == "CUSTOM PROMPT"
    assert overrides["chat_model"] == "gpt-5"


@pytest.mark.asyncio
async def test_dynamic_bot_empty_prompt_uses_default_and_no_model():
    registry = FakeRegistry({"bxa": make_record("bxa", prompt="", llm=None, active=True)})
    quart_app = make_ctx(registry)
    async with quart_app.app_context():
        request_json = req("bxa")
        await app_module.apply_saved_chatbot_prompt_override(request_json)
    overrides = request_json["context"]["overrides"]
    assert overrides["__saved_prompt_template"] == app_module.DEFAULT_DYNAMIC_PROMPT
    assert "chat_model" not in overrides


@pytest.mark.asyncio
async def test_dynamic_bot_respects_explicit_client_model():
    registry = FakeRegistry({"bxa": make_record("bxa", prompt="P", llm="gpt-5", active=True)})
    quart_app = make_ctx(registry)
    async with quart_app.app_context():
        request_json = req("bxa", chat_model="gpt-4.1")
        await app_module.apply_saved_chatbot_prompt_override(request_json)
    # setdefault keeps the explicit developer-selected model.
    assert request_json["context"]["overrides"]["chat_model"] == "gpt-4.1"


@pytest.mark.asyncio
async def test_builtin_bot_path_unchanged_uses_prompt_store_not_registry():
    registry = FakeRegistry({"demo": make_record("demo", prompt="HIJACK", llm="gpt-5", active=True)})
    prompt_store = FakePromptStore()
    quart_app = make_ctx(registry, prompt_store)
    async with quart_app.app_context():
        request_json = req("demo")
        name = await app_module.apply_saved_chatbot_prompt_override(request_json)
    overrides = request_json["context"]["overrides"]
    assert name == "demo"
    assert "__saved_prompt_template" not in overrides  # no dynamic prompt leaked in
    assert "chat_model" not in overrides
    assert registry.load_calls == []  # registry untouched for a built-in
    assert prompt_store.load_calls == ["demo"]  # built-in still uses the prompt store


@pytest.mark.asyncio
async def test_inactive_dynamic_bot_falls_back_to_prompt_store():
    registry = FakeRegistry({"bxa": make_record("bxa", prompt="CUSTOM", active=False)})
    prompt_store = FakePromptStore()
    quart_app = make_ctx(registry, prompt_store)
    async with quart_app.app_context():
        request_json = req("bxa")
        await app_module.apply_saved_chatbot_prompt_override(request_json)
    # A stopped bot is not served dynamically; no dynamic prompt is injected.
    assert "__saved_prompt_template" not in request_json["context"]["overrides"]
    assert prompt_store.load_calls == ["bxa"]


# --- enforce_dynamic_chatbot_gate (stopped-bot gate) --------------------------------------


@pytest.mark.asyncio
async def test_gate_rejects_stopped_dynamic_bot_with_403():
    registry = FakeRegistry({"bxa": make_record("bxa", active=False)})
    quart_app = make_ctx(registry)
    async with quart_app.app_context():
        gate = await app_module.enforce_dynamic_chatbot_gate("bxa")
        assert gate is not None
        response, status = gate
        assert status == 403
        body = await response.get_json()
    assert body["error"] == "chatbot_inactive"
    assert body["chatbotName"] == "bxa"


@pytest.mark.asyncio
async def test_gate_allows_active_dynamic_bot():
    registry = FakeRegistry({"bxa": make_record("bxa", active=True)})
    quart_app = make_ctx(registry)
    async with quart_app.app_context():
        assert await app_module.enforce_dynamic_chatbot_gate("bxa") is None


@pytest.mark.asyncio
async def test_gate_allows_unknown_dynamic_name():
    registry = FakeRegistry({})
    quart_app = make_ctx(registry)
    async with quart_app.app_context():
        assert await app_module.enforce_dynamic_chatbot_gate("ghost") is None


@pytest.mark.asyncio
async def test_gate_never_touches_registry_for_builtin():
    # Even a (hypothetical) stale same-named record must not gate a built-in bot.
    registry = FakeRegistry({"demo": make_record("demo", active=False)})
    quart_app = make_ctx(registry)
    async with quart_app.app_context():
        assert await app_module.enforce_dynamic_chatbot_gate("demo") is None
    assert registry.load_calls == []  # built-in short-circuits before any registry load
