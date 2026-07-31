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
from config import CONFIG_CHAT_MODEL_DEPLOYMENTS, CONFIG_CHATBOT_PROMPT_STORE, CONFIG_CHATBOT_REGISTRY_STORE
from core.chatbotregistrystore import ChatbotRegistryRecord
from core.dynamic_bot_config import DEFAULT_DYNAMIC_QNA_MODEL, DEFAULT_DYNAMIC_TUTOR_MODEL
from core.dynamic_tutor_prompt import DEFAULT_DYNAMIC_TUTOR_PROMPT
from embed_public_ids import DYNAMIC_PUBLIC_ID_INDEX, EMBED_PUBLIC_IDS, PUBLIC_ID_RE, get_public_id

# Deployed chat models available in the test app (mirrors what build_chat_model_deployments produces).
DEPLOYED_MODELS = {"gpt-5": "gpt-5", "gpt-5.4": "gpt-5.4", "gpt-5.4-mini": "gpt-5.4-mini", "gpt-4.1": "gpt-4.1"}


class FakeRegistry:
    def __init__(self, records=None):
        self.records = records or {}
        self.load_calls: list[str | None] = []
        self.save_calls: list[tuple[str | None, dict]] = []

    async def load_record(self, name):
        self.load_calls.append(normalize_chatbot_name(name))
        return self.records.get(normalize_chatbot_name(name))

    async def list_records(self):
        return dict(self.records)

    async def save_record(self, bot_name, *, fields):
        normalized = normalize_chatbot_name(bot_name)
        self.save_calls.append((normalized, dict(fields)))
        existing = self.records.get(normalized)
        self.records[normalized] = make_record(
            normalized,
            prompt=fields.get("prompt", ""),
            llm=fields.get("llm"),
            active=bool(fields.get("active", existing.active if existing else False)),
            modes=fields.get("modes"),
            # Write-once, like the real store.
            embed_public_id=(existing.embed_public_id if existing and existing.embed_public_id else None)
            or fields.get("embed_public_id"),
        )
        return self.records[normalized]


class FakePromptStore:
    def __init__(self):
        self.load_calls: list[str] = []

    async def load_prompt(self, name):
        self.load_calls.append(name)
        return None


def make_record(
    name,
    *,
    prompt="",
    llm=None,
    active=True,
    modes=None,
    reasoning_effort=None,
    embed_public_id=None,
    design=None,
    display_name=None,
):
    return ChatbotRegistryRecord(
        bot_name=name,
        display_name=display_name or name,
        active=active,
        created_at="2026-06-30T00:00:00+00:00",
        updated_at="2026-06-30T00:00:00+00:00",
        embed_public_id=embed_public_id,
        prompt=prompt,
        llm=llm,
        reasoning_effort=reasoning_effort,
        modes=modes if modes is not None else {},
        design=design if design is not None else {},
    )


def make_ctx(registry, prompt_store=None):
    quart_app = Quart(__name__)
    quart_app.config[CONFIG_CHATBOT_REGISTRY_STORE] = registry
    quart_app.config[CONFIG_CHATBOT_PROMPT_STORE] = prompt_store or FakePromptStore()
    quart_app.config[CONFIG_CHAT_MODEL_DEPLOYMENTS] = dict(DEPLOYED_MODELS)
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


# --- shipped example bot bootstrap -------------------------------------------------------


@pytest.mark.asyncio
async def test_example_dynamic_bot_is_seeded_once_and_is_idempotent():
    registry = FakeRegistry({})
    quart_app = make_ctx(registry)
    async with quart_app.app_context():
        await app_module.ensure_example_dynamic_bot_seeded()
        await app_module.ensure_example_dynamic_bot_seeded()

    assert registry.load_calls == ["example", "example"]
    assert len(registry.save_calls) == 1
    bot_name, fields = registry.save_calls[0]
    assert bot_name == "example"
    assert fields["display_name"] == "Example"
    assert fields["active"] is True
    assert fields["number_sessions"] == app_module.UNLIMITED_SESSIONS
    assert fields["modes"] == {"qa": True, "tutor": False, "assessment": False}
    assert fields["features"] == {"disclaimer": True, "history": True, "sources": False}
    assert fields["languages"] == ["English", "Deutsch", "Nederlands"]


@pytest.mark.asyncio
async def test_example_dynamic_bot_seed_skips_existing_record():
    registry = FakeRegistry({"example": make_record("example", active=True)})
    quart_app = make_ctx(registry)
    async with quart_app.app_context():
        await app_module.ensure_example_dynamic_bot_seeded()

    assert registry.load_calls == ["example"]
    assert registry.save_calls == []


