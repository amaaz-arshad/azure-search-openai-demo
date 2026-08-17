"""TURN credential fetching for the real-time text-to-speech avatar.

Like test_hubspot.py these run the real aiohttp request path against a throwaway localhost server
rather than mocking ClientSession, so the auth header and the status handling are genuinely
covered. The host/path construction is tested separately because it is the part that silently
breaks Entra ID auth: the regional *.tts.speech.microsoft.com host accepts only a subscription
key, so the custom-subdomain form (with its extra /tts segment) is the only one usable here.
"""

from contextlib import asynccontextmanager

import pytest
from aiohttp import web

from core.speechavatar import (
    RELAY_TOKEN_PATH,
    build_relay_token_url,
    fetch_ice_servers_from_url,
    select_turn_ice_servers,
    speech_account_name_from_resource_id,
)

RESOURCE_ID = (
    "/subscriptions/0000/resourceGroups/rg-demo/providers/Microsoft.CognitiveServices/accounts/cog-speech-demo"
)


@asynccontextmanager
async def fake_relay(handler):
    """Serve `handler` at the relay path and yield its URL."""
    app = web.Application()
    app.router.add_get(RELAY_TOKEN_PATH, handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    try:
        port = runner.addresses[0][1]
        yield f"http://127.0.0.1:{port}{RELAY_TOKEN_PATH}"
    finally:
        await runner.cleanup()


def test_the_account_name_is_the_last_segment_of_the_resource_id():
    assert speech_account_name_from_resource_id(RESOURCE_ID) == "cog-speech-demo"
    assert speech_account_name_from_resource_id(RESOURCE_ID + "/") == "cog-speech-demo"


def test_the_relay_url_uses_the_custom_subdomain_host_and_the_tts_path():
    """Entra ID auth requires the custom subdomain, and that host puts the endpoint under /tts.

    Building the regional host here instead would still return 200 with a subscription key and
    then fail with 401 in production, where the app authenticates with its managed identity.
    """
    url = build_relay_token_url(RESOURCE_ID)

    assert url == "https://cog-speech-demo.cognitiveservices.azure.com/tts/cognitiveservices/avatar/relay/token/v1"
    assert "tts.speech.microsoft.com" not in url


def test_an_empty_resource_id_is_rejected_rather_than_building_a_nonsense_host():
    with pytest.raises(ValueError):
        build_relay_token_url("")


def test_only_turn_urls_are_kept():
    """A stun: entry alongside the turn: one makes the browser try a path the avatar service does
    not accept, so the connection stalls in ICE gathering instead of failing fast."""
    ice_servers = select_turn_ice_servers(
        {
            "Urls": ["stun:relay.communication.microsoft.com:3478", "turn:relay.communication.microsoft.com:3478"],
            "Username": "user",
            "Password": "secret",
        }
    )

    assert ice_servers == [
        {
            "urls": ["turn:relay.communication.microsoft.com:3478"],
            "username": "user",
            "credential": "secret",
        }
    ]


def test_a_response_without_a_turn_url_raises():
    with pytest.raises(ValueError):
        select_turn_ice_servers({"Urls": ["stun:relay.communication.microsoft.com:3478"], "Username": "u", "Password": "p"})

    with pytest.raises(ValueError):
        select_turn_ice_servers({})


@pytest.mark.asyncio
async def test_the_bearer_token_is_sent_and_the_credentials_come_back_shaped_for_webrtc():
    seen = {}

    async def handler(request):
        seen["authorization"] = request.headers.get("Authorization")
        return web.json_response(
            {
                "Urls": ["turn:relay.communication.microsoft.com:3478"],
                "Username": "relay-user",
                "Password": "relay-secret",
            }
        )

    async with fake_relay(handler) as url:
        ice_servers = await fetch_ice_servers_from_url(relay_url=url, bearer_token="token-123")

    assert seen["authorization"] == "Bearer token-123"
    assert ice_servers == [
        {
            "urls": ["turn:relay.communication.microsoft.com:3478"],
            "username": "relay-user",
            "credential": "relay-secret",
        }
    ]


@pytest.mark.asyncio
async def test_a_non_200_relay_response_raises_instead_of_returning_empty_ice_servers():
    """Returning [] here would hand the browser a peer connection with no relay, which fails much
    later and much less legibly than a 500 from /speech/avatar-token."""

    async def handler(request):
        return web.Response(status=403, text="Forbidden")

    async with fake_relay(handler) as url:
        with pytest.raises(RuntimeError):
            await fetch_ice_servers_from_url(relay_url=url, bearer_token="token-123")
