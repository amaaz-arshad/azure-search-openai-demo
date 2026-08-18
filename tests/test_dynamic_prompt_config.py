"""Tests for dynamic-bot `ansprache` (formal/informal) wiring into the system prompt.

`ansprache` is a structured control-panel field that, unlike the prompt text, was stored but never
applied. These cover the pure helpers and the integration through apply_saved_chatbot_prompt_override.
"""

import pytest
from quart import Quart

import app as app_module
from approaches.chatbot_prompt_registry import normalize_chatbot_name
from config import CONFIG_CHATBOT_PROMPT_STORE, CONFIG_CHATBOT_REGISTRY_STORE
from core.chatbotregistrystore import ChatbotRegistryRecord
from core.dynamic_bot_config import (
    FORMAL_ANSPRACHE_DIRECTIVE,
    INFORMAL_ANSPRACHE_DIRECTIVE,
    ansprache_directive,
    build_dynamic_system_prompt,
)
from core.dynamic_tutor_prompt import DEFAULT_DYNAMIC_TUTOR_PROMPT


def make_record(name="bxa", *, prompt="", ansprache=None, active=True, modes=None):
    return ChatbotRegistryRecord(
        bot_name=name,
        display_name=name,
        active=active,
        created_at="2026-06-30T00:00:00+00:00",
        updated_at="2026-06-30T00:00:00+00:00",
        prompt=prompt,
        ansprache=ansprache,
        modes=modes if modes is not None else {},
    )


# --- pure helpers -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("informal", INFORMAL_ANSPRACHE_DIRECTIVE),
        ("du", INFORMAL_ANSPRACHE_DIRECTIVE),
        ("formal", FORMAL_ANSPRACHE_DIRECTIVE),
        ("Sie", FORMAL_ANSPRACHE_DIRECTIVE),  # case-insensitive
        ("  Formal  ", FORMAL_ANSPRACHE_DIRECTIVE),  # trimmed
        ("", None),
        (None, None),
        ("polite", None),  # unknown value
    ],
)
def test_ansprache_directive(value, expected):
    assert ansprache_directive(value) == expected


@pytest.mark.parametrize("directive", [INFORMAL_ANSPRACHE_DIRECTIVE, FORMAL_ANSPRACHE_DIRECTIVE])
def test_ansprache_directives_are_language_general(directive):
    # The directive must hold whatever language the answer is in: explicit German and Dutch forms,
    # a generic rule for other T-V languages, and a tone rule for languages without the distinction.
    assert "German" in directive
    assert "Dutch" in directive
    assert "any other" in directive
    assert "English" in directive
    assert "tone" in directive


def test_build_appends_directive_to_custom_prompt():
    prompt = build_dynamic_system_prompt(make_record(prompt="BASE PROMPT", ansprache="informal"), "DEFAULT")
    assert prompt == f"BASE PROMPT\n\n{INFORMAL_ANSPRACHE_DIRECTIVE}"


def test_build_uses_default_when_prompt_empty_then_appends():
    prompt = build_dynamic_system_prompt(make_record(prompt="", ansprache="formal"), "DEFAULT")
    assert prompt == f"DEFAULT\n\n{FORMAL_ANSPRACHE_DIRECTIVE}"


def test_build_leaves_prompt_unchanged_when_ansprache_unset():
    assert build_dynamic_system_prompt(make_record(prompt="BASE", ansprache=None), "DEFAULT") == "BASE"


def test_build_whitespace_prompt_falls_back_to_default():
    assert build_dynamic_system_prompt(make_record(prompt="   ", ansprache=None), "DEFAULT") == "DEFAULT"


# --- mode-aware default selection ---------------------------------------------------------


def test_build_tutor_mode_empty_prompt_uses_tutor_default():
    # A tutor bot with no custom prompt gets the generic tutor prompt, not the neutral Q&A default.
    record = make_record(prompt="", modes={"qa": True, "tutor": True})
    prompt = build_dynamic_system_prompt(record, "QNA_DEFAULT")
    assert prompt == DEFAULT_DYNAMIC_TUTOR_PROMPT
    # Sanity: the tutor default really is the working tutor prompt (Start-Gate + counter mechanics).
    assert "TUTOR START GATE" in prompt and "Frage {{N}} von {{Total}}" in prompt


