"""Tests for the dynamic bot-config mapping helpers and the GET /bot-config/<name> handler.

Covers: language label->code mapping, mode derivation, the public payload builder (no prompt/internals
leaked), and the route handler returning 200 for an active dynamic bot and 404 for unknown/inactive/
built-in names (isolation).
"""

import pytest
from quart import Quart
from werkzeug.exceptions import HTTPException

import app as app_module
from config import CONFIG_CHATBOT_REGISTRY_STORE
from core.chatbotregistrystore import ChatbotRegistryRecord
from core.dynamic_bot_config import (
    build_bot_config_payload,
    derive_chatbot_mode,
    language_label_to_code,
    map_language_keyed,
    map_language_list,
)


def make_record(name="bxa", **overrides):
    base = dict(
        bot_name=name,
        display_name="ABX",
        active=True,
        created_at="2026-06-30T00:00:00+00:00",
        updated_at="2026-06-30T00:00:00+00:00",
        prompt="SECRET PROMPT",
        llm="gpt-5",
        modes={"qa": True, "tutor": True, "assessment": False},
        design={"color_primary": "#AC44C6", "color_secondary": "#00cc96"},
        languages=["Deutsch"],
        greeting={"Deutsch": "Willkommen!"},
        disclaimer={"Deutsch": "KI-Assistent."},
        features={"disclaimer": True, "history": True, "sources": False},
        login={"required": False, "provider": "email"},
    )
    base.update(overrides)
    return ChatbotRegistryRecord(**base)


# --- mapping helpers ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "label,expected",
    [("Deutsch", "de"), ("german", "de"), ("DE", "de"), ("English", "en"), ("Nederlands", "nl"),
     ("Dutch", "nl"), ("Klingon", None), ("", None), (None, None), (123, None)],
)
def test_language_label_to_code(label, expected):
    assert language_label_to_code(label) == expected


def test_map_language_list_dedupes_and_drops_unknown():
    assert map_language_list(["Deutsch", "de", "English", "Klingon"]) == ["de", "en"]
    assert map_language_list("not a list") == []
    assert map_language_list([]) == []


def test_map_language_keyed_rekeys_to_codes():
    assert map_language_keyed({"Deutsch": "Hallo", "English": "Hi", "Klingon": "nuqneH"}) == {
        "de": "Hallo",
        "en": "Hi",
    }
    assert map_language_keyed({"Deutsch": 123}) == {}  # non-str values dropped
    assert map_language_keyed("nope") == {}


@pytest.mark.parametrize(
    "modes,expected",
    [({"qa": True, "tutor": True}, "tutor-qna"), ({"qa": True, "tutor": False}, "qna"),
     ({"tutor": True}, "tutor-qna"), ({}, "qna"), (None, "qna")],
)
def test_derive_chatbot_mode(modes, expected):
    assert derive_chatbot_mode(modes) == expected


# --- payload builder ----------------------------------------------------------------------


def test_build_bot_config_payload_shape():
    payload = build_bot_config_payload(make_record())
    assert payload == {
        "botName": "bxa",
        "displayName": "ABX",
        "mode": "tutor-qna",
        "llm": "gpt-5",
        "primaryColor": "#AC44C6",
        "logo": None,
        "icon": None,
        "languages": ["de"],
        "defaultLanguage": "de",
        "greeting": {"de": "Willkommen!"},
        "disclaimer": {"de": "KI-Assistent."},
        "features": {"disclaimer": True, "history": True, "sources": False},
        "login": {"required": False, "provider": "email"},
    }


def test_build_bot_config_payload_exposes_logo_and_icon():
    # The control panel sends brand images as base64 data URIs inside `design`; they ride out to the
    # frontend verbatim (logo -> header, icon -> assistant avatar).
    logo = "data:image/png;base64,AAAAlogo=="
    icon = "data:image/png;base64,AAAAicon=="
    payload = build_bot_config_payload(
        make_record(design={"color_primary": "#AC44C6", "logo": logo, "icon": icon})
    )
    assert payload["logo"] == logo
    assert payload["icon"] == icon
    assert payload["primaryColor"] == "#AC44C6"


@pytest.mark.parametrize("blank", ["", "   ", None, 123, {}])
def test_build_bot_config_payload_blank_logo_icon_become_none(blank):
    payload = build_bot_config_payload(make_record(design={"logo": blank, "icon": blank}))
    assert payload["logo"] is None
    assert payload["icon"] is None


def test_build_bot_config_payload_passes_speech_features_verbatim():
    # The granular speech toggles ride along inside `features` and must reach the frontend unchanged.
    features = {
        "disclaimer": True,
        "sources": False,
        "speech_input": True,
        "speech_output_browser": False,
        "speech_output_azure": True,
    }
    payload = build_bot_config_payload(make_record(features=features))
    assert payload["features"] == features


def test_build_bot_config_payload_never_leaks_prompt_or_internals():
    payload = build_bot_config_payload(make_record())
    assert "prompt" not in payload
    assert "SECRET PROMPT" not in str(payload)
    assert "number_sessions" not in payload and "numberSessions" not in payload


def test_build_bot_config_payload_defaults_language_when_none_supported():
    payload = build_bot_config_payload(make_record(languages=["Klingon"], greeting={}))
    assert payload["languages"] == ["de"]
    assert payload["defaultLanguage"] == "de"


# --- route handler ------------------------------------------------------------------------


class FakeRegistry:
    def __init__(self, records=None):
        self.records = records or {}

    async def load_record(self, name):
        from approaches.chatbot_prompt_registry import normalize_chatbot_name

        return self.records.get(normalize_chatbot_name(name))


def make_ctx(records):
    quart_app = Quart(__name__)
    quart_app.config[CONFIG_CHATBOT_REGISTRY_STORE] = FakeRegistry(records)
    return quart_app


@pytest.mark.asyncio
async def test_bot_config_route_returns_payload_for_active_dynamic_bot():
    quart_app = make_ctx({"bxa": make_record("bxa", active=True)})
    async with quart_app.app_context():
        response = await app_module.bot_config("bxa")
        body = await response.get_json()
    assert body["botName"] == "bxa"
    assert body["primaryColor"] == "#AC44C6"
    assert body["mode"] == "tutor-qna"


@pytest.mark.asyncio
@pytest.mark.parametrize("name,records", [("ghost", {}), ("bxa", {"bxa": "INACTIVE"}), ("demo", {})])
async def test_bot_config_route_404s_for_unknown_inactive_or_builtin(name, records):
    if records.get("bxa") == "INACTIVE":
        records = {"bxa": make_record("bxa", active=False)}
    quart_app = make_ctx(records)
    async with quart_app.app_context():
        with pytest.raises(HTTPException) as exc:
            await app_module.bot_config(name)
    assert exc.value.code == 404
