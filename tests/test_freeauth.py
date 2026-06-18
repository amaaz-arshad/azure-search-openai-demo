from unittest import mock

import pytest

from core.publictestauth import PUBLIC_TEST_EMAIL_LOGO_CID, PublicTestAuthStore


def build_auth_store() -> PublicTestAuthStore:
    return PublicTestAuthStore(
        blob_manager=mock.Mock(),
        session_secret="test-secret",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username=None,
        smtp_password=None,
        email_from="noreply@example.com",
        email_from_name="Nerilio Bot",
    )


@pytest.mark.asyncio
async def test_verification_email_is_german_and_branded(monkeypatch):
    auth_store = build_auth_store()
    sent_messages = []

    monkeypatch.setattr(auth_store, "load_email_logo", lambda: (b"fake-png", "png"))
    monkeypatch.setattr(auth_store, "send_email_sync", sent_messages.append)

    await auth_store.send_verification_email("user@example.com", "123456")

    assert len(sent_messages) == 1
    email_message = sent_messages[0]
    plain_body = email_message.get_body(("plain",)).get_content()
    html_body = email_message.get_body(("html",)).get_content()
    raw_message = email_message.as_string()

    assert email_message["Subject"] == "Dein nerilio Bestätigungscode"
    assert email_message["From"] == "nerilio <noreply@example.com>"
    assert "deine E-Mail-Adresse für dein nerilio-Konto zu bestätigen" in plain_body
    assert "123456" in plain_body
    assert "nerilio" in html_body
    assert f"cid:{PUBLIC_TEST_EMAIL_LOGO_CID}" in html_body
    assert f"Content-ID: <{PUBLIC_TEST_EMAIL_LOGO_CID}>" in raw_message
    assert "Nerilio Bot" not in raw_message


@pytest.mark.asyncio
async def test_password_reset_email_is_german_and_branded(monkeypatch):
    auth_store = build_auth_store()
    sent_messages = []

    monkeypatch.setattr(auth_store, "load_email_logo", lambda: None)
    monkeypatch.setattr(auth_store, "send_email_sync", sent_messages.append)

    await auth_store.send_password_reset_email("user@example.com", "654321")

    assert len(sent_messages) == 1
    email_message = sent_messages[0]
    plain_body = email_message.get_body(("plain",)).get_content()
    html_body = email_message.get_body(("html",)).get_content()

    assert email_message["Subject"] == "Dein nerilio Code zum Zurücksetzen des Passworts"
    assert "dein Passwort für dein nerilio-Konto zurückzusetzen" in plain_body
    assert "654321" in plain_body
    assert "zurückzusetzen" in html_body
    assert "Nerilio Bot" not in email_message.as_string()
