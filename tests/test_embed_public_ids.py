import re

from approaches.chatbot_prompt_registry import get_registered_chatbot_names
from embed_public_ids import (
    EMBED_PUBLIC_IDS,
    PUBLIC_ID_LENGTH,
    generate_public_id,
    get_public_id,
    is_embeddable,
    resolve_public_id,
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
