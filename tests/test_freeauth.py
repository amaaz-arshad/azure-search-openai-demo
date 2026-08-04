from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest

from core.freeauth import (
    FREE_ACCOUNT_LIFETIME_DAYS,
    FREE_EMAIL_LOGO_CID,
    FreeAccount,
    FreeAuthError,
    FreeAuthStore,
    PendingFreePasswordReset,
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
    display_name: str = "Test User",
    first_name: str = "Susi",
    last_name: str = "Musterfrau",
) -> FreeAccount:
    now = datetime.now(timezone.utc)
    return FreeAccount(
        display_name=display_name,
        email=email,
        password_salt=password_salt,
        password_hash=password_hash,
        created_at=format_utc(now - timedelta(days=created_days_ago)),
        updated_at=format_utc(now),
        expires_at=expires_at,
        first_name=first_name,
        last_name=last_name,
    )


def build_auth_store(*, hubspot_contact_store=None) -> FreeAuthStore:
    return FreeAuthStore(
        blob_manager=mock.Mock(),
        session_secret="test-secret",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username=None,
        smtp_password=None,
        email_from="noreply@example.com",
        email_from_name="Nerilio Bot",
        hubspot_contact_store=hubspot_contact_store,
    )


class RecordingHubSpotContactStore:
    """Stands in for HubSpotContactStore, recording calls instead of making them."""

    def __init__(self, *, error: Exception | None = None):
        self.calls: list[dict] = []
        self.error = error

    async def create_contact(self, **kwargs) -> bool:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return True


async def run_signup_to_verification(
    auth_store: FreeAuthStore,
    monkeypatch,
    *,
    first_name: str = "Susi",
    last_name: str = "Musterfrau",
    display_name: str = "Mustermann GmbH",
    email: str = "susi@example.com",
) -> tuple[list[FreeAccount], str]:
    """Drive start_signup -> verify_signup against in-memory storage.

    Returns the accounts handed to save_account plus the code that was emailed, so a test can
    assert on what a real registration actually persists.
    """
    pending_signups: dict[str, object] = {}
    saved_accounts: list[FreeAccount] = []
    sent_codes: list[str] = []

    async def mock_load_account(account_email: str):
        return None

    async def mock_save_pending_signup(pending_signup):
        pending_signups["current"] = pending_signup

    async def mock_load_pending_signup(account_email: str):
        return pending_signups.get("current")

    async def mock_delete_pending_signup(account_email: str):
        pending_signups.pop("current", None)

    async def mock_save_account(account: FreeAccount):
        saved_accounts.append(account)

    async def mock_send_verification_email(account_email: str, verification_code: str):
        sent_codes.append(verification_code)

    monkeypatch.setattr(auth_store, "load_account", mock_load_account)
    monkeypatch.setattr(auth_store, "save_pending_signup", mock_save_pending_signup)
    monkeypatch.setattr(auth_store, "load_pending_signup", mock_load_pending_signup)
    monkeypatch.setattr(auth_store, "delete_pending_signup", mock_delete_pending_signup)
    monkeypatch.setattr(auth_store, "save_account", mock_save_account)
    monkeypatch.setattr(auth_store, "send_verification_email", mock_send_verification_email)

    await auth_store.start_signup(
        first_name=first_name,
        last_name=last_name,
        display_name=display_name,
        email=email,
        password="long-enough",
        confirm_password="long-enough",
    )
    return saved_accounts, sent_codes[-1]


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
            first_name="Susi",
            last_name="Musterfrau",
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
            first_name="Susi",
            last_name="Musterfrau",
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


@pytest.mark.parametrize(
    "first_name, last_name, expected_error_key",
    [
        ("", "Musterfrau", "authErrors.firstNameRequired"),
        ("   ", "Musterfrau", "authErrors.firstNameRequired"),
        ("Susi", "", "authErrors.lastNameRequired"),
        ("Susi", "   ", "authErrors.lastNameRequired"),
    ],
)
@pytest.mark.asyncio
async def test_signup_requires_both_names(first_name, last_name, expected_error_key):
    auth_store = build_auth_store()

    with pytest.raises(FreeAuthError) as signup_error:
        await auth_store.start_signup(
            first_name=first_name,
            last_name=last_name,
            display_name="Mustermann GmbH",
            email="susi@example.com",
            password="long-enough",
            confirm_password="long-enough",
        )

    assert signup_error.value.error_key == expected_error_key


