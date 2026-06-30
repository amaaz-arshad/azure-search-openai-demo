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


def make_record(name="bxa", *, prompt="", ansprache=None, active=True):
    return ChatbotRegistryRecord(
        bot_name=name,
        display_name=name,
        active=active,
        created_at="2026-06-30T00:00:00+00:00",
        updated_at="2026-06-30T00:00:00+00:00",
        prompt=prompt,
        ansprache=ansprache,
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
