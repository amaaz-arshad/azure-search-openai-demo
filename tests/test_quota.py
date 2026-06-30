"""Tests for the number_sessions quota enforcement (Phase 2).

Covers the quota branch of `enforce_dynamic_chatbot_gate` (admit/block a new session against the
cumulative per-bot cap) and the pure helpers of the ETag-backed `ChatbotSessionCounterStore`.

ISOLATION INVARIANT under test: unlimited (-1) dynamic bots and built-in bots never touch the
session counter store.
"""

from unittest import mock

import pytest
from quart import Quart

from config import CONFIG_CHATBOT_REGISTRY_STORE, CONFIG_CHATBOT_SESSION_COUNTER_STORE
from core.chatbotregistrystore import UNLIMITED_SESSIONS, ChatbotRegistryRecord
from core.chatbotsessioncounterstore import ChatbotSessionCounterStore

import app as app_module
from approaches.chatbot_prompt_registry import normalize_chatbot_name


class FakeRegistry:
    def __init__(self, records=None):
        self.records = records or {}

    async def load_record(self, name):
        return self.records.get(normalize_chatbot_name(name))


class FakeCounter:
    def __init__(self, start=0):
        self.count = start
        self.increment_calls = 0
        self.get_calls = 0

    async def get_count(self, name):
        self.get_calls += 1
        return self.count

    async def increment(self, name):
        self.increment_calls += 1
        self.count += 1
        return self.count


class ExplodingCounter:
    """Asserts the counter is never consulted (unlimited / built-in paths)."""

    async def get_count(self, name):
        raise AssertionError("counter store must not be consulted")

    async def increment(self, name):
        raise AssertionError("counter store must not be consulted")


def make_record(name, *, number_sessions=UNLIMITED_SESSIONS, active=True):
    return ChatbotRegistryRecord(
        bot_name=name,
        display_name=name,
        active=active,
        created_at="2026-06-30T00:00:00+00:00",
        updated_at="2026-06-30T00:00:00+00:00",
        number_sessions=number_sessions,
    )


def make_ctx(registry, counter):
    quart_app = Quart(__name__)
    quart_app.config[CONFIG_CHATBOT_REGISTRY_STORE] = registry
    quart_app.config[CONFIG_CHATBOT_SESSION_COUNTER_STORE] = counter
    return quart_app


# --- gate quota branch --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_session_under_cap_is_admitted_and_counted():
    registry = FakeRegistry({"bxa": make_record("bxa", number_sessions=30)})
    counter = FakeCounter(start=10)
    quart_app = make_ctx(registry, counter)
    async with quart_app.app_context():
        gate = await app_module.enforce_dynamic_chatbot_gate("bxa", is_new_session=True)
    assert gate is None
    assert counter.increment_calls == 1  # the new session was counted


@pytest.mark.asyncio
async def test_new_session_at_cap_is_blocked_and_not_counted():
    registry = FakeRegistry({"bxa": make_record("bxa", number_sessions=30)})
    counter = FakeCounter(start=30)
    quart_app = make_ctx(registry, counter)
    async with quart_app.app_context():
        gate = await app_module.enforce_dynamic_chatbot_gate("bxa", is_new_session=True)
        assert gate is not None
        response, status = gate
        assert status == 403
        body = await response.get_json()
    assert body["error"] == "quota_exceeded"
    assert body["chatbotName"] == "bxa"
    assert body["limit"] == 30
    assert counter.increment_calls == 0  # a blocked session must not consume quota


@pytest.mark.asyncio
async def test_continuing_session_is_never_quota_blocked():
    # is_new_session=False: an in-progress chat is never cut off, even if the bot is over cap.
    registry = FakeRegistry({"bxa": make_record("bxa", number_sessions=30)})
    counter = FakeCounter(start=999)
    quart_app = make_ctx(registry, counter)
    async with quart_app.app_context():
        gate = await app_module.enforce_dynamic_chatbot_gate("bxa", is_new_session=False)
    assert gate is None
    assert counter.get_calls == 0 and counter.increment_calls == 0


@pytest.mark.asyncio
async def test_unlimited_bot_never_touches_counter():
    registry = FakeRegistry({"bxa": make_record("bxa", number_sessions=UNLIMITED_SESSIONS)})
    quart_app = make_ctx(registry, ExplodingCounter())
    async with quart_app.app_context():
        assert await app_module.enforce_dynamic_chatbot_gate("bxa", is_new_session=True) is None


@pytest.mark.asyncio
async def test_stopped_bot_blocks_before_quota():
    registry = FakeRegistry({"bxa": make_record("bxa", number_sessions=30, active=False)})
    quart_app = make_ctx(registry, ExplodingCounter())
    async with quart_app.app_context():
        gate = await app_module.enforce_dynamic_chatbot_gate("bxa", is_new_session=True)
        assert gate is not None
        _response, status = gate
    assert status == 403  # chatbot_inactive wins; counter never consulted


@pytest.mark.asyncio
async def test_builtin_never_touches_either_store():
    registry = FakeRegistry({"demo": make_record("demo", number_sessions=1, active=False)})
    quart_app = make_ctx(registry, ExplodingCounter())
    async with quart_app.app_context():
        assert await app_module.enforce_dynamic_chatbot_gate("demo", is_new_session=True) is None


# --- ChatbotSessionCounterStore pure helpers ----------------------------------------------


def test_parse_count_variants():
    store = ChatbotSessionCounterStore(blob_manager=mock.Mock())
    assert store.parse_count(b'{"count": 5}') == 5
    assert store.parse_count(b'{"count": 0}') == 0
    assert store.parse_count(b'{"count": -3}') == 0  # negative coerced to 0
    assert store.parse_count(b"{}") == 0
    assert store.parse_count(b"not json") == 0


def test_serialize_round_trips_count():
    import json

    store = ChatbotSessionCounterStore(blob_manager=mock.Mock())
    raw = store.serialize("bxa", 7).getvalue()
    payload = json.loads(raw.decode("utf-8"))
    assert payload["chatbotName"] == "bxa"
    assert payload["count"] == 7
    assert store.parse_count(raw) == 7
