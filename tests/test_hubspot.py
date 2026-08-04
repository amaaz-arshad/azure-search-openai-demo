"""HubSpot contact creation for verified Free Bot signups.

These exercise the real aiohttp request path against a throwaway localhost server rather than a
mocked ClientSession, so the headers, the JSON body and the status handling are all genuinely
covered. The one thing they cannot cover is whether the live portal actually accepts the
`neriliofreebot` property — that needs a real token, see CHANGES.md for the manual verification.
"""

import asyncio
from contextlib import asynccontextmanager

import pytest
from aiohttp import web

from core.hubspot import HUBSPOT_FREE_BOT_PROPERTY, HUBSPOT_LOGGED_BODY_LIMIT, HubSpotContactStore

CONTACTS_PATH = "/crm/v3/objects/contacts"


@asynccontextmanager
async def fake_hubspot(handler):
    """Serve `handler` at the contacts path and yield its URL."""
    app = web.Application()
    app.router.add_post(CONTACTS_PATH, handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    try:
        port = runner.addresses[0][1]
        yield f"http://127.0.0.1:{port}{CONTACTS_PATH}"
    finally:
        await runner.cleanup()


def test_the_payload_matches_the_shape_hubspot_expects():
    properties = HubSpotContactStore.build_contact_properties(
        email="  Susi@Example.COM ",
        first_name=" Susi ",
        last_name=" Musterfrau ",
        company=" Mustermann GmbH ",
    )

    assert properties == {
        "email": "susi@example.com",
        "firstname": "Susi",
        "lastname": "Musterfrau",
        "company": "Mustermann GmbH",
        HUBSPOT_FREE_BOT_PROPERTY: "true",
    }


def test_blank_values_are_omitted_rather_than_blanking_a_hubspot_field():
    properties = HubSpotContactStore.build_contact_properties(email="susi@example.com", company="   ")

    assert properties == {"email": "susi@example.com", HUBSPOT_FREE_BOT_PROPERTY: "true"}
    assert "firstname" not in properties
    assert "lastname" not in properties
    assert "company" not in properties


@pytest.mark.asyncio
async def test_a_successful_create_sends_the_bearer_token_and_the_properties():
    received = {}

    async def handler(request: web.Request):
        received["authorization"] = request.headers.get("Authorization")
        received["content_type"] = request.headers.get("Content-Type")
        received["body"] = await request.json()
        return web.json_response({"id": "12345"}, status=201)

    async with fake_hubspot(handler) as contacts_url:
        store = HubSpotContactStore(api_key="pat-eu1-test-token", contacts_url=contacts_url)
        assert await store.create_contact(
            email="susi@example.com",
            first_name="Susi",
            last_name="Musterfrau",
            company="Mustermann GmbH",
        )

    assert received["authorization"] == "Bearer pat-eu1-test-token"
    assert received["content_type"] == "application/json"
    assert received["body"] == {
        "properties": {
            "email": "susi@example.com",
            "firstname": "Susi",
            "lastname": "Musterfrau",
            "company": "Mustermann GmbH",
            HUBSPOT_FREE_BOT_PROPERTY: "true",
        }
    }


@pytest.mark.asyncio
async def test_an_unconfigured_store_makes_no_request_at_all():
    call_count = 0

    async def handler(request: web.Request):
        nonlocal call_count
        call_count += 1
        return web.json_response({"id": "12345"}, status=201)

    async with fake_hubspot(handler) as contacts_url:
        store = HubSpotContactStore(api_key="   ", contacts_url=contacts_url)
        assert store.is_configured() is False
        assert await store.create_contact(email="susi@example.com") is False

    assert call_count == 0


@pytest.mark.parametrize("status_code", [400, 401, 403, 429, 500])
@pytest.mark.asyncio
async def test_a_rejected_create_is_reported_as_failure_without_raising(status_code):
    """A revoked token or a renamed property must never surface as a signup error."""

    async def handler(request: web.Request):
        return web.json_response({"message": "nope"}, status=status_code)

    async with fake_hubspot(handler) as contacts_url:
        store = HubSpotContactStore(api_key="pat-eu1-test-token", contacts_url=contacts_url)
        assert await store.create_contact(email="susi@example.com") is False


@pytest.mark.asyncio
async def test_a_duplicate_contact_is_left_untouched():
    """HubSpot answers 409 for a known email; the signup is not the authority on that contact."""

    async def handler(request: web.Request):
        return web.json_response({"message": "Contact already exists. Existing ID: 701"}, status=409)

    async with fake_hubspot(handler) as contacts_url:
        store = HubSpotContactStore(api_key="pat-eu1-test-token", contacts_url=contacts_url)
        assert await store.create_contact(email="susi@example.com") is False


def test_a_duplicate_is_logged_as_information_not_as_an_error(caplog):
    with caplog.at_level("INFO", logger="scripts"):
        assert (
            HubSpotContactStore.interpret_contact_response(
                email="susi@example.com",
                status_code=409,
                body="Contact already exists. Existing ID: 701",
            )
            is False
        )

    assert [record.levelname for record in caplog.records] == ["INFO"]
    assert "Existing ID: 701" in caplog.text


def test_a_real_failure_is_logged_as_an_error_so_it_surfaces_in_container_apps(caplog):
    with caplog.at_level("INFO", logger="scripts"):
        assert (
            HubSpotContactStore.interpret_contact_response(
                email="susi@example.com",
                status_code=401,
                body="Authentication credentials not found",
            )
            is False
        )

    assert [record.levelname for record in caplog.records] == ["ERROR"]


def test_a_logged_body_is_truncated(caplog):
    """An unbounded HubSpot error body must not flood the log."""
    with caplog.at_level("INFO", logger="scripts"):
        assert (
            HubSpotContactStore.interpret_contact_response(email="a@b.co", status_code=500, body="x" * 10_000) is False
        )

    logged_body = caplog.records[0].getMessage()
    assert "x" * HUBSPOT_LOGGED_BODY_LIMIT in logged_body
    assert "x" * (HUBSPOT_LOGGED_BODY_LIMIT + 1) not in logged_body


@pytest.mark.asyncio
async def test_a_hanging_hubspot_gives_up_instead_of_holding_the_signup_open():
    async def handler(request: web.Request):
        await asyncio.sleep(5)
        return web.json_response({"id": "12345"}, status=201)

    async with fake_hubspot(handler) as contacts_url:
        store = HubSpotContactStore(
            api_key="pat-eu1-test-token",
            contacts_url=contacts_url,
            timeout_seconds=1,
        )
        assert await store.create_contact(email="susi@example.com") is False


@pytest.mark.asyncio
async def test_an_unreachable_hubspot_is_reported_as_failure_without_raising():
    # Nothing is listening on this port, so the connection is refused outright.
    store = HubSpotContactStore(api_key="pat-eu1-test-token", contacts_url="http://127.0.0.1:1/contacts")

    assert await store.create_contact(email="susi@example.com") is False
