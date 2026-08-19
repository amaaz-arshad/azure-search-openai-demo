"""Helpers for the Azure AI Speech real-time text-to-speech avatar.

The avatar runs in the browser over WebRTC. Establishing that peer connection needs TURN
credentials ("ICE servers"), which are issued by the Speech resource's avatar relay endpoint.
The browser must never call that endpoint itself: it is authenticated, and doing so would mean
shipping a Speech key (or a bearer token scoped to the whole Cognitive Services resource) into
page JavaScript. So the backend fetches the credentials and hands the browser only the short-lived
TURN username/password.

Two hosts serve the relay endpoint and they are NOT interchangeable:

* ``https://<region>.tts.speech.microsoft.com/cognitiveservices/avatar/relay/token/v1``
  accepts only ``Ocp-Apim-Subscription-Key`` (key auth).
* ``https://<custom-subdomain>.cognitiveservices.azure.com/tts/cognitiveservices/avatar/relay/token/v1``
  accepts Entra ID ``Authorization: Bearer`` — note the extra ``/tts`` path segment.

This app authenticates to Speech with its managed identity (see ``get_speech_service_token``), and
Entra ID auth for Cognitive Services requires the custom subdomain, so the second form is the only
one usable here. ``infra/main.bicep`` sets ``customSubDomainName`` equal to the account name, which
is why the host can be derived from the resource id instead of needing its own setting.
"""

import asyncio
import logging

import aiohttp

logger = logging.getLogger("scripts")

RELAY_TOKEN_PATH = "/tts/cognitiveservices/avatar/relay/token/v1"
DEFAULT_RELAY_TIMEOUT_SECONDS = 10


def speech_account_name_from_resource_id(speech_service_id: str) -> str:
    """Return the account name (the last segment) of a Cognitive Services resource id."""
    return speech_service_id.rstrip("/").rsplit("/", 1)[-1]


def build_relay_token_url(speech_service_id: str) -> str:
    """Build the Entra ID-capable relay token URL for a Speech resource id."""
    account_name = speech_account_name_from_resource_id(speech_service_id)
    if not account_name:
        raise ValueError("Speech service id does not contain an account name")
    return f"https://{account_name}.cognitiveservices.azure.com{RELAY_TOKEN_PATH}"


TURN_URL_SCHEMES = ("turn:", "turns:")


def select_turn_ice_servers(relay_payload: dict) -> list[dict]:
    """Shape a relay token response into RTCPeerConnection `iceServers` entries.

    Relay URLs are kept, ``stun:`` is dropped. The relay endpoint may also return a ``stun:`` URL,
    which the avatar docs explicitly say to exclude — a STUN entry alongside the TURN one makes the
    browser try a direct path that the avatar service does not accept, so the connection stalls in
    ICE gathering instead of failing fast.

    ``turns:`` (TURN over TLS, normally port 443) is kept deliberately. The test used to be
    ``startswith("turn:")``, and ``"turns:"`` does not start with ``"turn:"`` — the ``s`` sits where the
    colon is expected — so a TLS relay entry would have been silently discarded along with the STUN
    entry the filter is actually about.

    This is latent correctness, not a live improvement: checked against the nerilio Speech resource
    on 2026-08-19, the relay returns exactly ONE url, ``turn:relay.communication.microsoft.com:3478``
    — no ``turns:`` and no ``stun:``. So today every avatar session rides a single UDP allocation for a
    1080p stream with no alternative path, and nothing here can change that; the client-side
    ICE recovery grace window in ``avatarSession.ts`` is what actually has to absorb the resulting
    packet loss. The filter is fixed so that if Microsoft ever does return a TLS entry it is used
    instead of dropped on the floor.
    """
    urls = relay_payload.get("Urls") or []
    turn_urls = [url for url in urls if isinstance(url, str) and url.lower().startswith(TURN_URL_SCHEMES)]
    if not turn_urls:
        raise ValueError("Avatar relay token response contained no turn: or turns: URL")

    return [
        {
            "urls": turn_urls,
            "username": relay_payload.get("Username", ""),
            "credential": relay_payload.get("Password", ""),
        }
    ]


async def fetch_ice_servers_from_url(
    relay_url: str,
    bearer_token: str,
    timeout_seconds: int = DEFAULT_RELAY_TIMEOUT_SECONDS,
) -> list[dict]:
    """Fetch and shape TURN credentials from an explicit relay URL.

    Split out from `fetch_avatar_ice_servers` so tests can exercise the real HTTP path against a
    local server instead of mocking the client session.
    """
    try:
        async with aiohttp.ClientSession(
            headers={"Authorization": f"Bearer {bearer_token}"},
            timeout=aiohttp.ClientTimeout(total=timeout_seconds),
        ) as session:
            async with session.get(relay_url) as response:
                if response.status != 200:
                    body = await response.text()
                    logger.error(
                        "Avatar relay token request failed with %s: %s",
                        response.status,
                        body[:500],
                    )
                    raise RuntimeError(f"Avatar relay token request failed with status {response.status}")
                relay_payload = await response.json(content_type=None)
    except (TimeoutError, asyncio.TimeoutError) as error:
        logger.error("Avatar relay token request timed out after %ss", timeout_seconds)
        raise RuntimeError("Avatar relay token request timed out") from error

    return select_turn_ice_servers(relay_payload)


async def fetch_avatar_ice_servers(
    speech_service_id: str,
    bearer_token: str,
    timeout_seconds: int = DEFAULT_RELAY_TIMEOUT_SECONDS,
) -> list[dict]:
    """Fetch TURN credentials for an avatar WebRTC session.

    Raises on any failure so the caller can surface a 500 — unlike the CRM sync, there is no
    meaningful degraded mode here: without ICE servers the avatar simply cannot connect.
    """
    return await fetch_ice_servers_from_url(
        relay_url=build_relay_token_url(speech_service_id),
        bearer_token=bearer_token,
        timeout_seconds=timeout_seconds,
    )
