import re
from dataclasses import dataclass
from typing import Optional

import pytest

from approaches.chatbot_prompt_registry import get_registered_chatbot_names
from embed_public_ids import (
    EMBED_PUBLIC_IDS,
    PUBLIC_ID_LENGTH,
    DynamicPublicIdIndex,
    build_embed_snippet,
    generate_public_id,
    get_public_id,
    get_record_public_id,
    is_embeddable,
    looks_like_public_id,
    mint_public_id,
    resolve_public_id,
    resolve_public_id_async,
)


def test_every_registered_chatbot_has_a_public_id():
    # Each embeddable bot (one with a prompt module) must have a committed public ID.
    assert set(get_registered_chatbot_names()) == set(EMBED_PUBLIC_IDS)


def test_public_ids_are_unique_and_opaque():
    ids = list(EMBED_PUBLIC_IDS.values())
    assert len(set(ids)) == len(ids)
    for public_id, name in ((pid, n) for n, pid in EMBED_PUBLIC_IDS.items()):
        assert re.fullmatch(r"[a-z][a-z0-9]{9}", public_id), public_id
        assert name not in public_id  # must not leak the readable name


def test_round_trip_resolution():
    public_id = get_public_id("publishone")
    assert public_id is not None
    assert resolve_public_id(public_id) == "publishone"


def test_alias_public_test_maps_to_free():
    assert get_public_id("public-test") == get_public_id("free")


def test_non_embeddable_bots_have_no_id():
    assert get_public_id("internal") is None
    assert is_embeddable("internal") is False
    assert resolve_public_id("does-not-exist") is None


def test_generate_public_id_shape_and_uniqueness():
    generated = generate_public_id()
    assert re.fullmatch(r"[a-z][a-z0-9]{%d}" % (PUBLIC_ID_LENGTH - 1), generated)
    assert generated not in EMBED_PUBLIC_IDS.values()


# --- dynamic (provisioned) bots ------------------------------------------------------------
#
# Their IDs are minted at create time and stored on the registry record instead of the committed
# map above, so resolution has to consult the registry — while built-in resolution stays I/O-free.


@dataclass
class FakeRecord:
    bot_name: str
    embed_public_id: Optional[str] = None


class FakeRegistryStore:
    def __init__(self, records=None):
        self.records = {record.bot_name: record for record in (records or [])}
        self.list_calls = 0

    async def list_records(self):
        self.list_calls += 1
        return dict(self.records)


@pytest.fixture
def index():
    # A fresh index per test: the production one is a module-level cache.
    return DynamicPublicIdIndex(min_refresh_interval=0.0)


def test_looks_like_public_id_matches_only_minted_shape():
    assert looks_like_public_id("hzda0mvocb") is True
    assert looks_like_public_id("  hzda0mvocb  ") is True  # trimmed
    assert looks_like_public_id("not-a-real-id") is False  # hyphens
    assert looks_like_public_id("0zda0mvocb") is False  # must start with a letter
    assert looks_like_public_id("short") is False
    assert looks_like_public_id("hzda0mvocbXX") is False
    assert looks_like_public_id(None) is False
    assert looks_like_public_id("") is False


def test_build_embed_snippet_uses_the_public_id_and_never_the_name():
    snippet = build_embed_snippet("https://chat.nerilio.ai/", "abc1234567")
    assert snippet == '<script async src="https://chat.nerilio.ai/widget.js" data-chatbot-id="abc1234567"></script>'


def test_generate_public_id_avoids_already_taken_dynamic_ids():
    # Exhaust the space down to one free ID to prove `taken` is honored, not just the built-in map.
    alphabet_ids = {f"a{'0' * 8}{char}" for char in "0123456789"}
    free_id = "a000000009"
    taken = alphabet_ids - {free_id}
    # Deterministic only because generate_public_id retries until it finds an ID outside `taken`;
    # this asserts the retry, not the randomness.
    for _ in range(50):
        assert generate_public_id(taken) not in taken


def test_get_record_public_id_treats_blank_as_unminted():
    assert get_record_public_id(FakeRecord("bxa", "abc1234567")) == "abc1234567"
    assert get_record_public_id(FakeRecord("bxa", "")) is None
    assert get_record_public_id(FakeRecord("bxa", None)) is None
    assert get_record_public_id(None) is None