@pytest.mark.asyncio
async def test_a_missing_name_is_reported_before_a_missing_company():
    """The form stacks first/last above the company field, so the topmost gap must win."""
    auth_store = build_auth_store()

    with pytest.raises(FreeAuthError) as signup_error:
        await auth_store.start_signup(
            first_name="",
            last_name="",
            display_name="",
            email="",
            password="",
            confirm_password="",
        )

    assert signup_error.value.error_key == "authErrors.firstNameRequired"


@pytest.mark.asyncio
async def test_a_verified_signup_persists_the_names_and_creates_a_hubspot_contact(monkeypatch):
    hubspot_contact_store = RecordingHubSpotContactStore()
    auth_store = build_auth_store(hubspot_contact_store=hubspot_contact_store)

    saved_accounts, verification_code = await run_signup_to_verification(
        auth_store,
        monkeypatch,
        first_name="  Susi  ",
        last_name="  Musterfrau  ",
        display_name="  Mustermann GmbH  ",
    )
    session = await auth_store.verify_signup(email="susi@example.com", verification_code=verification_code)

    assert session.email == "susi@example.com"
    assert len(saved_accounts) == 1
    stored_account = saved_accounts[0]
    assert (stored_account.first_name, stored_account.last_name) == ("Susi", "Musterfrau")
    assert stored_account.display_name == "Mustermann GmbH"

    # The company field is the Free Bot's display_name, which is what HubSpot's `company` gets.
    assert hubspot_contact_store.calls == [
        {
            "email": "susi@example.com",
            "first_name": "Susi",
            "last_name": "Musterfrau",
            "company": "Mustermann GmbH",
        }
    ]


@pytest.mark.asyncio
async def test_the_names_survive_a_resent_code_and_a_wrong_code(monkeypatch):
    """Every PendingFreeSignup rewrite must carry them, or the account is created without them."""
    auth_store = build_auth_store()
    saved_accounts, _first_code = await run_signup_to_verification(auth_store, monkeypatch)

    # A wrong code rewrites the pending signup to bump failed_attempts.
    with pytest.raises(FreeAuthError):
        await auth_store.verify_signup(email="susi@example.com", verification_code="000000")

    # A resend rewrites it again with a fresh code, so drop the resend cooldown for this test.
    monkeypatch.setattr("core.freeauth.FREE_VERIFICATION_RESEND_INTERVAL_SECONDS", 0)
    sent_codes: list[str] = []

    async def mock_send_verification_email(email: str, verification_code: str):
        sent_codes.append(verification_code)

    monkeypatch.setattr(auth_store, "send_verification_email", mock_send_verification_email)
    await auth_store.resend_signup_code(email="susi@example.com")

    await auth_store.verify_signup(email="susi@example.com", verification_code=sent_codes[-1])

    assert len(saved_accounts) == 1
    assert (saved_accounts[0].first_name, saved_accounts[0].last_name) == ("Susi", "Musterfrau")


@pytest.mark.asyncio
async def test_a_hubspot_outage_does_not_cost_the_user_the_account_they_just_verified(monkeypatch):
    """The account blob is already written, and the email can never be re-registered."""
    hubspot_contact_store = RecordingHubSpotContactStore(error=RuntimeError("HubSpot exploded"))
    auth_store = build_auth_store(hubspot_contact_store=hubspot_contact_store)

    saved_accounts, verification_code = await run_signup_to_verification(auth_store, monkeypatch)
    session = await auth_store.verify_signup(email="susi@example.com", verification_code=verification_code)

    assert session.email == "susi@example.com"
    assert len(saved_accounts) == 1
    assert len(hubspot_contact_store.calls) == 1


@pytest.mark.asyncio
async def test_signup_works_with_no_hubspot_store_configured(monkeypatch):
    auth_store = build_auth_store(hubspot_contact_store=None)

    saved_accounts, verification_code = await run_signup_to_verification(auth_store, monkeypatch)
    session = await auth_store.verify_signup(email="susi@example.com", verification_code=verification_code)

    assert session.email == "susi@example.com"
    assert len(saved_accounts) == 1