@pytest.mark.asyncio
async def test_example_dynamic_bot_is_seeded_with_an_embed_public_id():
    registry = FakeRegistry({})
    quart_app = make_ctx(registry)
    async with quart_app.app_context():
        await app_module.ensure_example_dynamic_bot_seeded()

    _bot_name, fields = registry.save_calls[0]
    # Minted inline (never by listing the registry) so app startup performs no blob listing.
    assert PUBLIC_ID_RE.match(fields["embed_public_id"])
    assert fields["embed_public_id"] not in EMBED_PUBLIC_IDS.values()


# --- embed identity for dynamic bots ------------------------------------------------------
#
# A provisioned bot is embeddable by existing: its public ID is minted at create and stored on the
# record, so the /embed routes and the admin surfaces resolve through the registry. Built-in bots
# keep resolving from the committed map with no registry access at all (isolation invariant).


@pytest.fixture(autouse=True)
def clear_public_id_index():
    DYNAMIC_PUBLIC_ID_INDEX.by_public_id.clear()
    DYNAMIC_PUBLIC_ID_INDEX.last_refresh = None
    yield
    DYNAMIC_PUBLIC_ID_INDEX.by_public_id.clear()
    DYNAMIC_PUBLIC_ID_INDEX.last_refresh = None


@pytest.mark.asyncio
async def test_resolve_any_state_returns_stopped_bots_but_never_builtins():
    registry = FakeRegistry(
        {"bxa": make_record("bxa", active=False), "demo": make_record("demo", active=True)}
    )
    quart_app = make_ctx(registry)
    async with quart_app.app_context():
        stopped = await app_module.resolve_dynamic_record_any_state("bxa")
        assert stopped is not None and stopped.active is False
        assert await app_module.resolve_dynamic_record_any_state("ghost") is None
        # A built-in name must never resolve out of the registry, even if a record exists.
        assert await app_module.resolve_dynamic_record_any_state("demo") is None


@pytest.mark.asyncio
async def test_is_embeddable_chatbot_spans_both_worlds():
    registry = FakeRegistry({"bxa": make_record("bxa", active=True), "halted": make_record("halted", active=False)})
    quart_app = make_ctx(registry)
    async with quart_app.app_context():
        assert await app_module.is_embeddable_chatbot("publishone") is True  # built-in, committed ID
        assert await app_module.is_embeddable_chatbot("bxa") is True  # dynamic, active
        # Stopped bots count as embeddable so an admin can prepare the whitelist before starting.
        assert await app_module.is_embeddable_chatbot("halted") is True
        assert await app_module.is_embeddable_chatbot("ghost") is False
        # "internal" is a built-in router shell with no committed ID: it must NOT become embeddable
        # just because the registry is now consulted.
        assert await app_module.is_embeddable_chatbot("internal") is False


@pytest.mark.asyncio
async def test_servable_embed_target_resolves_builtin_without_registry_access():
    registry = FakeRegistry({})
    quart_app = make_ctx(registry)
    async with quart_app.app_context():
        name, record = await app_module.resolve_servable_embed_target(get_public_id("publishone"))
    assert (name, record) == ("publishone", None)
    assert registry.load_calls == []


@pytest.mark.asyncio
async def test_servable_embed_target_resolves_an_active_dynamic_bot():
    registry = FakeRegistry({"bxa": make_record("bxa", active=True, embed_public_id="dyn1234567")})
    quart_app = make_ctx(registry)
    async with quart_app.app_context():
        name, record = await app_module.resolve_servable_embed_target("dyn1234567")
    assert name == "bxa"
    assert record is not None and record.bot_name == "bxa"


@pytest.mark.asyncio
async def test_servable_embed_target_refuses_a_stopped_dynamic_bot():
    # The bot's own route redirects home when stopped; its live embeds must go dark the same way.
    registry = FakeRegistry({"bxa": make_record("bxa", active=False, embed_public_id="dyn1234567")})
    quart_app = make_ctx(registry)
    async with quart_app.app_context():
        assert await app_module.resolve_servable_embed_target("dyn1234567") == (None, None)


@pytest.mark.asyncio
async def test_servable_embed_target_refuses_unknown_and_malformed_ids():
    registry = FakeRegistry({"bxa": make_record("bxa", active=True, embed_public_id="dyn1234567")})
    quart_app = make_ctx(registry)
    async with quart_app.app_context():
        assert await app_module.resolve_servable_embed_target("zzz9999999") == (None, None)
        assert await app_module.resolve_servable_embed_target("not-a-real-id") == (None, None)