@pytest.mark.asyncio
async def test_builtin_ids_resolve_without_touching_the_registry():
    store = FakeRegistryStore()
    assert await resolve_public_id_async(get_public_id("publishone"), store) == "publishone"
    assert store.list_calls == 0


@pytest.mark.asyncio
async def test_malformed_ids_are_rejected_before_any_registry_lookup():
    # The shape gate is what stops a flood of probe requests from becoming a flood of blob listings.
    store = FakeRegistryStore([FakeRecord("bxa", "abc1234567")])
    assert await resolve_public_id_async("not-a-real-id", store) is None
    assert await resolve_public_id_async("", store) is None
    assert await resolve_public_id_async(None, store) is None
    assert store.list_calls == 0


@pytest.mark.asyncio
async def test_dynamic_id_resolves_from_the_registry(index):
    store = FakeRegistryStore([FakeRecord("bxa", "abc1234567")])
    assert await index.resolve("abc1234567", store) == "bxa"
    assert store.list_calls == 1
    # Second lookup is served from the index.
    assert await index.resolve("abc1234567", store) == "bxa"
    assert store.list_calls == 1


@pytest.mark.asyncio
async def test_unknown_but_well_formed_id_returns_none_after_a_refresh(index):
    store = FakeRegistryStore([FakeRecord("bxa", "abc1234567")])
    assert await index.resolve("zzz9999999", store) is None
    assert store.list_calls == 1


@pytest.mark.asyncio
async def test_index_refresh_is_rate_limited():
    index = DynamicPublicIdIndex(min_refresh_interval=3600.0)
    store = FakeRegistryStore([FakeRecord("bxa", "abc1234567")])
    assert await index.resolve("zzz9999999", store) is None
    assert store.list_calls == 1
    # Within the interval a miss must not trigger another listing.
    assert await index.resolve("yyy8888888", store) is None
    assert store.list_calls == 1


@pytest.mark.asyncio
async def test_remembered_id_resolves_with_no_listing_at_all():
    index = DynamicPublicIdIndex(min_refresh_interval=3600.0)
    store = FakeRegistryStore()
    index.remember("abc1234567", "bxa")
    assert await index.resolve("abc1234567", store) == "bxa"
    assert store.list_calls == 0


@pytest.mark.asyncio
async def test_forget_bot_drops_every_id_for_that_bot(index):
    store = FakeRegistryStore()
    index.remember("abc1234567", "bxa")
    index.remember("def1234567", "other")
    index.forget_bot("bxa")
    # Only the deleted bot's entry goes; the others stay cached (a later refresh rebuilds the whole
    # map from the registry, which is why this is checked before any resolve).
    assert index.by_public_id == {"def1234567": "other"}
    assert await index.resolve("abc1234567", store) is None


@pytest.mark.asyncio
async def test_index_refresh_failure_is_swallowed(index):
    class ExplodingStore:
        async def list_records(self):
            raise RuntimeError("blob storage is down")

    # A registry outage must not 500 the public widget/iframe path.
    assert await index.resolve("abc1234567", ExplodingStore()) is None


@pytest.mark.asyncio
async def test_resolve_public_id_async_without_a_store_only_sees_builtins():
    assert await resolve_public_id_async(get_public_id("lemon"), None) == "lemon"
    assert await resolve_public_id_async("abc1234567", None) is None


@pytest.mark.asyncio
async def test_mint_public_id_avoids_builtin_and_dynamic_ids():
    store = FakeRegistryStore([FakeRecord("bxa", "abc1234567"), FakeRecord("other", None)])
    minted = await mint_public_id(store)
    assert re.fullmatch(r"[a-z][a-z0-9]{%d}" % (PUBLIC_ID_LENGTH - 1), minted)
    assert minted != "abc1234567"
    assert minted not in EMBED_PUBLIC_IDS.values()


@pytest.mark.asyncio
async def test_mint_public_id_still_returns_an_id_when_the_registry_is_unreachable():
    class ExplodingStore:
        async def list_records(self):
            raise RuntimeError("blob storage is down")

    # A create must not fail because the collision scan could not run.
    minted = await mint_public_id(ExplodingStore())
    assert re.fullmatch(r"[a-z][a-z0-9]{%d}" % (PUBLIC_ID_LENGTH - 1), minted)
