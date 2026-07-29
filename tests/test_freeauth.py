from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest

from core.freeauth import (
    FREE_ACCOUNT_LIFETIME_DAYS,
    FREE_EMAIL_LOGO_CID,
    FreeAccount,
    FreeAuthError,
    FreeAuthStore,
    describe_account_expiry,
    format_utc,
    is_account_expired,
)


def build_account(
    *,
    created_days_ago: float = 0,
    expires_at: str = "",
    email: str = "user@example.com",
    password_salt: str = "salt",
    password_hash: str = "hash",
) -> FreeAccount:
    now = datetime.now(timezone.utc)
    return FreeAccount(
        display_name="Test User",
        email=email,
        password_salt=password_salt,
        password_hash=password_hash,
        created_at=format_utc(now - timedelta(days=created_days_ago)),
        updated_at=format_utc(now),
        expires_at=expires_at,
    )


def build_auth_store() -> FreeAuthStore:
    return FreeAuthStore(
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
    assert f"cid:{FREE_EMAIL_LOGO_CID}" in html_body
    assert f"Content-ID: <{FREE_EMAIL_LOGO_CID}>" in raw_message
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


def test_expiry_derives_from_created_at_for_accounts_without_a_stored_window():
    """Accounts registered before the trial window existed still expire 30 days after signup."""
    fresh_expiry = describe_account_expiry(build_account(created_days_ago=5))
    assert fresh_expiry.is_expired is False
    assert fresh_expiry.days_remaining == FREE_ACCOUNT_LIFETIME_DAYS - 5
    assert fresh_expiry.days_expired == 0

    stale_expiry = describe_account_expiry(build_account(created_days_ago=FREE_ACCOUNT_LIFETIME_DAYS + 9))
    assert stale_expiry.is_expired is True
    assert stale_expiry.days_remaining == 0
    assert stale_expiry.days_expired == 9


def test_a_stored_window_wins_over_created_at():
    """So an admin reactivation survives instead of being undone by the created_at fallback."""
    reactivated_account = build_account(
        created_days_ago=200,
        expires_at=format_utc(datetime.now(timezone.utc) + timedelta(days=FREE_ACCOUNT_LIFETIME_DAYS)),
    )

    expiry = describe_account_expiry(reactivated_account)
    assert expiry.is_expired is False
    assert expiry.days_remaining == FREE_ACCOUNT_LIFETIME_DAYS


def test_a_partial_final_day_still_reads_as_one_day_left():
    almost_expired_account = build_account(expires_at=format_utc(datetime.now(timezone.utc) + timedelta(hours=6)))

    expiry = describe_account_expiry(almost_expired_account)
    assert expiry.is_expired is False
    assert expiry.days_remaining == 1


def test_unreadable_timestamps_count_as_expired_so_the_account_surfaces_in_the_archive():
    corrupt_account = FreeAccount(
        display_name="Test User",
        email="user@example.com",
        password_salt="salt",
        password_hash="hash",
        created_at="not-a-timestamp",
        updated_at="not-a-timestamp",
    )

    expiry = describe_account_expiry(corrupt_account)
    assert expiry.is_expired is True
    assert expiry.expires_at == ""


@pytest.mark.asyncio
async def test_login_is_refused_once_the_window_has_closed(monkeypatch):
    auth_store = build_auth_store()
    password_salt, password_hash = FreeAuthStore.build_secret_hash("correct-horse")

    async def mock_load_account(email: str):
        return build_account(
            created_days_ago=FREE_ACCOUNT_LIFETIME_DAYS + 1,
            email=email,
            password_salt=password_salt,
            password_hash=password_hash,
        )

    monkeypatch.setattr(auth_store, "load_account", mock_load_account)

    with pytest.raises(FreeAuthError) as expired_error:
        await auth_store.login_user(email="user@example.com", password="correct-horse")

    assert expired_error.value.error_key == "authErrors.accountExpired"
    assert expired_error.value.status_code == 403


@pytest.mark.asyncio
async def test_login_still_reports_bad_credentials_before_expiry_is_considered(monkeypatch):
    """An expired account must not become an oracle for which emails are registered."""
    auth_store = build_auth_store()
    password_salt, password_hash = FreeAuthStore.build_secret_hash("correct-horse")

    async def mock_load_account(email: str):
        return build_account(
            created_days_ago=FREE_ACCOUNT_LIFETIME_DAYS + 1,
            email=email,
            password_salt=password_salt,
            password_hash=password_hash,
        )

    monkeypatch.setattr(auth_store, "load_account", mock_load_account)

    with pytest.raises(FreeAuthError) as credentials_error:
        await auth_store.login_user(email="user@example.com", password="wrong-password")

    assert credentials_error.value.error_key == "authErrors.invalidCredentials"


@pytest.mark.asyncio
async def test_a_live_session_stops_resolving_when_the_account_expires(monkeypatch):
    auth_store = build_auth_store()
    await auth_store.setup()
    session_token = auth_store.create_session_token(auth_store.build_session(build_account(email="user@example.com")))

    async def mock_load_active_account(email: str):
        return build_account(created_days_ago=1, email=email)

    monkeypatch.setattr(auth_store, "load_account", mock_load_active_account)
    active_session = await auth_store.load_session(session_token)
    assert active_session is not None
    assert active_session.days_remaining == FREE_ACCOUNT_LIFETIME_DAYS - 1

    async def mock_load_expired_account(email: str):
        return build_account(created_days_ago=FREE_ACCOUNT_LIFETIME_DAYS + 1, email=email)

    monkeypatch.setattr(auth_store, "load_account", mock_load_expired_account)
    assert await auth_store.load_session(session_token) is None


@pytest.mark.asyncio
async def test_signup_with_an_expired_email_is_refused_with_its_own_message(monkeypatch):
    auth_store = build_auth_store()

    async def mock_load_expired_account(email: str):
        return build_account(created_days_ago=FREE_ACCOUNT_LIFETIME_DAYS + 1, email=email)

    monkeypatch.setattr(auth_store, "load_account", mock_load_expired_account)

    with pytest.raises(FreeAuthError) as signup_error:
        await auth_store.start_signup(
            display_name="Test User",
            email="user@example.com",
            password="long-enough",
            confirm_password="long-enough",
        )

    assert signup_error.value.error_key == "authErrors.accountExpiredSignup"
    assert signup_error.value.status_code == 403


@pytest.mark.asyncio
async def test_signup_with_an_active_email_still_reports_the_account_exists(monkeypatch):
    auth_store = build_auth_store()

    async def mock_load_active_account(email: str):
        return build_account(created_days_ago=2, email=email)

    monkeypatch.setattr(auth_store, "load_account", mock_load_active_account)

    with pytest.raises(FreeAuthError) as signup_error:
        await auth_store.start_signup(
            display_name="Test User",
            email="user@example.com",
            password="long-enough",
            confirm_password="long-enough",
        )

    assert signup_error.value.error_key == "authErrors.accountExists"


@pytest.mark.asyncio
async def test_password_reset_is_refused_once_the_window_has_closed(monkeypatch):
    auth_store = build_auth_store()

    async def mock_load_expired_account(email: str):
        return build_account(created_days_ago=FREE_ACCOUNT_LIFETIME_DAYS + 1, email=email)

    monkeypatch.setattr(auth_store, "load_account", mock_load_expired_account)

    with pytest.raises(FreeAuthError) as reset_error:
        await auth_store.start_password_reset(email="user@example.com")

    assert reset_error.value.error_key == "authErrors.accountExpired"


@pytest.mark.asyncio
async def test_reactivation_opens_a_new_window_and_keeps_the_password(monkeypatch):
    auth_store = build_auth_store()
    expired_account = build_account(created_days_ago=FREE_ACCOUNT_LIFETIME_DAYS + 40)
    saved_payloads: dict[str, dict] = {}

    async def mock_load_account(email: str):
        return expired_account

    async def mock_save_json_blob(blob_name: str, payload: dict):
        saved_payloads[blob_name] = payload

    monkeypatch.setattr(auth_store, "load_account", mock_load_account)
    monkeypatch.setattr(auth_store, "save_json_blob", mock_save_json_blob)

    reactivated_account = await auth_store.reactivate_account(email="user@example.com")

    assert is_account_expired(expired_account) is True
    assert is_account_expired(reactivated_account) is False
    assert describe_account_expiry(reactivated_account).days_remaining == FREE_ACCOUNT_LIFETIME_DAYS
    # Registration date and credentials are untouched; only the window moves.
    assert reactivated_account.created_at == expired_account.created_at
    assert reactivated_account.password_hash == expired_account.password_hash
    saved_payload = saved_payloads[auth_store.get_account_blob_name("user@example.com")]
    assert saved_payload["expires_at"] == reactivated_account.expires_at


@pytest.mark.asyncio
async def test_a_password_reset_keeps_a_reactivated_window(monkeypatch):
    """Rewriting the account must not silently drop back to the created_at fallback."""
    auth_store = build_auth_store()
    reactivated_expires_at = format_utc(datetime.now(timezone.utc) + timedelta(days=12))
    saved_payloads: dict[str, dict] = {}

    async def mock_load_account(email: str):
        return build_account(created_days_ago=300, expires_at=reactivated_expires_at, email=email)

    async def mock_save_json_blob(blob_name: str, payload: dict):
        saved_payloads[blob_name] = payload

    async def mock_delete_pending_password_reset(email: str):
        return None

    monkeypatch.setattr(auth_store, "load_account", mock_load_account)
    monkeypatch.setattr(auth_store, "save_json_blob", mock_save_json_blob)
    monkeypatch.setattr(auth_store, "delete_pending_password_reset", mock_delete_pending_password_reset)

    updated_account = await auth_store.reset_account_password(
        email="user@example.com",
        password="brand-new-password",
        confirm_password="brand-new-password",
    )

    assert updated_account.expires_at == reactivated_expires_at
    assert is_account_expired(updated_account) is False
