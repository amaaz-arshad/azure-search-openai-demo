import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

import pytest
import quart.testing.app
from httpx import Request, Response
from openai import BadRequestError
from quart import Response as QuartResponse

import app
from core import freeauth as free_auth
from core.dynamic_bot_config import DEFAULT_DYNAMIC_QNA_MODEL, DEFAULT_DYNAMIC_TUTOR_MODEL
from core.internaladminauth import (
    INTERNAL_ADMIN_AUTH_COOKIE,
    INTERNAL_ADMIN_INVALID_PASSWORD_MESSAGE,
    INTERNAL_ADMIN_REQUIRED_MESSAGE,
)
from core.simplechatbotauth import SIMPLE_CHATBOT_AUTH_COOKIE_PREFIX
from embed_public_ids import DYNAMIC_PUBLIC_ID_INDEX, PUBLIC_ID_RE


def fake_response(http_code):
    return Response(http_code, request=Request(method="get", url="https://foo.bar/"))


# See https://learn.microsoft.com/azure/ai-services/openai/concepts/content-filter
filtered_response = BadRequestError(
    message="The response was filtered",
    body={
        "message": "The response was filtered",
        "type": None,
        "param": "prompt",
        "code": "content_filter",
        "status": 400,
    },
    response=Response(
        400, request=Request(method="get", url="https://foo.bar/"), json={"error": {"code": "content_filter"}}
    ),
)

contextlength_response = BadRequestError(
    message="This model's maximum context length is 4096 tokens. However, your messages resulted in 5069 tokens. Please reduce the length of the messages.",
    body={
        "message": "This model's maximum context length is 4096 tokens. However, your messages resulted in 5069 tokens. Please reduce the length of the messages.",
        "code": "context_length_exceeded",
        "status": 400,
    },
    response=Response(400, request=Request(method="get", url="https://foo.bar/"), json={"error": {"code": "429"}}),
)


def messages_contains_text(messages, text):
    for message in messages:
        if text in message["content"]:
            return True
    return False


def pop_citation_activity_details(result: dict[str, Any] | None):  # type: ignore[name-defined]
    if result is None:
        return None
    context = result.get("context") if isinstance(result, dict) else None
    if not isinstance(context, dict):
        return None
    data_points = context.get("data_points")
    if not isinstance(data_points, dict):
        return None
    return data_points.pop("citation_activity_details", None)


async def login_internal_admin(client, password: str = "chatbot123"):
    response = await client.post("/internal-admin/login", json={"password": password})
    payload = await response.get_json()
    assert response.status_code == 200
    assert payload == {"authenticated": True}
    return response


async def login_simple_chatbot(client, chatbot_name: str, username: str, password: str):
    response = await client.post(
        f"/chatbot-auth/{chatbot_name}/login",
        json={"username": username, "password": password},
    )
    payload = await response.get_json()
    assert response.status_code == 200
    assert payload == {"authenticated": True, "user": username}
    return response


class OpenLitAttributeRecorder:
    def __init__(self):
        self.entries: list[dict[str, str]] = []
        self.exits: list[dict[str, str]] = []
        self.active: list[dict[str, str]] = []

    def using_attributes(self, attributes: dict[str, str]):
        recorder = self

        class OpenLitAttributeContext:
            def __enter__(self):
                captured_attributes = dict(attributes)
                recorder.entries.append(captured_attributes)
                recorder.active.append(captured_attributes)

            def __exit__(self, exc_type, exc_value, traceback):
                recorder.exits.append(dict(attributes))
                recorder.active.pop()

        return OpenLitAttributeContext()


@pytest.mark.asyncio
async def test_missing_env_vars():
    with mock.patch.dict(os.environ, clear=True):
        quart_app = app.create_app()

        with pytest.raises(quart.testing.app.LifespanError, match="Error during startup 'AZURE_STORAGE_ACCOUNT'"):
            async with quart_app.test_app() as test_app:
                test_app.test_client()


@pytest.mark.asyncio
async def test_index(client):
    response = await client.get("/")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_redirect(client):
    response = await client.get("/redirect")
    assert response.status_code == 200
    assert (await response.get_data()) == b""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "expected_location"),
    [
        ("/nerilio/.auth/me", "/.auth/me"),
        (
            "/nerilio/.auth/logout?post_logout_redirect_uri=/",
            "/.auth/logout?post_logout_redirect_uri=/",
        ),
    ],
)
async def test_chatbot_auth_subpath_redirects_to_root_auth_endpoint(client, path, expected_location):
    response = await client.get(path)
    assert response.status_code == 302
    assert response.headers["Location"] == expected_location


@pytest.mark.asyncio
async def test_favicon(client):
    response = await client.get("/favicon.ico")
    assert response.status_code == 200
    assert response.content_type.startswith("image")
    assert response.content_type.endswith("icon")


@pytest.mark.asyncio
async def test_cors_notallowed(client) -> None:
    response = await client.get("/", headers={"Origin": "https://quart.com"})
    assert "Access-Control-Allow-Origin" not in response.headers


@pytest.mark.asyncio
async def test_assets_route_delegates_to_send_from_directory(client, monkeypatch):
    async def fake_send_from_directory(directory, requested_path):
        assert "assets" in str(directory)
        assert requested_path == "bundle.js"
        return QuartResponse("console.log('hi')", mimetype="application/javascript")

    monkeypatch.setattr(app, "send_from_directory", fake_send_from_directory)

    response = await client.get("/assets/bundle.js")
    assert response.status_code == 200
    assert await response.get_data() == b"console.log('hi')"


@pytest.mark.asyncio
async def test_cors_allowed(client) -> None:
    response = await client.get("/", headers={"Origin": "https://frontend.com"})
    assert response.access_control_allow_origin == "https://frontend.com"
    assert "Access-Control-Allow-Origin" in response.headers


@pytest.mark.asyncio
async def test_chat_request_must_be_json(client):
    response = await client.post("/chat")
    assert response.status_code == 415
    result = await response.get_json()
    assert result["error"] == "request must be json"


@pytest.mark.asyncio
async def test_send_text_sources_false(client):
    """When send_text_sources is False, text sources should be omitted while citations remain."""
    response = await client.post(
        "/chat",
        json={
            "messages": [{"content": "What is the capital of France?", "role": "user"}],
            "context": {"overrides": {"retrieval_mode": "text", "send_text_sources": False}},
        },
    )
    assert response.status_code == 200
    result = await response.get_json()
    data_points = result["context"]["data_points"]
    assert data_points["text"] == []
    assert "citations" in data_points and len(data_points["citations"]) > 0


@pytest.mark.asyncio
async def test_search_image_embeddings_ignored_without_multimodal(client):
    """Sending search_image_embeddings=True when USE_MULTIMODAL is false should be ignored and still succeed (200)."""
    response = await client.post(
        "/chat",
        json={
            "messages": [{"content": "What is the capital of France?", "role": "user"}],
            "context": {"overrides": {"search_image_embeddings": True, "send_image_sources": True}},
        },
    )
    assert response.status_code == 200
    result = await response.get_json()
    # Ensure the thought step recorded search_image_embeddings as False
    search_thought = [
        thought for thought in result["context"]["thoughts"] if thought["title"].startswith("Search using")
    ][0]
    assert search_thought["props"]["search_image_embeddings"] is False