@pytest.mark.asyncio
async def test_every_account_rewrite_keeps_the_names(monkeypatch):
    """Same hazard as expires_at: a rewrite that forgets a field silently discards it."""
    auth_store = build_auth_store()
    account = build_account(first_name="Susi", last_name="Musterfrau")

    async def mock_load_account(email: str):
        return account

    async def mock_save_json_blob(blob_name: str, payload: dict):
        return None

    async def mock_delete_pending_password_reset(email: str):
        return None

    monkeypatch.setattr(auth_store, "load_account", mock_load_account)
    monkeypatch.setattr(auth_store, "save_json_blob", mock_save_json_blob)
    monkeypatch.setattr(auth_store, "delete_pending_password_reset", mock_delete_pending_password_reset)

    after_admin_reset = await auth_store.reset_account_password(
        email="user@example.com",
        password="brand-new-password",
        confirm_password="brand-new-password",
    )
    after_reactivation = await auth_store.reactivate_account(email="user@example.com")

    for rewritten_account in (after_admin_reset, after_reactivation):
        assert (rewritten_account.first_name, rewritten_account.last_name) == ("Susi", "Musterfrau")


@pytest.mark.asyncio
async def test_a_self_service_password_reset_keeps_the_names(monkeypatch):
    auth_store = build_auth_store()
    account = build_account(first_name="Susi", last_name="Musterfrau")
    verification_salt, verification_hash = FreeAuthStore.build_secret_hash("123456")
    now = datetime.now(timezone.utc)
    saved_payloads: dict[str, dict] = {}

    async def mock_load_account(email: str):
        return account

    async def mock_load_pending_password_reset(email: str):
        return PendingFreePasswordReset(
            email=email,
            verification_salt=verification_salt,
            verification_hash=verification_hash,
            created_at=format_utc(now),
            updated_at=format_utc(now),
            expires_at=format_utc(now + timedelta(minutes=10)),
            last_sent_at=format_utc(now),
            send_count=1,
            failed_attempts=0,
        )

    async def mock_save_json_blob(blob_name: str, payload: dict):
        saved_payloads[blob_name] = payload

    async def mock_delete_pending_password_reset(email: str):
        return None

    monkeypatch.setattr(auth_store, "load_account", mock_load_account)
    monkeypatch.setattr(auth_store, "load_pending_password_reset", mock_load_pending_password_reset)
    monkeypatch.setattr(auth_store, "save_json_blob", mock_save_json_blob)
    monkeypatch.setattr(auth_store, "delete_pending_password_reset", mock_delete_pending_password_reset)

    await auth_store.verify_password_reset(
        email="user@example.com",
        verification_code="123456",
        password="brand-new-password",
        confirm_password="brand-new-password",
    )

    saved_payload = saved_payloads[auth_store.get_account_blob_name("user@example.com")]
    assert saved_payload["first_name"] == "Susi"
    assert saved_payload["last_name"] == "Musterfrau"


@pytest.mark.asyncio
async def test_accounts_registered_before_the_name_fields_existed_still_load(monkeypatch):
    """The names must not join load_account's required-field set, or every legacy blob breaks."""
    auth_store = build_auth_store()
    now = format_utc(datetime.now(timezone.utc))

    async def mock_load_json_blob(blob_name: str):
        return {
            "display_name": "Legacy GmbH",
            "email": "legacy@example.com",
            "password_salt": "salt",
            "password_hash": "hash",
            "created_at": now,
            "updated_at": now,
        }

    monkeypatch.setattr(auth_store, "load_json_blob", mock_load_json_blob)

    account = await auth_store.load_account("legacy@example.com")

    assert account is not None
    assert account.display_name == "Legacy GmbH"
    assert (account.first_name, account.last_name) == ("", "")


@pytest.mark.asyncio
async def test_a_signup_already_awaiting_its_code_when_this_shipped_still_verifies(monkeypatch):
    """A pending-signup blob written before the name fields existed must not dead-end."""
    auth_store = build_auth_store()
    now = format_utc(datetime.now(timezone.utc))

    async def mock_load_json_blob(blob_name: str):
        return {
            "display_name": "Legacy GmbH",
            "email": "legacy@example.com",
            "password_salt": "salt",
            "password_hash": "hash",
            "verification_salt": "vsalt",
            "verification_hash": "vhash",
            "created_at": now,
            "updated_at": now,
            "expires_at": now,
            "last_sent_at": now,
            "send_count": 1,
            "failed_attempts": 0,
        }

    monkeypatch.setattr(auth_store, "load_json_blob", mock_load_json_blob)

    pending_signup = await auth_store.load_pending_signup("legacy@example.com")

    assert pending_signup is not None
    assert (pending_signup.first_name, pending_signup.last_name) == ("", "")