@pytest.mark.asyncio
async def test_launcher_colors_use_the_provisioned_primary():
    record = make_record("bxa", design={"color_primary": "#123456"})
    assert app_module.embed_launcher_colors("bxa", record) == ("#123456", None)
    # Blank/absent provisioned color falls back to the shared default.
    assert app_module.embed_launcher_colors("bxa", make_record("bxa", design={"color_primary": "  "})) == (
        app_module.EMBED_LAUNCHER_DEFAULT_COLOR,
        None,
    )
    assert app_module.embed_launcher_colors("bxa", make_record("bxa")) == (
        app_module.EMBED_LAUNCHER_DEFAULT_COLOR,
        None,
    )
    # Built-in bots keep their committed launcher colors, including the icon override.
    assert app_module.embed_launcher_colors("hyrox-assessment", None) == ("#000000", "#FFED00")


@pytest.mark.asyncio
async def test_embed_admin_public_id_backfills_a_legacy_dynamic_record():
    registry = FakeRegistry({"bxa": make_record("bxa", active=True, embed_public_id=None)})
    quart_app = make_ctx(registry)
    async with quart_app.app_context():
        public_id = await app_module.resolve_embed_admin_public_id("bxa")
    assert PUBLIC_ID_RE.match(public_id)
    # Persisted, not just returned, so the ID is stable across requests.
    assert registry.records["bxa"].embed_public_id == public_id
    assert len(registry.save_calls) == 1


@pytest.mark.asyncio
async def test_embed_admin_public_id_is_stable_and_never_rewrites():
    registry = FakeRegistry({"bxa": make_record("bxa", active=True, embed_public_id="dyn1234567")})
    quart_app = make_ctx(registry)
    async with quart_app.app_context():
        assert await app_module.resolve_embed_admin_public_id("bxa") == "dyn1234567"
        assert await app_module.resolve_embed_admin_public_id("publishone") == get_public_id("publishone")
        assert await app_module.resolve_embed_admin_public_id("ghost") is None
    assert registry.save_calls == []  # nothing to heal -> no write


# --- effective model / effort (shared by the chat path and the admin directory) ------------


@pytest.mark.asyncio
async def test_effective_model_honors_a_deployed_llm_and_falls_back_otherwise():
    assert app_module.resolve_dynamic_chat_model(make_record("bxa", llm="gpt-5"), DEPLOYED_MODELS) == "gpt-5"
    # Undeployed, empty, and tutor-mode cases resolve to the mode-aware defaults.
    assert (
        app_module.resolve_dynamic_chat_model(make_record("bxa", llm="nope"), DEPLOYED_MODELS)
        == DEFAULT_DYNAMIC_QNA_MODEL
    )
    assert (
        app_module.resolve_dynamic_chat_model(make_record("bxa", llm=None), DEPLOYED_MODELS)
        == DEFAULT_DYNAMIC_QNA_MODEL
    )
    assert (
        app_module.resolve_dynamic_chat_model(make_record("bxa", llm="nope", modes={"tutor": True}), DEPLOYED_MODELS)
        == DEFAULT_DYNAMIC_TUTOR_MODEL
    )
    assert app_module.resolve_dynamic_chat_model(make_record("bxa", llm="gpt-5"), {}) == DEFAULT_DYNAMIC_QNA_MODEL


@pytest.mark.asyncio
async def test_effective_reasoning_effort_matches_the_model_capability():
    reasoning_record = make_record("bxa", reasoning_effort="high")
    assert app_module.resolve_dynamic_reasoning_effort(reasoning_record, DEFAULT_DYNAMIC_TUTOR_MODEL) == "high"
    # An invalid provisioned effort falls back to medium; a non-reasoning model gets no effort at all.
    assert (
        app_module.resolve_dynamic_reasoning_effort(make_record("bxa", reasoning_effort="turbo"), DEFAULT_DYNAMIC_TUTOR_MODEL)
        == "medium"
    )
    assert app_module.resolve_dynamic_reasoning_effort(make_record("bxa"), DEFAULT_DYNAMIC_TUTOR_MODEL) == "medium"
    assert app_module.resolve_dynamic_reasoning_effort(reasoning_record, DEFAULT_DYNAMIC_QNA_MODEL) is None
    assert app_module.resolve_dynamic_reasoning_effort(reasoning_record, None) is None


def test_dynamic_chatbot_admin_payload_reports_effective_values():
    record = make_record(
        "bxa",
        display_name="ABX",
        active=False,
        llm="not-deployed",
        reasoning_effort="high",
        modes={"tutor": True},
        embed_public_id="dyn1234567",
    )
    payload = app_module.build_dynamic_chatbot_admin_payload(record, DEPLOYED_MODELS)
    assert payload["botName"] == "bxa"
    assert payload["displayName"] == "ABX"
    assert payload["active"] is False
    assert payload["publicId"] == "dyn1234567"
    assert payload["mode"] == "tutor-qna"
    # The directory must show what would really serve, not the undeployed provisioned model.
    assert payload["llm"] == DEFAULT_DYNAMIC_TUTOR_MODEL
    assert payload["reasoningEffort"] == "high"


# --- apply_saved_chatbot_prompt_override (dynamic branch) ---------------------------------