@pytest.mark.asyncio
async def test_content_file_missing_content_settings(auth_client, monkeypatch):
    blob_manager = auth_client.config[app.CONFIG_GLOBAL_BLOB_MANAGER]

    async def fake_download_blob(_path, user_oid=None, container=None):
        return b"data", {}

    monkeypatch.setattr(blob_manager, "download_blob", fake_download_blob)

    response = await auth_client.get("/content/file.pdf", headers={"Authorization": "Bearer token"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_chat_stream_request_must_be_json(client):
    response = await client.post("/chat/stream")
    assert response.status_code == 415
    result = await response.get_json()
    assert result["error"] == "request must be json"


@pytest.mark.asyncio
async def test_chat_adds_openlit_chatbot_attributes(client, monkeypatch):
    recorder = OpenLitAttributeRecorder()
    monkeypatch.setenv("OPENLIT_ENDPOINT", "http://openlit.internal")
    monkeypatch.setitem(sys.modules, "openlit", SimpleNamespace(using_attributes=recorder.using_attributes))

    prompt_store = client.app.config[app.CONFIG_CHATBOT_PROMPT_STORE]

    async def mock_load_prompt(_chatbot_name: str):
        return None

    monkeypatch.setattr(prompt_store, "load_prompt", mock_load_prompt)

    response = await client.post(
        "/chat",
        headers={"X-Chatbot-Name": "demo"},
        json={
            "messages": [{"content": "What is the capital of France?", "role": "user"}],
            "context": {"overrides": {"retrieval_mode": "text", "include_category": "demo"}},
        },
    )

    assert response.status_code == 200
    assert recorder.entries == [{"chatbot.name": "demo", "chatbot.effective_name": "demo"}]
    assert recorder.exits == recorder.entries


@pytest.mark.asyncio
async def test_chat_hyrox_assessment_routes_and_skips_retrieval(client, monkeypatch):
    """The assessment bot grades from its in-prompt rubric, so /chat must succeed
    without performing any search retrieval."""
    prompt_store = client.app.config[app.CONFIG_CHATBOT_PROMPT_STORE]

    async def mock_load_prompt(_chatbot_name: str):
        return None

    monkeypatch.setattr(prompt_store, "load_prompt", mock_load_prompt)

    response = await client.post(
        "/chat",
        headers={"X-Chatbot-Name": "hyrox-assessment"},
        json={
            "messages": [{"content": "start", "role": "user"}],
            "context": {"overrides": {"retrieval_mode": "text", "include_category": "hyrox-assessment", "language": "en"}},
        },
    )

    assert response.status_code == 200
    result = await response.get_json()
    assert isinstance(result["message"]["content"], str)
    # Skip-retrieval path: no search query / search-results thought steps were produced.
    thoughts_blob = json.dumps(result["context"]["thoughts"])
    assert "Search using generated search query" not in thoughts_blob
    assert "Search results" not in thoughts_blob


@pytest.mark.asyncio
async def test_internal_chat_adds_openlit_route_and_source_attributes(client, monkeypatch):
    recorder = OpenLitAttributeRecorder()
    monkeypatch.setenv("OPENLIT_ENDPOINT", "http://openlit.internal")
    monkeypatch.setitem(sys.modules, "openlit", SimpleNamespace(using_attributes=recorder.using_attributes))

    prompt_store = client.app.config[app.CONFIG_CHATBOT_PROMPT_STORE]

    async def mock_load_prompt(_chatbot_name: str):
        return None

    monkeypatch.setattr(prompt_store, "load_prompt", mock_load_prompt)

    response = await client.post(
        "/chat",
        headers={"X-Chatbot-Name": "internal"},
        json={
            "messages": [{"content": "What is the capital of France?", "role": "user"}],
            "context": {"overrides": {"retrieval_mode": "text", "source_chatbot": "lemon"}},
        },
    )

    assert response.status_code == 200
    assert recorder.entries == [
        {
            "chatbot.name": "internal",
            "chatbot.effective_name": "lemon",
            "chatbot.source_name": "lemon",
        }
    ]
    assert recorder.exits == recorder.entries


@pytest.mark.asyncio
async def test_chat_stream_keeps_openlit_chatbot_attributes_active_while_streaming(client, monkeypatch):
    recorder = OpenLitAttributeRecorder()
    active_attributes_during_stream: list[list[dict[str, str]]] = []
    monkeypatch.setenv("OPENLIT_ENDPOINT", "http://openlit.internal")
    monkeypatch.setitem(sys.modules, "openlit", SimpleNamespace(using_attributes=recorder.using_attributes))

    prompt_store = client.app.config[app.CONFIG_CHATBOT_PROMPT_STORE]

    async def mock_load_prompt(_chatbot_name: str):
        return None

    class StreamingApproach:
        async def run_stream(self, messages, session_state=None, context=None):
            async def stream():
                active_attributes_during_stream.append(list(recorder.active))
                yield {"delta": {"role": "assistant", "content": "Hello"}}

            return stream()

    monkeypatch.setattr(prompt_store, "load_prompt", mock_load_prompt)
    client.app.config[app.CONFIG_CHAT_APPROACH] = StreamingApproach()
    client.app.config[app.CONFIG_CHATBOT_CHAT_APPROACHES] = {}

    response = await client.post(
        "/chat/stream",
        json={
            "messages": [{"content": "What is the capital of France?", "role": "user"}],
            "context": {"overrides": {"retrieval_mode": "text", "include_category": "demo"}},
        },
    )

    assert response.status_code == 200
    assert (await response.get_data()).decode("utf-8") == '{"delta": {"role": "assistant", "content": "Hello"}}\n'
    assert active_attributes_during_stream == [[{"chatbot.name": "demo", "chatbot.effective_name": "demo"}]]


def test_json_encoder_drops_optional_fields():
    data_points = app.DataPoints(
        text=["One"], citations=["a"], external_results_metadata=None, citation_activity_details=None
    )
    encoded = app.JSONEncoder().encode(data_points)
    assert "citation_activity_details" not in encoded
    assert '"text": ["One"]' in encoded


@pytest.mark.asyncio
async def test_auth_setup_returns_payload(client):
    response = await client.get("/auth_setup")
    assert response.status_code == 200
    payload = await response.get_json()
    assert isinstance(payload, dict)
    assert payload  # should contain configuration values


@pytest.mark.asyncio
async def test_free_signup_starts_verification(client, monkeypatch):
    auth_service = client.app.config[app.CONFIG_FREE_AUTH_SERVICE]

    async def mock_start_signup(**kwargs):
        assert kwargs["first_name"] == "Susi"
        assert kwargs["last_name"] == "Musterfrau"
        assert kwargs["display_name"] == "Test User"
        assert kwargs["email"] == "user@example.com"
        return SimpleNamespace(email="user@example.com", expires_in_seconds=900)

    monkeypatch.setattr(auth_service, "start_signup", mock_start_signup)

    response = await client.post(
        "/free-auth/signup",
        json={
            "firstName": "Susi",
            "lastName": "Musterfrau",
            "displayName": "Test User",
            "email": "user@example.com",
            "password": "secret",
            "confirmPassword": "secret",
        },
    )

    payload = await response.get_json()
    assert response.status_code == 200
    assert payload == {
        "verificationRequired": True,
        "email": "user@example.com",
        "expiresInSeconds": 900,
    }


@pytest.mark.asyncio
async def test_free_signup_without_names_is_a_validation_error_not_a_crash(client):
    """An old cached frontend bundle posts no names; that must be a 400, never a 500."""
    response = await client.post(
        "/free-auth/signup",
        json={
            "displayName": "Test User",
            "email": "user@example.com",
            "password": "secret-enough",
            "confirmPassword": "secret-enough",
        },
    )

    payload = await response.get_json()
    assert response.status_code == 400
    assert payload == {"errorKey": "authErrors.firstNameRequired"}


@pytest.mark.asyncio
async def test_free_signup_verify_sets_session_cookie(client, monkeypatch):
    auth_service = client.app.config[app.CONFIG_FREE_AUTH_SERVICE]

    async def mock_verify_signup(**kwargs):
        assert kwargs["email"] == "user@example.com"
        assert kwargs["verification_code"] == "123456"
        return app.FreeSession(display_name="Test User", email="user@example.com")

    monkeypatch.setattr(auth_service, "verify_signup", mock_verify_signup)

    response = await client.post(
        "/free-auth/signup/verify",
        json={
            "email": "user@example.com",
            "verificationCode": "123456",
        },
    )

    payload = await response.get_json()
    assert response.status_code == 200
    assert payload["session"] == {
        "displayName": "Test User",
        "email": "user@example.com",
        "expiresAt": "",
        "daysRemaining": 0,
    }
    assert auth_service.session_cookie_name in response.headers["Set-Cookie"]


@pytest.mark.asyncio
async def test_free_password_reset_starts_verification(client, monkeypatch):
    auth_service = client.app.config[app.CONFIG_FREE_AUTH_SERVICE]

    async def mock_start_password_reset(**kwargs):
        assert kwargs["email"] == "user@example.com"
        return SimpleNamespace(email="user@example.com", expires_in_seconds=900)

    monkeypatch.setattr(auth_service, "start_password_reset", mock_start_password_reset)

    response = await client.post(
        "/free-auth/password-reset",
        json={
            "email": "user@example.com",
        },
    )

    payload = await response.get_json()
    assert response.status_code == 200
    assert payload == {
        "verificationRequired": True,
        "email": "user@example.com",
        "expiresInSeconds": 900,
    }


@pytest.mark.asyncio
async def test_free_password_reset_verify_sets_session_cookie(client, monkeypatch):
    auth_service = client.app.config[app.CONFIG_FREE_AUTH_SERVICE]

    async def mock_verify_password_reset(**kwargs):
        assert kwargs["email"] == "user@example.com"
        assert kwargs["verification_code"] == "123456"
        assert kwargs["password"] == "new-secret"
        assert kwargs["confirm_password"] == "new-secret"
        return app.FreeSession(display_name="Test User", email="user@example.com")

    monkeypatch.setattr(auth_service, "verify_password_reset", mock_verify_password_reset)

    response = await client.post(
        "/free-auth/password-reset/verify",
        json={
            "email": "user@example.com",
            "verificationCode": "123456",
            "password": "new-secret",
            "confirmPassword": "new-secret",
        },
    )

    payload = await response.get_json()
    assert response.status_code == 200
    assert payload["session"] == {
        "displayName": "Test User",
        "email": "user@example.com",
        "expiresAt": "",
        "daysRemaining": 0,
    }
    assert auth_service.session_cookie_name in response.headers["Set-Cookie"]


@pytest.mark.asyncio
async def test_free_password_reset_resend_returns_error_key(client, monkeypatch):
    auth_service = client.app.config[app.CONFIG_FREE_AUTH_SERVICE]

    async def mock_resend_password_reset_code(**kwargs):
        raise app.FreeAuthError("authErrors.passwordResetSessionNotFound", status_code=404)

    monkeypatch.setattr(auth_service, "resend_password_reset_code", mock_resend_password_reset_code)

    response = await client.post(
        "/free-auth/password-reset/resend",
        json={
            "email": "user@example.com",
        },
    )

    payload = await response.get_json()
    assert response.status_code == 404
    assert payload == {"errorKey": "authErrors.passwordResetSessionNotFound"}


@pytest.mark.asyncio
async def test_free_login_returns_error_key(client, monkeypatch):
    auth_service = client.app.config[app.CONFIG_FREE_AUTH_SERVICE]

    async def mock_login_user(**kwargs):
        raise app.FreeAuthError("authErrors.invalidCredentials", status_code=401)

    monkeypatch.setattr(auth_service, "login_user", mock_login_user)

    response = await client.post(
        "/free-auth/login",
        json={
            "email": "user@example.com",
            "password": "wrong-password",
        },
    )

    payload = await response.get_json()
    assert response.status_code == 401
    assert payload == {"errorKey": "authErrors.invalidCredentials"}


@pytest.mark.asyncio
async def test_free_session_returns_authenticated_user(client, monkeypatch):
    async def mock_get_authenticated_free_user():
        return app.FreeSession(
            display_name="Stored User",
            email="stored@example.com",
            expires_at="2026-04-30T10:00:00+00:00",
            days_remaining=12,
        )

    monkeypatch.setattr(app, "get_authenticated_free_user", mock_get_authenticated_free_user)

    response = await client.get("/free-auth/session")

    payload = await response.get_json()
    assert response.status_code == 200
    assert payload["session"] == {
        "displayName": "Stored User",
        "email": "stored@example.com",
        "expiresAt": "2026-04-30T10:00:00+00:00",
        "daysRemaining": 12,
    }


@pytest.mark.asyncio
async def test_free_profile_returns_account_details(client, monkeypatch):
    auth_service = client.app.config[app.CONFIG_FREE_AUTH_SERVICE]

    async def mock_get_authenticated_free_user():
        return app.FreeSession(display_name="Stored User", email="stored@example.com")

    async def mock_load_account(email: str):
        assert email == "stored@example.com"
        return SimpleNamespace(
            display_name="Stored User",
            email="stored@example.com",
            created_at=free_auth.format_utc(datetime.now(timezone.utc) - timedelta(days=4)),
            updated_at="2026-03-31T11:00:00+00:00",
        )

    monkeypatch.setattr(app, "get_authenticated_free_user", mock_get_authenticated_free_user)
    monkeypatch.setattr(auth_service, "load_account", mock_load_account)

    response = await client.get("/free-auth/profile")

    payload = await response.get_json()
    assert response.status_code == 200
    profile_payload = payload["profile"]
    assert profile_payload["displayName"] == "Stored User"
    assert profile_payload["email"] == "stored@example.com"
    assert profile_payload["updatedAt"] == "2026-03-31T11:00:00+00:00"
    # The 30-day trial countdown drives the Free Bot's expiry banner and profile row.
    assert profile_payload["daysRemaining"] == free_auth.FREE_ACCOUNT_LIFETIME_DAYS - 4
    assert profile_payload["expiresAt"]


@pytest.mark.asyncio
async def test_internal_admin_login_session_logout_flow(client):
    response = await client.get("/internal-admin/session")
    payload = await response.get_json()
    assert response.status_code == 200
    assert payload == {"authenticated": False}

    response = await client.post("/internal-admin/login", json={"password": "wrong-password"})
    payload = await response.get_json()
    assert response.status_code == 401
    assert payload == {"message": INTERNAL_ADMIN_INVALID_PASSWORD_MESSAGE, "authenticated": False}

    response = await login_internal_admin(client)
    assert INTERNAL_ADMIN_AUTH_COOKIE in response.headers["Set-Cookie"]

    response = await client.get("/internal-admin/session")
    payload = await response.get_json()
    assert response.status_code == 200
    assert payload == {"authenticated": True}

    response = await client.post("/internal-admin/logout")
    payload = await response.get_json()
    assert response.status_code == 200
    assert payload == {"authenticated": False}
    assert INTERNAL_ADMIN_AUTH_COOKIE in response.headers["Set-Cookie"]

    response = await client.get("/internal-admin/session")
    payload = await response.get_json()
    assert response.status_code == 200
    assert payload == {"authenticated": False}


@pytest.mark.asyncio
async def test_simple_chatbot_login_session_logout_flow(client):
    response = await client.get("/chatbot-auth/demo/session")
    payload = await response.get_json()
    assert response.status_code == 200
    assert payload == {"authenticated": False}

    response = await client.post(
        "/chatbot-auth/demo/login",
        json={"username": "demouser", "password": "wrong-password"},
    )
    payload = await response.get_json()
    assert response.status_code == 401
    assert payload["authenticated"] is False

    response = await login_simple_chatbot(client, "demo", "demouser", "demo@123")
    assert f"{SIMPLE_CHATBOT_AUTH_COOKIE_PREFIX}_demo" in response.headers["Set-Cookie"]

    response = await client.get("/chatbot-auth/demo/session")
    payload = await response.get_json()
    assert response.status_code == 200
    assert payload == {"authenticated": True, "user": "demouser"}

    response = await client.post("/chatbot-auth/demo/logout")
    payload = await response.get_json()
    assert response.status_code == 200
    assert payload == {"authenticated": False}
    assert f"{SIMPLE_CHATBOT_AUTH_COOKIE_PREFIX}_demo" in response.headers["Set-Cookie"]

    response = await client.get("/chatbot-auth/demo/session")
    payload = await response.get_json()
    assert response.status_code == 200
    assert payload == {"authenticated": False}


@pytest.mark.asyncio
async def test_simple_chatbot_chat_route_allows_missing_simple_auth_session(client, monkeypatch):
    prompt_store = client.app.config[app.CONFIG_CHATBOT_PROMPT_STORE]

    async def mock_load_prompt(_chatbot_name: str):
        return None

    monkeypatch.setattr(prompt_store, "load_prompt", mock_load_prompt)

    response = await client.post(
        "/chat",
        json={
            "messages": [{"content": "What is the capital of France?", "role": "user"}],
            "context": {"overrides": {"retrieval_mode": "text", "include_category": "demo"}},
        },
    )
    payload = await response.get_json()
    assert response.status_code == 200
    assert payload["context"]["thoughts"][1]["props"]["use_text_search"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path", ["/internal-admin/prompts", "/internal-admin/builtin-chatbots", "/managed_uploads", "/free-admin/users"]
)
async def test_internal_admin_routes_require_session(client, path):
    response = await client.get(path)
    payload = await response.get_json()
    assert response.status_code == 401
    assert payload == {"message": INTERNAL_ADMIN_REQUIRED_MESSAGE}


@pytest.mark.asyncio
async def test_manage_prompts_spa_route(client):
    response = await client.get("/manage-prompts")
    assert response.status_code == 200
    assert response.content_type.startswith("text/html")


@pytest.mark.asyncio
async def test_admin_spa_route(client):
    response = await client.get("/admin")
    assert response.status_code == 200
    assert response.content_type.startswith("text/html")


@pytest.mark.asyncio
async def test_admin_subpath_spa_route(client):
    # Deep links into a tab must serve index.html so the React router can mount that tab.
    response = await client.get("/admin/prompts")
    assert response.status_code == 200
    assert response.content_type.startswith("text/html")


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/chatbots", "/upload-files", "/free-users", "/manage-prompts"])
async def test_legacy_admin_routes_still_serve_spa(client, path):
    # Legacy admin URLs keep serving the SPA; the frontend then redirects them into the /admin tabs.
    response = await client.get(path)
    assert response.status_code == 200
    assert response.content_type.startswith("text/html")


def test_admin_is_reserved_non_chatbot_prefix():
    # "admin" must be reserved so the /<chatbot_name> catch-all and dynamic-bot provisioning can't
    # take it; the removed verwaltung mini-app must no longer be reserved.
    assert "admin" in app.NON_CHATBOT_FRONTEND_PREFIXES
    assert "verwaltung" not in app.NON_CHATBOT_FRONTEND_PREFIXES


@pytest.mark.asyncio
async def test_widget_loader_served_with_short_cache(client):
    response = await client.get("/widget.js")
    assert response.status_code == 200
    assert response.content_type.startswith("application/javascript")
    assert "max-age=300" in response.headers.get("Cache-Control", "")


@pytest.mark.asyncio
async def test_spa_index_allows_cross_origin_iframe_embedding(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert response.headers.get("Content-Security-Policy") == "frame-ancestors *"
    assert "X-Frame-Options" not in response.headers


@pytest.mark.asyncio
async def test_embed_demo_page_renders_chatbot_options(client):
    response = await client.get("/embed-demo")
    assert response.status_code == 200
    assert response.content_type.startswith("text/html")
    body = (await response.get_data()).decode()
    assert "{{CHATBOT_OPTIONS}}" not in body  # placeholder was replaced
    # Options carry the anonymous public ID as the value, with the readable name only as the label.
    assert f'<option value="{app.get_public_id("nerilio")}">nerilio</option>' in body
    assert "nerilio</option>" in body
    assert ">internal</option>" not in body  # router shell is excluded
    assert "/widget.js" in body


@pytest.mark.asyncio
async def test_embed_widget_config_returns_rules_with_cors(client, monkeypatch):
    embed_store = client.app.config[app.CONFIG_CHATBOT_EMBED_CONFIG_STORE]

    async def mock_load_allowed_rules(chatbot_name: str):
        assert chatbot_name == "publishone"
        return ["*.snap.de"]

    monkeypatch.setattr(embed_store, "load_allowed_rules", mock_load_allowed_rules)

    response = await client.get(f"/embed/{app.get_public_id('publishone')}/config")
    assert response.status_code == 200
    assert response.headers.get("Access-Control-Allow-Origin") == "*"
    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["rules"] == ["*.snap.de"]
    assert payload["allowAll"] is False
    assert payload["primaryColor"] == app.EMBED_LAUNCHER_COLORS["publishone"]
    # The readable name must never appear in the widget config response.
    assert "publishone" not in (await response.get_data()).decode()


@pytest.mark.asyncio
async def test_embed_widget_config_unknown_public_id_returns_404(client):
    response = await client.get("/embed/not-a-real-id/config")
    assert response.status_code == 404
    assert (await response.get_json())["ok"] is False


@pytest.mark.asyncio
async def test_embed_route_serves_spa_with_injected_name_and_locked_csp(client, monkeypatch):
    embed_store = client.app.config[app.CONFIG_CHATBOT_EMBED_CONFIG_STORE]

    async def mock_load_allowed_rules(chatbot_name: str):
        return ["*.snap.de", "publishone.snap.de/preise.html"]

    monkeypatch.setattr(embed_store, "load_allowed_rules", mock_load_allowed_rules)

    response = await client.get(f"/embed/{app.get_public_id('publishone')}")
    assert response.status_code == 200
    assert response.content_type.startswith("text/html")
    # Origins only (paths dropped) plus 'self' so our own preview/demo can still frame it.
    assert response.headers.get("Content-Security-Policy") == "frame-ancestors 'self' *.snap.de publishone.snap.de"
    assert "X-Frame-Options" not in response.headers
    body = (await response.get_data()).decode()
    assert 'window.__EMBED_CHATBOT_NAME__="publishone"' in body


@pytest.mark.asyncio
async def test_embed_route_unknown_public_id_redirects_home(client):
    response = await client.get("/embed/not-a-real-id")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")


@pytest.mark.asyncio
async def test_canonical_chatbot_route_locks_framing_to_whitelist(client, monkeypatch):
    embed_store = client.app.config[app.CONFIG_CHATBOT_EMBED_CONFIG_STORE]

    async def mock_load_allowed_rules(chatbot_name: str):
        assert chatbot_name == "publishone"
        return ["*.snap.de"]

    monkeypatch.setattr(embed_store, "load_allowed_rules", mock_load_allowed_rules)

    response = await client.get("/publishone")
    assert response.status_code == 200
    assert response.headers.get("Content-Security-Policy") == "frame-ancestors 'self' *.snap.de"


@pytest.mark.asyncio
async def test_internal_admin_embed_config_get_and_save(client, monkeypatch):
    await login_internal_admin(client)
    embed_store = client.app.config[app.CONFIG_CHATBOT_EMBED_CONFIG_STORE]
    saved_rules: dict[str, list[str]] = {"rules": []}

    async def mock_load_config(chatbot_name: str):
        return app.ChatbotEmbedConfig(chatbot_name=chatbot_name, allowed_rules=saved_rules["rules"])

    async def mock_save_rules(chatbot_name: str, rules: list[str]):
        assert chatbot_name == "publishone"
        saved_rules["rules"] = [rule.strip() for rule in rules if rule.strip()]
        return app.ChatbotEmbedConfig(chatbot_name=chatbot_name, allowed_rules=saved_rules["rules"])

    monkeypatch.setattr(embed_store, "load_config", mock_load_config)
    monkeypatch.setattr(embed_store, "save_rules", mock_save_rules)

    get_response = await client.get("/internal-admin/embed-config/publishone")
    assert get_response.status_code == 200
    get_payload = await get_response.get_json()
    assert get_payload["embedConfig"]["publicId"] == app.get_public_id("publishone")
    assert get_payload["embedConfig"]["allowedRules"] == []

    put_response = await client.put(
        "/internal-admin/embed-config/publishone",
        json={"allowedRules": ["*.snap.de", ""]},
    )
    assert put_response.status_code == 200
    put_payload = await put_response.get_json()
    assert put_payload["embedConfig"]["allowedRules"] == ["*.snap.de"]


@pytest.mark.asyncio
async def test_internal_admin_embed_config_rejects_non_embeddable_bot(client):
    await login_internal_admin(client)
    response = await client.get("/internal-admin/embed-config/internal")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_internal_admin_embed_config_requires_auth(client):
    response = await client.get("/internal-admin/embed-config/publishone")
    assert response.status_code == 401


# --- embedding provisioned (dynamic) bots --------------------------------------------------
#
# Dynamic bots have no committed public ID: theirs is minted at create time and stored on the
# registry record, so the /embed routes have to resolve through the registry. Everything below runs
# against an in-memory registry so no blob I/O is involved.

DYNAMIC_PUBLIC_ID = "dyn1234567"


def make_dynamic_record(
    bot_name="acme",
    *,
    active=True,
    public_id=DYNAMIC_PUBLIC_ID,
    display_name="ACME Support",
    llm=None,
    reasoning_effort=None,
    modes=None,
    design=None,
):
    return app.ChatbotRegistryRecord(
        bot_name=bot_name,
        display_name=display_name,
        active=active,
        created_at="2026-07-01T00:00:00+00:00",
        updated_at="2026-07-01T00:00:00+00:00",
        embed_public_id=public_id,
        llm=llm,
        reasoning_effort=reasoning_effort,
        modes=modes if modes is not None else {},
        design=design if design is not None else {},
    )


@pytest.fixture
def dynamic_registry(client, monkeypatch):
    """Replace the registry + embed-config stores with in-memory fakes.

    Yields the record dict, so a test can populate it with provisioned bots. The module-level
    publicId index is a cache, so it is cleared around each test.
    """
    records: dict[str, Any] = {}
    registry_store = client.app.config[app.CONFIG_CHATBOT_REGISTRY_STORE]
    embed_store = client.app.config[app.CONFIG_CHATBOT_EMBED_CONFIG_STORE]
    saved_rules: dict[str, list[str]] = {}

    async def load_record(bot_name):
        return records.get(bot_name)

    async def list_records():
        return dict(records)

    async def save_record(bot_name, *, fields):
        existing = records[bot_name]
        records[bot_name] = make_dynamic_record(
            bot_name,
            active=existing.active,
            public_id=existing.embed_public_id or fields.get("embed_public_id"),
            display_name=existing.display_name,
            llm=existing.llm,
            reasoning_effort=existing.reasoning_effort,
            modes=existing.modes,
            design=existing.design,
        )
        return records[bot_name]

    async def load_allowed_rules(chatbot_name):
        return list(saved_rules.get(chatbot_name, []))

    async def load_config(chatbot_name):
        return app.ChatbotEmbedConfig(chatbot_name=chatbot_name, allowed_rules=list(saved_rules.get(chatbot_name, [])))

    async def save_rules(chatbot_name, rules):
        saved_rules[chatbot_name] = [rule.strip() for rule in rules if rule.strip()]
        return app.ChatbotEmbedConfig(chatbot_name=chatbot_name, allowed_rules=saved_rules[chatbot_name])

    monkeypatch.setattr(registry_store, "load_record", load_record)
    monkeypatch.setattr(registry_store, "list_records", list_records)
    monkeypatch.setattr(registry_store, "save_record", save_record)
    monkeypatch.setattr(embed_store, "load_allowed_rules", load_allowed_rules)
    monkeypatch.setattr(embed_store, "load_config", load_config)
    monkeypatch.setattr(embed_store, "save_rules", save_rules)

    DYNAMIC_PUBLIC_ID_INDEX.by_public_id.clear()
    DYNAMIC_PUBLIC_ID_INDEX.last_refresh = None
    yield records
    DYNAMIC_PUBLIC_ID_INDEX.by_public_id.clear()
    DYNAMIC_PUBLIC_ID_INDEX.last_refresh = None


@pytest.mark.asyncio
async def test_embed_route_serves_a_provisioned_bot(client, dynamic_registry):
    dynamic_registry["acme"] = make_dynamic_record()

    response = await client.get(f"/embed/{DYNAMIC_PUBLIC_ID}")
    assert response.status_code == 200
    assert response.content_type.startswith("text/html")
    body = (await response.get_data()).decode()
    # The SPA mounts the bot from the injected name; the URL only ever carries the opaque ID.
    assert 'window.__EMBED_CHATBOT_NAME__="acme"' in body
    assert f'window.__EMBED_PUBLIC_ID__="{DYNAMIC_PUBLIC_ID}"' in body


@pytest.mark.asyncio
async def test_embed_widget_config_uses_the_provisioned_primary_color(client, dynamic_registry):
    dynamic_registry["acme"] = make_dynamic_record(design={"color_primary": "#123456"})

    response = await client.get(f"/embed/{DYNAMIC_PUBLIC_ID}/config")
    assert response.status_code == 200
    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["primaryColor"] == "#123456"
    assert payload["launcherIconColor"] is None
    assert payload["allowAll"] is True
    # The readable name must never appear in the widget config response.
    assert "acme" not in (await response.get_data()).decode()


@pytest.mark.asyncio
async def test_embed_widget_config_falls_back_when_no_color_is_provisioned(client, dynamic_registry):
    dynamic_registry["acme"] = make_dynamic_record(design={})
    response = await client.get(f"/embed/{DYNAMIC_PUBLIC_ID}/config")
    assert (await response.get_json())["primaryColor"] == app.EMBED_LAUNCHER_DEFAULT_COLOR


@pytest.mark.asyncio
async def test_stopped_provisioned_bot_is_not_embeddable(client, dynamic_registry):
    # A stopped bot's own route redirects home, so its live embeds must go dark the same way.
    dynamic_registry["acme"] = make_dynamic_record(active=False)

    entry_response = await client.get(f"/embed/{DYNAMIC_PUBLIC_ID}")
    assert entry_response.status_code == 302
    assert entry_response.headers["Location"].endswith("/")

    config_response = await client.get(f"/embed/{DYNAMIC_PUBLIC_ID}/config")
    assert config_response.status_code == 404
    assert (await config_response.get_json())["ok"] is False


@pytest.mark.asyncio
async def test_embed_route_locks_framing_to_a_provisioned_bots_whitelist(client, dynamic_registry, monkeypatch):
    dynamic_registry["acme"] = make_dynamic_record()
    embed_store = client.app.config[app.CONFIG_CHATBOT_EMBED_CONFIG_STORE]

    async def load_allowed_rules(chatbot_name):
        assert chatbot_name == "acme"
        return ["*.acme.example"]

    monkeypatch.setattr(embed_store, "load_allowed_rules", load_allowed_rules)

    response = await client.get(f"/embed/{DYNAMIC_PUBLIC_ID}")
    assert response.headers.get("Content-Security-Policy") == "frame-ancestors 'self' *.acme.example"
    assert "X-Frame-Options" not in response.headers


@pytest.mark.asyncio
async def test_internal_admin_embed_config_serves_a_provisioned_bot(client, dynamic_registry):
    dynamic_registry["acme"] = make_dynamic_record()
    await login_internal_admin(client)

    get_response = await client.get("/internal-admin/embed-config/acme")
    assert get_response.status_code == 200
    assert (await get_response.get_json())["embedConfig"]["publicId"] == DYNAMIC_PUBLIC_ID

    put_response = await client.put("/internal-admin/embed-config/acme", json={"allowedRules": ["*.acme.example", ""]})
    assert put_response.status_code == 200
    put_payload = await put_response.get_json()
    assert put_payload["embedConfig"]["allowedRules"] == ["*.acme.example"]
    assert put_payload["embedConfig"]["publicId"] == DYNAMIC_PUBLIC_ID


@pytest.mark.asyncio
async def test_internal_admin_embed_config_serves_a_stopped_provisioned_bot(client, dynamic_registry):
    # Editing the whitelist before starting a bot is allowed; only handing out a snippet is not.
    dynamic_registry["acme"] = make_dynamic_record(active=False)
    await login_internal_admin(client)
    response = await client.get("/internal-admin/embed-config/acme")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_internal_admin_embed_config_still_rejects_an_unknown_bot(client, dynamic_registry):
    await login_internal_admin(client)
    response = await client.get("/internal-admin/embed-config/ghost")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_dynamic_chatbots_listing_includes_stopped_bots_and_effective_models(client, dynamic_registry):
    dynamic_registry["acme"] = make_dynamic_record(llm="not-deployed-model")
    dynamic_registry["zeta"] = make_dynamic_record(
        "zeta", active=False, public_id="zet1234567", display_name="Zeta", modes={"tutor": True}
    )
    await login_internal_admin(client)

    response = await client.get("/internal-admin/dynamic-chatbots")
    assert response.status_code == 200
    chatbots = (await response.get_json())["chatbots"]
    assert [entry["botName"] for entry in chatbots] == ["acme", "zeta"]  # sorted

    acme, zeta = chatbots
    assert acme["publicId"] == DYNAMIC_PUBLIC_ID
    assert acme["active"] is True
    assert acme["mode"] == "qna"
    # An undeployed provisioned model must display the model that will really serve, not the bad one.
    assert acme["llm"] == DEFAULT_DYNAMIC_QNA_MODEL
    assert acme["reasoningEffort"] is None  # gpt-4.1 has no reasoning

    # Stopped bots are listed (flagged), so the directory shows the whole estate.
    assert zeta["active"] is False
    assert zeta["displayName"] == "Zeta"
    assert zeta["mode"] == "tutor-qna"
    assert zeta["llm"] == DEFAULT_DYNAMIC_TUTOR_MODEL
    assert zeta["reasoningEffort"] == "medium"


@pytest.mark.asyncio
async def test_dynamic_chatbots_listing_honors_a_deployed_provisioned_model(client, dynamic_registry, monkeypatch):
    monkeypatch.setitem(client.app.config, app.CONFIG_CHAT_MODEL_DEPLOYMENTS, {"gpt-5.4": "gpt-5.4"})
    dynamic_registry["acme"] = make_dynamic_record(llm="gpt-5.4", reasoning_effort="high")
    await login_internal_admin(client)

    response = await client.get("/internal-admin/dynamic-chatbots")
    entry = (await response.get_json())["chatbots"][0]
    assert entry["llm"] == "gpt-5.4"
    assert entry["reasoningEffort"] == "high"


@pytest.mark.asyncio
async def test_dynamic_chatbots_listing_backfills_a_missing_public_id(client, dynamic_registry):
    # A bot provisioned before dynamic embedding existed is healed on first admin access, so the
    # whole listing is immediately embeddable.
    dynamic_registry["legacy"] = make_dynamic_record("legacy", public_id=None)
    await login_internal_admin(client)

    response = await client.get("/internal-admin/dynamic-chatbots")
    entry = (await response.get_json())["chatbots"][0]
    assert PUBLIC_ID_RE.match(entry["publicId"])
    assert dynamic_registry["legacy"].embed_public_id == entry["publicId"]  # persisted, not just returned


@pytest.mark.asyncio
async def test_dynamic_chatbots_listing_requires_auth(client):
    response = await client.get("/internal-admin/dynamic-chatbots")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_builtin_chatbots_listing_reports_the_settings_chat_would_use(client):
    # The directory used to hand-mirror these from the deployment .env, which drifts silently. The
    # endpoint must resolve exactly like /chat does, so a card can never advertise a model or effort
    # the bot does not actually run on.
    await login_internal_admin(client)

    response = await client.get("/internal-admin/builtin-chatbots")
    assert response.status_code == 200
    chatbots = (await response.get_json())["chatbots"]
    assert [entry["name"] for entry in chatbots] == sorted(app.KNOWN_CHATBOT_NAMES)

    overrides = client.app.config[app.CONFIG_CHATBOT_CHAT_APPROACHES]
    default_approach = client.app.config[app.CONFIG_CHAT_APPROACH]
    by_name = {entry["name"]: entry for entry in chatbots}
    for name in app.KNOWN_CHATBOT_NAMES:
        if name == app.INTERNAL_ROUTER_CHATBOT_NAME:
            continue
        approach = overrides.get(app.normalize_chatbot_name(name) or name, default_approach)
        assert by_name[name]["llm"] == approach.chatgpt_model

    # /internal is a router shell: its include_category — and so the approach lookup — resolves to
    # the SELECTED source bot, so it has no model of its own and must not claim one.
    assert by_name["internal"] == {
        "name": "internal",
        "llm": None,
        "reasoningEffort": None,
        "variesBySourceBot": True,
    }

    # A bot pinned in its own config.py reports that model/effort, not the deployment default.
    assert by_name["lemon"]["llm"] == "gpt-5.4-mini"
    assert by_name["lemon"]["reasoningEffort"] == "high"
    # Effort is meaningless on a non-reasoning model and is dropped downstream, so it is not shown.
    assert by_name["snap"]["llm"] == "gpt-4.1"
    assert by_name["snap"]["reasoningEffort"] is None


@pytest.mark.asyncio
async def test_builtin_chatbots_listing_resolves_the_public_test_alias(client):
    # `public-test` is an alias of `free`, so a chat request through either name runs on the same
    # config; the listing must not report the deployment default for the alias.
    await login_internal_admin(client)

    response = await client.get("/internal-admin/builtin-chatbots")
    by_name = {entry["name"]: entry for entry in (await response.get_json())["chatbots"]}
    assert by_name["public-test"] == {**by_name["free"], "name": "public-test"}


@pytest.mark.asyncio
async def test_embed_demo_page_fetches_provisioned_chatbots(client):
    # Built-in options are server-rendered; provisioned bots are fetched so a newly created bot
    # appears in the picker with no redeploy.
    response = await client.get("/embed-demo")
    body = (await response.get_data()).decode()
    assert "/internal-admin/dynamic-chatbots" in body


@pytest.mark.asyncio
async def test_route_name_resolves_anonymized_embed_referer(client):
    # Requests from inside the embed iframe carry Referer /embed/<publicId>; it must map to the bot
    # so per-bot scoping (history, simple-auth, telemetry) matches the old /<name>?embed=1 behavior.
    public_id = app.get_public_id("publishone")
    async with client.app.test_request_context(
        "/chat", method="POST", headers={"Referer": f"https://host.example/embed/{public_id}?embed=1"}
    ):
        assert app.get_request_route_chatbot_name() == "publishone"


@pytest.mark.asyncio
async def test_route_name_ignores_unknown_embed_referer(client):
    async with client.app.test_request_context(
        "/chat", method="POST", headers={"Referer": "https://host.example/embed/not-a-real-id"}
    ):
        assert app.get_request_route_chatbot_name() is None


@pytest.mark.asyncio
async def test_route_name_still_resolves_plain_chatbot_referer(client):
    async with client.app.test_request_context(
        "/chat", method="POST", headers={"Referer": "https://host.example/publishone"}
    ):
        assert app.get_request_route_chatbot_name() == "publishone"


@pytest.mark.asyncio
async def test_internal_admin_prompt_list_excludes_internal_router_bot(client):
    prompt_store = client.app.config[app.CONFIG_CHATBOT_PROMPT_STORE]

    async def mock_list_prompts():
        return {}

    with mock.patch.object(prompt_store, "list_prompts", mock_list_prompts):
        await login_internal_admin(client)

        response = await client.get("/internal-admin/prompts")
        payload = await response.get_json()

        assert response.status_code == 200
        assert all(prompt["chatbotName"] != "internal" for prompt in payload["prompts"])


def test_chat_history_scope_marks_internal_admin_routes_as_non_chatbot():
    chat_history_scope = (
        Path(app.__file__).resolve().parent.parent / "frontend" / "src" / "chatHistoryScope.ts"
    ).read_text(encoding="utf-8")
    assert '"admin"' in chat_history_scope
    assert '"free-users"' in chat_history_scope
    assert '"public-test-users"' in chat_history_scope
    assert '"manage-prompts"' in chat_history_scope
    # The anonymized embed route (/embed/<publicId>) must resolve to the backend-injected bot name,
    # not the shared "embed" path segment, or embedded bots would share one chat-history scope.
    assert "__EMBED_CHATBOT_NAME__" in chat_history_scope


@pytest.mark.asyncio
async def test_legacy_free_route_redirects_to_free(client):
    response = await client.get("/public-test")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/free")


@pytest.mark.asyncio
async def test_prompt_override_is_used_for_next_chat_request_and_delete_restores_default(client, monkeypatch):
    await login_internal_admin(client)
    await login_simple_chatbot(client, "demo", "demouser", "demo@123")

    prompt_store = client.app.config[app.CONFIG_CHATBOT_PROMPT_STORE]
    override_state = {"prompt": None}

    async def mock_load_prompt(chatbot_name: str):
        assert chatbot_name == "demo"
        return override_state["prompt"]

    async def mock_save_prompt(chatbot_name: str, prompt: str, *, default_prompt: str | None = None):
        assert chatbot_name == "demo"
        assert default_prompt == app.get_chatbot_prompt("demo")
        override_state["prompt"] = app.ChatbotPromptOverride(
            chatbot_name="demo",
            prompt=prompt,
            created_at="2026-04-08T10:00:00+00:00",
            updated_at="2026-04-08T10:05:00+00:00",
        )
        return override_state["prompt"]

    async def mock_delete_prompt(chatbot_name: str):
        assert chatbot_name == "demo"
        override_state["prompt"] = None
        return True

    monkeypatch.setattr(prompt_store, "load_prompt", mock_load_prompt)
    monkeypatch.setattr(prompt_store, "save_prompt", mock_save_prompt)
    monkeypatch.setattr(prompt_store, "delete_prompt", mock_delete_prompt)

    save_response = await client.put(
        "/internal-admin/prompts/demo",
        json={"prompt": "You are a saved prompt for {{ SUPPORT_EMAIL }}."},
    )
    save_payload = await save_response.get_json()
    assert save_response.status_code == 200
    assert save_payload["prompt"]["source"] == "override"
    assert save_payload["prompt"]["updatedAt"] == "2026-04-08T10:05:00+00:00"

    response = await client.post(
        "/chat",
        json={
            "messages": [{"content": "What is the capital of France?", "role": "user"}],
            "context": {"overrides": {"retrieval_mode": "text", "include_category": "demo"}},
        },
    )
    assert response.status_code == 200
    result = await response.get_json()
    assert result["context"]["thoughts"][3]["description"][0]["content"].startswith(
        "You are a saved prompt for info@snap.de."
    )

    reset_response = await client.delete("/internal-admin/prompts/demo")
    reset_payload = await reset_response.get_json()
    assert reset_response.status_code == 200
    assert reset_payload["prompt"]["source"] == "default"

    response = await client.post(
        "/chat",
        json={
            "messages": [{"content": "What is the capital of France?", "role": "user"}],
            "context": {"overrides": {"retrieval_mode": "text", "include_category": "demo"}},
        },
    )
    assert response.status_code == 200
    result = await response.get_json()
    assert not result["context"]["thoughts"][3]["description"][0]["content"].startswith(
        "You are a saved prompt for info@snap.de."
    )


@pytest.mark.asyncio
async def test_free_admin_users_lists_accounts(client, monkeypatch):
    await login_internal_admin(client)
    auth_service = client.app.config[app.CONFIG_FREE_AUTH_SERVICE]

    active_created_at = free_auth.format_utc(datetime.now(timezone.utc) - timedelta(days=2))
    expired_created_at = free_auth.format_utc(
        datetime.now(timezone.utc) - timedelta(days=free_auth.FREE_ACCOUNT_LIFETIME_DAYS + 5)
    )

    async def mock_list_accounts():
        return [
            SimpleNamespace(
                display_name="Test User",
                email="user@example.com",
                created_at=active_created_at,
                updated_at="2026-03-31T11:00:00+00:00",
            ),
            SimpleNamespace(
                display_name="Lapsed User",
                email="lapsed@example.com",
                created_at=expired_created_at,
                updated_at="2026-03-31T11:00:00+00:00",
            ),
        ]

    upload_manager = mock.AsyncMock()
    upload_manager.list_files.return_value = ["sample.pdf"]

    monkeypatch.setattr(auth_service, "list_accounts", mock_list_accounts)
    monkeypatch.setattr(app, "get_chatbot_upload_manager", lambda chatbot_name: upload_manager)

    response = await client.get("/free-admin/users")

    payload = await response.get_json()
    assert response.status_code == 200
    # Expired accounts stay in the listing (the admin page splits them into its archive tab)
    # and every row carries the expiry state the tab bar and countdown are rendered from.
    active_user, expired_user = payload["users"]
    assert active_user == {
        "displayName": "Test User",
        "email": "user@example.com",
        "createdAt": active_created_at,
        "updatedAt": "2026-03-31T11:00:00+00:00",
        "uploadCount": 1,
        "uploadedFiles": ["sample.pdf"],
        "expiresAt": active_user["expiresAt"],
        "isExpired": False,
        "daysRemaining": free_auth.FREE_ACCOUNT_LIFETIME_DAYS - 2,
        "daysExpired": 0,
    }
    assert expired_user["email"] == "lapsed@example.com"
    assert expired_user["isExpired"] is True
    assert expired_user["daysRemaining"] == 0
    assert expired_user["daysExpired"] == 5


@pytest.mark.asyncio
async def test_free_admin_user_delete_removes_uploads_and_account(client, monkeypatch):
    await login_internal_admin(client)
    auth_service = client.app.config[app.CONFIG_FREE_AUTH_SERVICE]
    upload_manager = mock.AsyncMock()
    upload_manager.remove_all_files.return_value = (["deleted.pdf"], [])

    async def mock_delete_account(email: str):
        assert email == "user@example.com"
        return True

    monkeypatch.setattr(app, "get_chatbot_upload_manager", lambda chatbot_name: upload_manager)
    monkeypatch.setattr(auth_service, "delete_account", mock_delete_account)

    response = await client.delete("/free-admin/users/user%40example.com")

    payload = await response.get_json()
    assert response.status_code == 200
    assert payload == {
        "message": "nerilio user deleted successfully.",
        "deletedUploadCount": 1,
    }
    upload_manager.remove_all_files.assert_awaited_once_with(user_identifier="user@example.com")


@pytest.mark.asyncio
async def test_free_admin_user_password_reset_updates_account(client, monkeypatch):
    await login_internal_admin(client)
    auth_service = client.app.config[app.CONFIG_FREE_AUTH_SERVICE]

    async def mock_reset_account_password(**kwargs):
        assert kwargs["email"] == "user@example.com"
        assert kwargs["password"] == "new-secret"
        assert kwargs["confirm_password"] == "new-secret"
        return SimpleNamespace(email="user@example.com", updated_at="2026-03-31T12:00:00+00:00")

    monkeypatch.setattr(auth_service, "reset_account_password", mock_reset_account_password)

    response = await client.post(
        "/free-admin/users/user%40example.com/password",
        json={"password": "new-secret", "confirmPassword": "new-secret"},
    )

    payload = await response.get_json()
    assert response.status_code == 200
    assert payload == {
        "message": "nerilio user password updated successfully.",
        "email": "user@example.com",
        "updatedAt": "2026-03-31T12:00:00+00:00",
    }


@pytest.mark.asyncio
async def test_free_admin_user_reactivate_opens_a_new_window(client, monkeypatch):
    await login_internal_admin(client)
    auth_service = client.app.config[app.CONFIG_FREE_AUTH_SERVICE]
    now = datetime.now(timezone.utc)

    async def mock_reactivate_account(**kwargs):
        assert kwargs["email"] == "user@example.com"
        return SimpleNamespace(
            display_name="Test User",
            email="user@example.com",
            created_at=free_auth.format_utc(now - timedelta(days=90)),
            updated_at=free_auth.format_utc(now),
            expires_at=free_auth.format_utc(now + timedelta(days=free_auth.FREE_ACCOUNT_LIFETIME_DAYS)),
        )

    monkeypatch.setattr(auth_service, "reactivate_account", mock_reactivate_account)

    response = await client.post("/free-admin/users/user%40example.com/reactivate")

    payload = await response.get_json()
    assert response.status_code == 200
    assert payload["email"] == "user@example.com"
    assert payload["isExpired"] is False
    assert payload["daysRemaining"] == free_auth.FREE_ACCOUNT_LIFETIME_DAYS
    assert payload["daysExpired"] == 0


@pytest.mark.asyncio
async def test_free_admin_user_reactivate_requires_admin_session(client):
    response = await client.post("/free-admin/users/user%40example.com/reactivate")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_chat_rak_applies_user_filter_from_simple_auth_session(client, monkeypatch):
    await login_simple_chatbot(client, "rak", "12345", "rak99#")
    prompt_store = client.app.config[app.CONFIG_CHATBOT_PROMPT_STORE]

    async def mock_load_prompt(_chatbot_name: str):
        return None

    monkeypatch.setattr(prompt_store, "load_prompt", mock_load_prompt)

    response = await client.post(
        "/chat",
        headers={"X-Chatbot-User": "12345"},
        json={
            "messages": [{"content": "What is the capital of France?", "role": "user"}],
            "context": {
                "overrides": {
                    "retrieval_mode": "text",
                    "include_category": "rak",
                }
            },
        },
    )

    assert response.status_code == 200
    assert client.app.config[app.CONFIG_SEARCH_CLIENT].filter == "category eq 'rak' and user eq '12345'"


@pytest.mark.asyncio
async def test_internal_chat_requires_source_bot_selection(client):
    response = await client.post(
        "/chat",
        headers={"X-Chatbot-Name": "internal"},
        json={
            "messages": [{"content": "What is the capital of France?", "role": "user"}],
            "context": {"overrides": {"retrieval_mode": "text"}},
        },
    )

    assert response.status_code == 400
    assert await response.get_json() == {"error": "Internal Bot requires a source bot selection."}


@pytest.mark.asyncio
@pytest.mark.parametrize("source_chatbot", ["free", "hyrox-assessment"])
async def test_internal_chat_rejects_invalid_source_bot(client, source_chatbot):
    response = await client.post(
        "/chat",
        headers={"X-Chatbot-Name": "internal"},
        json={
            "messages": [{"content": "What is the capital of France?", "role": "user"}],
            "context": {"overrides": {"retrieval_mode": "text", "source_chatbot": source_chatbot}},
        },
    )

    assert response.status_code == 400
    assert await response.get_json() == {"error": "Internal Bot source bot is invalid."}


@pytest.mark.asyncio
async def test_internal_chat_uses_selected_source_bot_for_prompt_and_category(client):
    await login_simple_chatbot(client, "internal", "internal", "internal")
    prompt_store = client.app.config[app.CONFIG_CHATBOT_PROMPT_STORE]

    async def mock_load_prompt(_chatbot_name: str):
        return None

    with mock.patch.object(prompt_store, "load_prompt", mock_load_prompt):
        response = await client.post(
            "/chat",
            headers={"X-Chatbot-Name": "internal"},
            json={
                "messages": [{"content": "What is the capital of France?", "role": "user"}],
                "context": {"overrides": {"retrieval_mode": "text", "source_chatbot": "lemon"}},
            },
        )

        assert response.status_code == 200
        result = await response.get_json()
        assert client.app.config[app.CONFIG_SEARCH_CLIENT].filter == "category eq 'lemon'"
        assert "info@lemon-systems.de" in result["context"]["thoughts"][3]["description"][0]["content"]


@pytest.mark.asyncio
async def test_chat_handle_exception(client, monkeypatch, snapshot, caplog):
    monkeypatch.setattr(
        "approaches.chatreadretrieveread.ChatReadRetrieveReadApproach.run",
        mock.Mock(side_effect=ZeroDivisionError("something bad happened")),
    )

    response = await client.post(
        "/chat",
        json={"messages": [{"content": "What is the capital of France?", "role": "user"}]},
    )
    assert response.status_code == 500
    result = await response.get_json()
    assert "Exception in /chat: something bad happened" in caplog.text
    snapshot.assert_match(json.dumps(result, indent=4), "result.json")


@pytest.mark.asyncio
async def test_chat_stream_handle_exception(client, monkeypatch, snapshot, caplog):
    monkeypatch.setattr(
        "approaches.chatreadretrieveread.ChatReadRetrieveReadApproach.run_stream",
        mock.Mock(side_effect=ZeroDivisionError("something bad happened")),
    )

    response = await client.post(
        "/chat/stream",
        json={"messages": [{"content": "What is the capital of France?", "role": "user"}]},
    )
    assert response.status_code == 500
    result = await response.get_json()
    assert "Exception in /chat: something bad happened" in caplog.text
    snapshot.assert_match(json.dumps(result, indent=4), "result.json")


@pytest.mark.asyncio
async def test_chat_handle_exception_contentsafety(client, monkeypatch, snapshot, caplog):
    monkeypatch.setattr(
        "approaches.chatreadretrieveread.ChatReadRetrieveReadApproach.run",
        mock.Mock(side_effect=filtered_response),
    )

    response = await client.post(
        "/chat",
        json={"messages": [{"content": "How do I do something bad?", "role": "user"}]},
    )
    assert response.status_code == 400
    result = await response.get_json()
    assert "Exception in /chat: The response was filtered" in caplog.text
    snapshot.assert_match(json.dumps(result, indent=4), "result.json")


@pytest.mark.asyncio
async def test_chat_handle_exception_contentsafety_localized(client, monkeypatch, caplog):
    monkeypatch.setattr(
        "approaches.chatreadretrieveread.ChatReadRetrieveReadApproach.run",
        mock.Mock(side_effect=filtered_response),
    )

    response = await client.post(
        "/chat",
        json={
            "messages": [{"content": "How do I do something bad?", "role": "user"}],
            "context": {"overrides": {"language": "de-DE"}},
        },
    )
    assert response.status_code == 400
    result = await response.get_json()
    assert "Exception in /chat: The response was filtered" in caplog.text
    assert result["error"] == "Deine Nachricht enthält Inhalte, die vom OpenAI-Inhaltsfilter markiert wurden."


@pytest.mark.asyncio
async def test_chat_handle_exception_streaming(client, monkeypatch, snapshot, caplog):
    chat_client = client.app.config[app.CONFIG_OPENAI_CLIENT]
    monkeypatch.setattr(
        chat_client.chat.completions, "create", mock.Mock(side_effect=ZeroDivisionError("something bad happened"))
    )

    response = await client.post(
        "/chat/stream",
        json={"messages": [{"content": "What is the capital of France?", "role": "user"}]},
    )
    assert response.status_code == 200
    assert "Exception while generating response stream: something bad happened" in caplog.text
    result = await response.get_data()
    snapshot.assert_match(result, "result.jsonlines")


@pytest.mark.asyncio
async def test_chat_handle_exception_contentsafety_streaming(client, monkeypatch, snapshot, caplog):
    chat_client = client.app.config[app.CONFIG_OPENAI_CLIENT]
    monkeypatch.setattr(chat_client.chat.completions, "create", mock.Mock(side_effect=filtered_response))

    response = await client.post(
        "/chat/stream",
        json={"messages": [{"content": "How do I do something bad?", "role": "user"}]},
    )
    assert response.status_code == 200
    assert "Exception while generating response stream: The response was filtered" in caplog.text
    result = await response.get_data()
    snapshot.assert_match(result, "result.jsonlines")


@pytest.mark.asyncio
async def test_chat_handle_exception_contentsafety_streaming_chatbot_override(client, monkeypatch, caplog):
    await login_simple_chatbot(client, "fhg", "fhg", "1nnsbruck#")
    chat_client = client.app.config[app.CONFIG_OPENAI_CLIENT]
    prompt_store = client.app.config[app.CONFIG_CHATBOT_PROMPT_STORE]

    async def mock_load_prompt(_chatbot_name: str):
        return None

    monkeypatch.setattr(prompt_store, "load_prompt", mock_load_prompt)
    monkeypatch.setattr(chat_client.chat.completions, "create", mock.Mock(side_effect=filtered_response))
    monkeypatch.setattr(
        "approaches.chatbot_content_filter_registry.load_chatbot_content_filter_messages",
        lambda chatbot_name: {"nl": "Dit is een FHG-specifiek contentfilterbericht."} if chatbot_name == "fhg" else {},
    )

    response = await client.post(
        "/chat/stream",
        json={
            "messages": [{"content": "How do I do something bad?", "role": "user"}],
            "context": {"overrides": {"include_category": "fhg", "language": "nl-NL"}},
        },
    )
    assert response.status_code == 200
    assert "Exception while generating response stream: The response was filtered" in caplog.text
    result = await response.get_data()
    assert result == b'{"error": "Dit is een FHG-specifiek contentfilterbericht."}'


@pytest.mark.asyncio
async def test_speech(client, mock_speech_success):
    response = await client.post(
        "/speech",
        json={
            "text": "test",
        },
    )
    assert response.status_code == 200
    assert await response.get_data() == b"mock_audio_data"


@pytest.mark.asyncio
async def test_speech_token_refresh(client_with_expiring_token, mock_speech_success):
    # First time should create a brand new token
    response = await client_with_expiring_token.post(
        "/speech",
        json={
            "text": "test",
        },
    )
    assert response.status_code == 200
    assert await response.get_data() == b"mock_audio_data"

    response = await client_with_expiring_token.post(
        "/speech",
        json={
            "text": "test",
        },
    )
    assert response.status_code == 200
    assert await response.get_data() == b"mock_audio_data"

    response = await client_with_expiring_token.post(
        "/speech",
        json={
            "text": "test",
        },
    )
    assert response.status_code == 200
    assert await response.get_data() == b"mock_audio_data"


@pytest.mark.asyncio
async def test_speech_request_must_be_json(client, mock_speech_success):
    response = await client.post("/speech")
    assert response.status_code == 415
    result = await response.get_json()
    assert result["error"] == "request must be json"


@pytest.mark.asyncio
async def test_speech_request_cancelled(client, mock_speech_cancelled):
    response = await client.post(
        "/speech",
        json={
            "text": "test",
        },
    )
    assert response.status_code == 500
    result = await response.get_json()
    assert result["error"] == "Speech synthesis canceled. Check logs for details."


@pytest.mark.asyncio
async def test_speech_request_failed(client, mock_speech_failed):
    response = await client.post(
        "/speech",
        json={
            "text": "test",
        },
    )
    assert response.status_code == 500
    result = await response.get_json()
    assert result["error"] == "Speech synthesis failed. Check logs for details."


@pytest.mark.asyncio
async def test_chat_text(client, snapshot):
    response = await client.post(
        "/chat",
        json={
            "messages": [{"content": "What is the capital of France?", "role": "user"}],
            "context": {
                "overrides": {"retrieval_mode": "text"},
            },
        },
    )
    assert response.status_code == 200
    result = await response.get_json()
    assert result["context"]["thoughts"][1]["props"]["use_text_search"] is True
    assert result["context"]["thoughts"][1]["props"]["use_vector_search"] is False
    assert result["context"]["thoughts"][1]["props"]["use_semantic_ranker"] is False
    snapshot.assert_match(json.dumps(result, indent=4), "result.json")


@pytest.mark.asyncio
async def test_chat_text_agent(knowledgebase_client, snapshot):
    response = await knowledgebase_client.post(
        "/chat",
        json={
            "messages": [{"content": "What is the capital of France?", "role": "user"}],
            "context": {
                "overrides": {"use_agentic_knowledgebase": True},
            },
        },
    )
    assert response.status_code == 200
    result = await response.get_json()
    assert result["context"]["thoughts"][0]["props"]["reranker_threshold"] == 0
    snapshot.assert_match(json.dumps(result, indent=4), "result.json")


@pytest.mark.asyncio
async def test_chat_text_filter(auth_client, snapshot):
    response = await auth_client.post(
        "/chat",
        headers={"Authorization": "Bearer MockToken"},
        json={
            "messages": [{"content": "What is the capital of France?", "role": "user"}],
            "context": {
                "overrides": {
                    "retrieval_mode": "text",
                    "exclude_category": "excluded",
                },
            },
        },
    )
    assert response.status_code == 200
    assert auth_client.config[app.CONFIG_SEARCH_CLIENT].filter == "category ne 'excluded'"
    assert auth_client.config[app.CONFIG_SEARCH_CLIENT].access_token == "MockToken"
    result = await response.get_json()
    snapshot.assert_match(json.dumps(result, indent=4), "result.json")


@pytest.mark.asyncio
async def test_chat_text_filter_agent(knowledgebase_auth_client, snapshot):
    response = await knowledgebase_auth_client.post(
        "/chat",
        headers={"Authorization": "Bearer MockToken"},
        json={
            "messages": [{"content": "What is the capital of France?", "role": "user"}],
            "context": {
                "overrides": {
                    "use_agentic_knowledgebase": True,
                    "exclude_category": "excluded",
                },
            },
        },
    )
    assert response.status_code == 200
    assert knowledgebase_auth_client.config[app.CONFIG_KNOWLEDGEBASE_CLIENT].filter == "category ne 'excluded'"
    assert knowledgebase_auth_client.config[app.CONFIG_KNOWLEDGEBASE_CLIENT].access_token == "MockToken"
    result = await response.get_json()
    snapshot.assert_match(json.dumps(result, indent=4), "result.json")


@pytest.mark.asyncio
async def test_chat_text_filter_public_documents(auth_public_documents_client, snapshot):
    response = await auth_public_documents_client.post(
        "/chat",
        headers={"Authorization": "Bearer MockToken"},
        json={
            "messages": [{"content": "What is the capital of France?", "role": "user"}],
            "context": {
                "overrides": {
                    "retrieval_mode": "text",
                    "exclude_category": "excluded",
                },
            },
        },
    )
    assert response.status_code == 200
    assert auth_public_documents_client.config[app.CONFIG_SEARCH_CLIENT].filter == "category ne 'excluded'"
    assert auth_public_documents_client.config[app.CONFIG_SEARCH_CLIENT].access_token == "MockToken"
    result = await response.get_json()
    if result.get("session_state"):
        del result["session_state"]
    snapshot.assert_match(json.dumps(result, indent=4), "result.json")


@pytest.mark.asyncio
async def test_chat_text_semanticranker(client, snapshot):
    response = await client.post(
        "/chat",
        json={
            "messages": [{"content": "What is the capital of France?", "role": "user"}],
            "context": {
                "overrides": {"retrieval_mode": "text", "semantic_ranker": True},
            },
        },
    )
    assert response.status_code == 200
    result = await response.get_json()
    snapshot.assert_match(json.dumps(result, indent=4), "result.json")


@pytest.mark.asyncio
async def test_chat_text_semanticcaptions(client, snapshot):
    response = await client.post(
        "/chat",
        json={
            "messages": [{"content": "What is the capital of France?", "role": "user"}],
            "context": {
                "overrides": {"retrieval_mode": "text", "semantic_captions": True},
            },
        },
    )
    assert response.status_code == 200
    result = await response.get_json()
    snapshot.assert_match(json.dumps(result, indent=4), "result.json")


@pytest.mark.asyncio
async def test_chat_prompt_template(client, snapshot):
    response = await client.post(
        "/chat",
        json={
            "messages": [{"content": "What is the capital of France?", "role": "user"}],
            "context": {
                "overrides": {"retrieval_mode": "text", "prompt_template": "You are a cat."},
            },
        },
    )
    assert response.status_code == 200
    result = await response.get_json()
    assert result["context"]["thoughts"][3]["description"][0]["content"].startswith("You are a cat.")
    snapshot.assert_match(json.dumps(result, indent=4), "result.json")


@pytest.mark.asyncio
async def test_chat_seed(client, snapshot):
    response = await client.post(
        "/chat",
        json={
            "messages": [{"content": "What is the capital of France?", "role": "user"}],
            "context": {
                "overrides": {"seed": 42},
            },
        },
    )
    assert response.status_code == 200
    result = await response.get_json()
    snapshot.assert_match(json.dumps(result, indent=4), "result.json")


@pytest.mark.asyncio
async def test_chat_hybrid(client, snapshot):
    response = await client.post(
        "/chat",
        json={
            "messages": [{"content": "What is the capital of France?", "role": "user"}],
            "context": {
                "overrides": {"retrieval_mode": "hybrid"},
            },
        },
    )
    assert response.status_code == 200
    result = await response.get_json()
    assert result["context"]["thoughts"][1]["props"]["use_text_search"] is True
    assert result["context"]["thoughts"][1]["props"]["use_vector_search"] is True
    assert result["context"]["thoughts"][1]["props"]["use_semantic_ranker"] is False
    assert result["context"]["thoughts"][1]["props"]["use_semantic_captions"] is False
    snapshot.assert_match(json.dumps(result, indent=4), "result.json")


@pytest.mark.asyncio
async def test_chat_hybrid_semantic_ranker(client, snapshot):
    response = await client.post(
        "/chat",
        json={
            "messages": [{"content": "What is the capital of France?", "role": "user"}],
            "context": {
                "overrides": {
                    "retrieval_mode": "hybrid",
                    "semantic_ranker": True,
                },
            },
        },
    )
    assert response.status_code == 200
    result = await response.get_json()
    assert result["context"]["thoughts"][1]["props"]["use_text_search"] is True
    assert result["context"]["thoughts"][1]["props"]["use_vector_search"] is True
    assert result["context"]["thoughts"][1]["props"]["use_semantic_ranker"] is True
    assert result["context"]["thoughts"][1]["props"]["use_semantic_captions"] is False
    snapshot.assert_match(json.dumps(result, indent=4), "result.json")


@pytest.mark.asyncio
async def test_chat_hybrid_semantic_captions(client, snapshot):
    response = await client.post(
        "/chat",
        json={
            "messages": [{"content": "What is the capital of France?", "role": "user"}],
            "context": {
                "overrides": {
                    "retrieval_mode": "hybrid",
                    "semantic_ranker": True,
                    "semantic_captions": True,
                },
            },
        },
    )
    assert response.status_code == 200
    result = await response.get_json()
    assert result["context"]["thoughts"][1]["props"]["use_text_search"] is True
    assert result["context"]["thoughts"][1]["props"]["use_vector_search"] is True
    assert result["context"]["thoughts"][1]["props"]["use_semantic_ranker"] is True
    assert result["context"]["thoughts"][1]["props"]["use_semantic_captions"] is True
    snapshot.assert_match(json.dumps(result, indent=4), "result.json")


@pytest.mark.asyncio
async def test_chat_vector(client, snapshot):
    response = await client.post(
        "/chat",
        json={
            "messages": [{"content": "What is the capital of France?", "role": "user"}],
            "context": {
                "overrides": {"retrieval_mode": "vectors"},
            },
        },
    )
    assert response.status_code == 200
    result = await response.get_json()
    assert result["context"]["thoughts"][1]["props"]["use_text_search"] is False
    assert result["context"]["thoughts"][1]["props"]["use_vector_search"] is True
    assert result["context"]["thoughts"][1]["props"]["use_semantic_ranker"] is False
    snapshot.assert_match(json.dumps(result, indent=4), "result.json")


@pytest.mark.asyncio
async def test_chat_vector_semantic_ranker(client, snapshot):
    response = await client.post(
        "/chat",
        json={
            "messages": [{"content": "What is the capital of France?", "role": "user"}],
            "context": {
                "overrides": {
                    "retrieval_mode": "vectors",
                    "semantic_ranker": True,
                },
            },
        },
    )
    assert response.status_code == 200
    result = await response.get_json()
    assert result["context"]["thoughts"][1]["props"]["use_text_search"] is False
    assert result["context"]["thoughts"][1]["props"]["use_vector_search"] is True
    assert result["context"]["thoughts"][1]["props"]["use_semantic_ranker"] is True
    snapshot.assert_match(json.dumps(result, indent=4), "result.json")


@pytest.mark.asyncio
async def test_chat_text_semantic_ranker(client, snapshot):
    response = await client.post(
        "/chat",
        json={
            "messages": [{"content": "What is the capital of France?", "role": "user"}],
            "context": {
                "overrides": {"retrieval_mode": "text", "semantic_ranker": True},
            },
        },
    )
    assert response.status_code == 200
    result = await response.get_json()
    assert result["context"]["thoughts"][1]["props"]["use_text_search"] is True
    assert result["context"]["thoughts"][1]["props"]["use_vector_search"] is False
    assert result["context"]["thoughts"][1]["props"]["use_semantic_ranker"] is True
    snapshot.assert_match(json.dumps(result, indent=4), "result.json")


@pytest.mark.asyncio
async def test_chat_stream_text(client, snapshot):
    response = await client.post(
        "/chat/stream",
        json={
            "messages": [{"content": "What is the capital of France?", "role": "user"}],
            "context": {
                "overrides": {"retrieval_mode": "text"},
            },
        },
    )
    assert response.status_code == 200
    result = await response.get_data()
    snapshot.assert_match(result, "result.jsonlines")


@pytest.mark.asyncio
async def test_chat_text_reasoning(reasoning_client, snapshot):
    response = await reasoning_client.post(
        "/chat",
        json={
            "messages": [{"content": "What is the capital of France?", "role": "user"}],
            "context": {
                "overrides": {"retrieval_mode": "text"},
            },
        },
    )
    assert response.status_code == 200
    result = await response.get_json()
    assert result["context"]["thoughts"][0]["props"]["token_usage"] is not None
    assert result["context"]["thoughts"][0]["props"]["reasoning_effort"] is not None
    assert result["context"]["thoughts"][3]["props"]["token_usage"] is not None
    assert result["context"]["thoughts"][3]["props"]["token_usage"]["reasoning_tokens"] > 0
    assert result["context"]["thoughts"][3]["props"]["reasoning_effort"] == os.getenv("AZURE_OPENAI_REASONING_EFFORT")

    snapshot.assert_match(json.dumps(result, indent=4), "result.json")


@pytest.mark.asyncio
async def test_chat_stream_text_reasoning(reasoning_client, snapshot):
    response = await reasoning_client.post(
        "/chat/stream",
        json={
            "messages": [{"content": "What is the capital of France?", "role": "user"}],
            "context": {
                "overrides": {"retrieval_mode": "text"},
            },
        },
    )
    assert response.status_code == 200
    result = await response.get_data()
    snapshot.assert_match(result, "result.jsonlines")


@pytest.mark.asyncio
async def test_chat_stream_text_filter(auth_client, snapshot):
    response = await auth_client.post(
        "/chat/stream",
        headers={"Authorization": "Bearer MockToken"},
        json={
            "messages": [{"content": "What is the capital of France?", "role": "user"}],
            "context": {
                "overrides": {
                    "retrieval_mode": "text",
                    "exclude_category": "excluded",
                }
            },
        },
    )
    assert response.status_code == 200
    assert auth_client.config[app.CONFIG_SEARCH_CLIENT].filter == "category ne 'excluded'"
    assert auth_client.config[app.CONFIG_SEARCH_CLIENT].access_token == "MockToken"
    result = await response.get_data()
    snapshot.assert_match(result, "result.jsonlines")


@pytest.mark.asyncio
async def test_chat_with_history(client, snapshot):
    response = await client.post(
        "/chat",
        json={
            "messages": [
                {"content": "What happens in a performance review?", "role": "user"},
                {
                    "content": "During a performance review, employees will receive feedback on their performance over the past year, including both successes and areas for improvement. The feedback will be provided by the employee's supervisor and is intended to help the employee develop and grow in their role [employee_handbook-3.pdf]. The review is a two-way dialogue between the employee and their manager, so employees are encouraged to be honest and open during the process [employee_handbook-3.pdf]. The employee will also have the opportunity to discuss their goals and objectives for the upcoming year [employee_handbook-3.pdf]. A written summary of the performance review will be provided to the employee, which will include a rating of their performance, feedback, and goals and objectives for the upcoming year [employee_handbook-3.pdf].",
                    "role": "assistant",
                },
                {"content": "Is dental covered?", "role": "user"},
            ],
            "context": {
                "overrides": {"retrieval_mode": "text"},
            },
        },
    )
    assert response.status_code == 200
    result = await response.get_json()
    assert messages_contains_text(result["context"]["thoughts"][3]["description"], "performance review")
    snapshot.assert_match(json.dumps(result, indent=4), "result.json")


@pytest.mark.asyncio
async def test_chat_session_state_persists(client, snapshot):
    response = await client.post(
        "/chat",
        json={
            "messages": [{"content": "What is the capital of France?", "role": "user"}],
            "context": {
                "overrides": {"retrieval_mode": "text"},
            },
            "session_state": {"conversation_id": 1234},
        },
    )
    assert response.status_code == 200
    result = await response.get_json()
    snapshot.assert_match(json.dumps(result, indent=4), "result.json")


@pytest.mark.asyncio
async def test_chat_stream_session_state_persists(client, snapshot):
    response = await client.post(
        "/chat/stream",
        json={
            "messages": [{"content": "What is the capital of France?", "role": "user"}],
            "context": {
                "overrides": {"retrieval_mode": "text"},
            },
            "session_state": {"conversation_id": 1234},
        },
    )
    assert response.status_code == 200
    result = await response.get_data()
    snapshot.assert_match(result, "result.jsonlines")


@pytest.mark.asyncio
async def test_chat_followup(client, snapshot):
    response = await client.post(
        "/chat",
        json={
            "messages": [{"content": "What is the capital of France?", "role": "user"}],
            "context": {
                "overrides": {
                    "suggest_followup_questions": True,
                },
            },
        },
    )
    assert response.status_code == 200
    result = await response.get_json()
    assert result["context"]["followup_questions"][0] == "What is the capital of Spain?"

    snapshot.assert_match(json.dumps(result, indent=4), "result.json")


@pytest.mark.asyncio
async def test_chat_stream_followup(client, snapshot):
    response = await client.post(
        "/chat/stream",
        json={
            "messages": [{"content": "What is the capital of France?", "role": "user"}],
            "context": {
                "overrides": {
                    "suggest_followup_questions": True,
                },
            },
        },
    )
    assert response.status_code == 200
    result = await response.get_data()
    snapshot.assert_match(result, "result.jsonlines")


@pytest.mark.asyncio
async def test_chat_vision(monkeypatch, vision_client, snapshot):
    response = await vision_client.post(
        "/chat",
        json={"messages": [{"content": "Are interest rates high?", "role": "user"}]},
    )
    assert response.status_code == 200
    result = await response.get_json()
    snapshot.assert_match(json.dumps(result, indent=4), "result.json")


@pytest.mark.asyncio
async def test_chat_stream_vision(vision_client, snapshot):
    response = await vision_client.post(
        "/chat/stream",
        json={"messages": [{"content": "Are interest rates high?", "role": "user"}]},
    )
    assert response.status_code == 200
    result = await response.get_data()
    snapshot.assert_match(result, "result.jsonlines")


@pytest.mark.asyncio
async def test_chat_vision_user(monkeypatch, vision_auth_client, mock_user_directory_client, snapshot):
    response = await vision_auth_client.post(
        "/chat",
        headers={"Authorization": "Bearer MockToken"},
        json={"messages": [{"content": "Flowers in westbrae nursery logo?", "role": "user"}]},
    )

    assert response.status_code == 200
    result = await response.get_json()
    snapshot.assert_match(json.dumps(result, indent=4), "result.json")


@pytest.mark.asyncio
async def test_format_as_ndjson():
    async def gen():
        yield {"a": "I ❤️ 🐍"}
        yield {"b": "Newlines inside \n strings are fine"}

    result = [line async for line in app.format_as_ndjson(gen())]
    assert result == ['{"a": "I ❤️ 🐍"}\n', '{"b": "Newlines inside \\n strings are fine"}\n']


def test_bbsa_is_wired_consistently_across_the_backend_registries():
    """A new built-in bot has to land in four independent places or it half-works: the route gate,
    the prompt registry, the embed ID map, and the widget launcher palette. Fixture-free on purpose
    so it runs without the app client."""
    from approaches.chatbot_config_registry import get_chatbot_config
    from approaches.chatbot_prompt_registry import get_registered_chatbot_names
    from embed_public_ids import EMBED_PUBLIC_IDS, is_embeddable, resolve_public_id

    # /<chatbot_name> gates on this set; a missing name redirects to "/" even with a frontend route.
    assert "bbsa" in app.KNOWN_CHATBOT_NAMES
    # "bbsa" must not collide with a reserved (non-chatbot) frontend prefix such as "admin".
    assert "bbsa" not in app.NON_CHATBOT_FRONTEND_PREFIXES

    assert "bbsa" in get_registered_chatbot_names()
    config = get_chatbot_config("bbsa")
    assert config is not None and config.language_locale == "German" and config.citation_target == "url"

    # Public + embeddable: a committed, stable public ID that round-trips.
    assert is_embeddable("bbsa")
    public_id = app.get_public_id("bbsa")
    assert public_id == EMBED_PUBLIC_IDS["bbsa"]
    assert PUBLIC_ID_RE.match(public_id)
    assert resolve_public_id(public_id) == "bbsa"

    # The launcher bubble is the brand dark teal, not the (white) visible navbar — a white bubble
    # would be invisible on a host page.
    assert app.EMBED_LAUNCHER_COLORS["bbsa"] == "#032D3C"

    # General invariant this bot must not break: every bot with a prompt module is routable.
    # ("internal" and "public-test" are the documented exceptions in the other direction.)
    assert set(get_registered_chatbot_names()) <= app.KNOWN_CHATBOT_NAMES


@pytest.mark.asyncio
async def test_bbsa_route_serves_the_spa_and_locks_framing_to_its_whitelist(client, monkeypatch):
    embed_store = client.app.config[app.CONFIG_CHATBOT_EMBED_CONFIG_STORE]

    async def mock_load_allowed_rules(chatbot_name: str):
        assert chatbot_name == "bbsa"
        return ["*.breitband.tirol"]

    monkeypatch.setattr(embed_store, "load_allowed_rules", mock_load_allowed_rules)

    response = await client.get("/bbsa")
    assert response.status_code == 200
    assert response.headers.get("Content-Security-Policy") == "frame-ancestors 'self' *.breitband.tirol"


@pytest.mark.asyncio
async def test_bbsa_embed_route_resolves_its_public_id(client, monkeypatch):
    embed_store = client.app.config[app.CONFIG_CHATBOT_EMBED_CONFIG_STORE]

    async def mock_load_allowed_rules(chatbot_name: str):
        assert chatbot_name == "bbsa"
        return []

    monkeypatch.setattr(embed_store, "load_allowed_rules", mock_load_allowed_rules)

    response = await client.get(f"/embed/{app.get_public_id('bbsa')}/config")
    assert response.status_code == 200
    payload = await response.get_json()
    assert payload["primaryColor"] == app.EMBED_LAUNCHER_COLORS["bbsa"]
    # The readable route name never leaves the backend on the embed surface.
    assert "bbsa" not in (await response.get_data()).decode()
