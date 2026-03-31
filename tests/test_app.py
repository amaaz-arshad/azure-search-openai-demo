import json
import os
from typing import Any
from types import SimpleNamespace
from unittest import mock

import pytest
import quart.testing.app
from httpx import Request, Response
from openai import BadRequestError
from quart import Response as QuartResponse

import app


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
async def test_public_test_signup_starts_verification(client, monkeypatch):
    auth_service = client.app.config[app.CONFIG_PUBLIC_TEST_AUTH_SERVICE]

    async def mock_start_signup(**kwargs):
        assert kwargs["display_name"] == "Test User"
        assert kwargs["email"] == "user@example.com"
        return SimpleNamespace(email="user@example.com", expires_in_seconds=900)

    monkeypatch.setattr(auth_service, "start_signup", mock_start_signup)

    response = await client.post(
        "/public-test-auth/signup",
        json={
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
async def test_public_test_signup_verify_sets_session_cookie(client, monkeypatch):
    auth_service = client.app.config[app.CONFIG_PUBLIC_TEST_AUTH_SERVICE]

    async def mock_verify_signup(**kwargs):
        assert kwargs["email"] == "user@example.com"
        assert kwargs["verification_code"] == "123456"
        return app.PublicTestSession(display_name="Test User", email="user@example.com")

    monkeypatch.setattr(auth_service, "verify_signup", mock_verify_signup)

    response = await client.post(
        "/public-test-auth/signup/verify",
        json={
            "email": "user@example.com",
            "verificationCode": "123456",
        },
    )

    payload = await response.get_json()
    assert response.status_code == 200
    assert payload["session"] == {"displayName": "Test User", "email": "user@example.com"}
    assert auth_service.session_cookie_name in response.headers["Set-Cookie"]


@pytest.mark.asyncio
async def test_public_test_password_reset_starts_verification(client, monkeypatch):
    auth_service = client.app.config[app.CONFIG_PUBLIC_TEST_AUTH_SERVICE]

    async def mock_start_password_reset(**kwargs):
        assert kwargs["email"] == "user@example.com"
        return SimpleNamespace(email="user@example.com", expires_in_seconds=900)

    monkeypatch.setattr(auth_service, "start_password_reset", mock_start_password_reset)

    response = await client.post(
        "/public-test-auth/password-reset",
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
async def test_public_test_password_reset_verify_sets_session_cookie(client, monkeypatch):
    auth_service = client.app.config[app.CONFIG_PUBLIC_TEST_AUTH_SERVICE]

    async def mock_verify_password_reset(**kwargs):
        assert kwargs["email"] == "user@example.com"
        assert kwargs["verification_code"] == "123456"
        assert kwargs["password"] == "new-secret"
        assert kwargs["confirm_password"] == "new-secret"
        return app.PublicTestSession(display_name="Test User", email="user@example.com")

    monkeypatch.setattr(auth_service, "verify_password_reset", mock_verify_password_reset)

    response = await client.post(
        "/public-test-auth/password-reset/verify",
        json={
            "email": "user@example.com",
            "verificationCode": "123456",
            "password": "new-secret",
            "confirmPassword": "new-secret",
        },
    )

    payload = await response.get_json()
    assert response.status_code == 200
    assert payload["session"] == {"displayName": "Test User", "email": "user@example.com"}
    assert auth_service.session_cookie_name in response.headers["Set-Cookie"]


@pytest.mark.asyncio
async def test_public_test_password_reset_resend_returns_error_key(client, monkeypatch):
    auth_service = client.app.config[app.CONFIG_PUBLIC_TEST_AUTH_SERVICE]

    async def mock_resend_password_reset_code(**kwargs):
        raise app.PublicTestAuthError("authErrors.passwordResetSessionNotFound", status_code=404)

    monkeypatch.setattr(auth_service, "resend_password_reset_code", mock_resend_password_reset_code)

    response = await client.post(
        "/public-test-auth/password-reset/resend",
        json={
            "email": "user@example.com",
        },
    )

    payload = await response.get_json()
    assert response.status_code == 404
    assert payload == {"errorKey": "authErrors.passwordResetSessionNotFound"}


@pytest.mark.asyncio
async def test_public_test_login_returns_error_key(client, monkeypatch):
    auth_service = client.app.config[app.CONFIG_PUBLIC_TEST_AUTH_SERVICE]

    async def mock_login_user(**kwargs):
        raise app.PublicTestAuthError("authErrors.invalidCredentials", status_code=401)

    monkeypatch.setattr(auth_service, "login_user", mock_login_user)

    response = await client.post(
        "/public-test-auth/login",
        json={
            "email": "user@example.com",
            "password": "wrong-password",
        },
    )

    payload = await response.get_json()
    assert response.status_code == 401
    assert payload == {"errorKey": "authErrors.invalidCredentials"}


@pytest.mark.asyncio
async def test_public_test_session_returns_authenticated_user(client, monkeypatch):
    async def mock_get_authenticated_public_test_user():
        return app.PublicTestSession(display_name="Stored User", email="stored@example.com")

    monkeypatch.setattr(app, "get_authenticated_public_test_user", mock_get_authenticated_public_test_user)

    response = await client.get("/public-test-auth/session")

    payload = await response.get_json()
    assert response.status_code == 200
    assert payload["session"] == {"displayName": "Stored User", "email": "stored@example.com"}


@pytest.mark.asyncio
async def test_public_test_admin_users_lists_accounts(client, monkeypatch):
    auth_service = client.app.config[app.CONFIG_PUBLIC_TEST_AUTH_SERVICE]

    async def mock_list_accounts():
        return [
            SimpleNamespace(
                display_name="Test User",
                email="user@example.com",
                created_at="2026-03-31T10:00:00+00:00",
                updated_at="2026-03-31T11:00:00+00:00",
            )
        ]

    upload_manager = mock.AsyncMock()
    upload_manager.list_files.return_value = ["sample.pdf"]

    monkeypatch.setattr(auth_service, "list_accounts", mock_list_accounts)
    monkeypatch.setattr(app, "get_chatbot_upload_manager", lambda chatbot_name: upload_manager)

    response = await client.get("/public-test-admin/users")

    payload = await response.get_json()
    assert response.status_code == 200
    assert payload == {
        "users": [
            {
                "displayName": "Test User",
                "email": "user@example.com",
                "createdAt": "2026-03-31T10:00:00+00:00",
                "updatedAt": "2026-03-31T11:00:00+00:00",
                "uploadCount": 1,
                "uploadedFiles": ["sample.pdf"],
            }
        ]
    }


@pytest.mark.asyncio
async def test_public_test_admin_user_delete_removes_uploads_and_account(client, monkeypatch):
    auth_service = client.app.config[app.CONFIG_PUBLIC_TEST_AUTH_SERVICE]
    upload_manager = mock.AsyncMock()
    upload_manager.remove_all_files.return_value = (["deleted.pdf"], [])

    async def mock_delete_account(email: str):
        assert email == "user@example.com"
        return True

    monkeypatch.setattr(app, "get_chatbot_upload_manager", lambda chatbot_name: upload_manager)
    monkeypatch.setattr(auth_service, "delete_account", mock_delete_account)

    response = await client.delete("/public-test-admin/users/user%40example.com")

    payload = await response.get_json()
    assert response.status_code == 200
    assert payload == {
        "message": "Public-test user deleted successfully.",
        "deletedUploadCount": 1,
    }
    upload_manager.remove_all_files.assert_awaited_once_with(user_identifier="user@example.com")


@pytest.mark.asyncio
async def test_public_test_admin_user_password_reset_updates_account(client, monkeypatch):
    auth_service = client.app.config[app.CONFIG_PUBLIC_TEST_AUTH_SERVICE]

    async def mock_reset_account_password(**kwargs):
        assert kwargs["email"] == "user@example.com"
        assert kwargs["password"] == "new-secret"
        assert kwargs["confirm_password"] == "new-secret"
        return SimpleNamespace(email="user@example.com", updated_at="2026-03-31T12:00:00+00:00")

    monkeypatch.setattr(auth_service, "reset_account_password", mock_reset_account_password)

    response = await client.post(
        "/public-test-admin/users/user%40example.com/password",
        json={"password": "new-secret", "confirmPassword": "new-secret"},
    )

    payload = await response.get_json()
    assert response.status_code == 200
    assert payload == {
        "message": "Public-test user password updated successfully.",
        "email": "user@example.com",
        "updatedAt": "2026-03-31T12:00:00+00:00",
    }


@pytest.mark.asyncio
async def test_chat_rak_applies_user_filter_from_header(client):
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
    assert client.app.config[app.CONFIG_SEARCH_CLIENT].filter == "(category eq 'rak') and user eq '12345'"


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
    chat_client = client.app.config[app.CONFIG_OPENAI_CLIENT]
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