def test_build_qna_mode_empty_prompt_uses_passed_default():
    record = make_record(prompt="", modes={"qa": True, "tutor": False})
    assert build_dynamic_system_prompt(record, "QNA_DEFAULT") == "QNA_DEFAULT"


def test_build_custom_prompt_overrides_tutor_default():
    # An explicit custom prompt always wins, even for a tutor bot.
    record = make_record(prompt="MY CUSTOM", modes={"tutor": True})
    assert build_dynamic_system_prompt(record, "QNA_DEFAULT") == "MY CUSTOM"


def test_build_tutor_default_appends_ansprache():
    record = make_record(prompt="", ansprache="formal", modes={"tutor": True})
    prompt = build_dynamic_system_prompt(record, "QNA_DEFAULT")
    assert prompt == f"{DEFAULT_DYNAMIC_TUTOR_PROMPT}\n\n{FORMAL_ANSPRACHE_DIRECTIVE}"


# --- integration through the injection path -----------------------------------------------


class FakeRegistry:
    def __init__(self, records):
        self.records = records

    async def load_record(self, name):
        return self.records.get(normalize_chatbot_name(name))


class FakePromptStore:
    async def load_prompt(self, name):
        return None


@pytest.mark.asyncio
async def test_apply_saved_appends_ansprache_for_dynamic_bot():
    registry = FakeRegistry({"bxa": make_record(prompt="BASE", ansprache="formal", active=True)})
    quart_app = Quart(__name__)
    quart_app.config[CONFIG_CHATBOT_REGISTRY_STORE] = registry
    quart_app.config[CONFIG_CHATBOT_PROMPT_STORE] = FakePromptStore()
    request_json = {"context": {"overrides": {"include_category": "bxa"}}}
    async with quart_app.app_context():
        await app_module.apply_saved_chatbot_prompt_override(request_json)
    assert request_json["context"]["overrides"]["__saved_prompt_template"] == f"BASE\n\n{FORMAL_ANSPRACHE_DIRECTIVE}"


@pytest.mark.asyncio
async def test_apply_saved_empty_prompt_no_ansprache_still_default():
    # Guards the existing contract: empty prompt + no ansprache → exactly DEFAULT_DYNAMIC_PROMPT.
    registry = FakeRegistry({"bxa": make_record(prompt="", ansprache=None, active=True)})
    quart_app = Quart(__name__)
    quart_app.config[CONFIG_CHATBOT_REGISTRY_STORE] = registry
    quart_app.config[CONFIG_CHATBOT_PROMPT_STORE] = FakePromptStore()
    request_json = {"context": {"overrides": {"include_category": "bxa"}}}
    async with quart_app.app_context():
        await app_module.apply_saved_chatbot_prompt_override(request_json)
    assert request_json["context"]["overrides"]["__saved_prompt_template"] == app_module.DEFAULT_DYNAMIC_PROMPT


def test_both_dynamic_prompts_carry_every_citation_guard() -> None:
    # A provisioned bot is cited per document, so one turn can show the model a page URL and a
    # filename as source labels. Both failure modes these guards forbid shipped to production on
    # `snap`, which is likewise URL-cited: a URL remembered from an earlier turn pasted into a
    # bracket, and a source label written as a markdown link so the bracket validated while the raw
    # URL leaked into the visible answer. The tutor prompt spells the guards out as markdown bullets,
    # so this is what stops the two prompts from drifting apart.
    from core.dynamic_tutor_prompt import DEFAULT_DYNAMIC_TUTOR_PROMPT, DYNAMIC_CITATION_GUARDS

    import app

    assert DYNAMIC_CITATION_GUARDS
    for guard in DYNAMIC_CITATION_GUARDS:
        assert guard in DEFAULT_DYNAMIC_TUTOR_PROMPT
        assert guard in app.DEFAULT_DYNAMIC_PROMPT

    # Both still substitute the citation list the backend injects per turn.
    assert "{{POSSIBLE_CITATIONS_PROMPT}}" in DEFAULT_DYNAMIC_TUTOR_PROMPT
    assert "{{POSSIBLE_CITATIONS_PROMPT}}" in app.DEFAULT_DYNAMIC_PROMPT