@pytest.mark.asyncio
async def test_dynamic_bot_injects_prompt_and_honors_deployed_model():
    registry = FakeRegistry({"bxa": make_record("bxa", prompt="CUSTOM PROMPT", llm="gpt-5", active=True)})
    quart_app = make_ctx(registry)
    async with quart_app.app_context():
        request_json = req("bxa")
        name = await app_module.apply_saved_chatbot_prompt_override(request_json)
    overrides = request_json["context"]["overrides"]
    assert name == "bxa"
    assert overrides["__saved_prompt_template"] == "CUSTOM PROMPT"
    assert overrides["chat_model"] == "gpt-5"  # deployed provisioned model is honored


@pytest.mark.asyncio
async def test_dynamic_qna_empty_llm_falls_back_to_qna_model():
    registry = FakeRegistry({"bxa": make_record("bxa", prompt="", llm=None, active=True)})
    quart_app = make_ctx(registry)
    async with quart_app.app_context():
        request_json = req("bxa")
        await app_module.apply_saved_chatbot_prompt_override(request_json)
    overrides = request_json["context"]["overrides"]
    assert overrides["__saved_prompt_template"] == app_module.DEFAULT_DYNAMIC_PROMPT
    assert overrides["chat_model"] == DEFAULT_DYNAMIC_QNA_MODEL  # empty llm -> qna default
    assert "reasoning_effort" not in overrides  # gpt-4.1 is non-reasoning; effort untouched


@pytest.mark.asyncio
async def test_dynamic_tutor_empty_llm_uses_tutor_prompt_model_and_medium_effort():
    registry = FakeRegistry(
        {"bxa": make_record("bxa", prompt="", llm=None, active=True, modes={"tutor": True})}
    )
    quart_app = make_ctx(registry)
    async with quart_app.app_context():
        request_json = req("bxa", reasoning_effort="")  # frontend sends empty by default
        await app_module.apply_saved_chatbot_prompt_override(request_json)
    overrides = request_json["context"]["overrides"]
    assert overrides["__saved_prompt_template"] == DEFAULT_DYNAMIC_TUTOR_PROMPT
    assert overrides["chat_model"] == DEFAULT_DYNAMIC_TUTOR_MODEL  # gpt-5.4-mini
    assert overrides["reasoning_effort"] == "medium"  # empty/invalid -> medium on a reasoning model


@pytest.mark.asyncio
async def test_dynamic_wrong_llm_falls_back_to_mode_default():
    registry = FakeRegistry({"bxa": make_record("bxa", prompt="P", llm="gpt-does-not-exist", active=True)})
    quart_app = make_ctx(registry)
    async with quart_app.app_context():
        request_json = req("bxa")
        await app_module.apply_saved_chatbot_prompt_override(request_json)
    # Undeployed model -> qna default (this bot is Q&A: no tutor mode).
    assert request_json["context"]["overrides"]["chat_model"] == DEFAULT_DYNAMIC_QNA_MODEL


@pytest.mark.asyncio
async def test_dynamic_tutor_valid_provisioned_effort_is_kept():
    registry = FakeRegistry(
        {"bxa": make_record("bxa", llm="gpt-5.4", active=True, modes={"tutor": True}, reasoning_effort="low")}
    )
    quart_app = make_ctx(registry)
    async with quart_app.app_context():
        request_json = req("bxa", reasoning_effort="")
        await app_module.apply_saved_chatbot_prompt_override(request_json)
    overrides = request_json["context"]["overrides"]
    assert overrides["chat_model"] == "gpt-5.4"  # valid deployed provisioned model honored
    assert overrides["reasoning_effort"] == "low"  # valid provisioned effort kept


@pytest.mark.asyncio
async def test_dynamic_tutor_invalid_provisioned_effort_defaults_medium():
    registry = FakeRegistry(
        {"bxa": make_record("bxa", llm="gpt-5.4", active=True, modes={"tutor": True}, reasoning_effort="bogus")}
    )
    quart_app = make_ctx(registry)
    async with quart_app.app_context():
        request_json = req("bxa", reasoning_effort="")
        await app_module.apply_saved_chatbot_prompt_override(request_json)
    assert request_json["context"]["overrides"]["reasoning_effort"] == "medium"


@pytest.mark.asyncio
async def test_dynamic_bot_respects_explicit_client_model():
    registry = FakeRegistry({"bxa": make_record("bxa", prompt="P", llm="gpt-5", active=True)})
    quart_app = make_ctx(registry)
    async with quart_app.app_context():
        request_json = req("bxa", chat_model="gpt-5.4")
        await app_module.apply_saved_chatbot_prompt_override(request_json)
    # An explicit non-empty client-selected model is respected over the provisioned/default one.
    assert request_json["context"]["overrides"]["chat_model"] == "gpt-5.4"


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
