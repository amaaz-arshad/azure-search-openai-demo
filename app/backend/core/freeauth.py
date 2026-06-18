import asyncio
import base64
import hashlib
import hmac
import html
import io
import json
import logging
import re
import secrets
import smtplib
import ssl
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.storage.blob import ContentSettings
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from prepdocslib.blobmanager import BlobManager

logger = logging.getLogger("scripts")

# Legacy persisted namespaces for the Free Bot. The string VALUES below intentionally keep their
# original "public-test" naming for backward compatibility: the blob container holds every
# registered account and the cookie name identifies live sessions. Renaming either VALUE would
# orphan all existing accounts / log every user out, so only the identifier names are "free".
FREE_AUTH_CONTAINER = "public-test-auth"
FREE_AUTH_COOKIE = "public_test_session"
FREE_SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 7
FREE_PASSWORD_HASH_ITERATIONS = 600_000
FREE_SESSION_SECRET_BLOB = "session-secret.txt"
FREE_VERIFICATION_CODE_TTL_SECONDS = 15 * 60
FREE_VERIFICATION_RESEND_INTERVAL_SECONDS = 45
FREE_VERIFICATION_MAX_ATTEMPTS = 5
FREE_PASSWORD_MIN_LENGTH = 8
FREE_EMAIL_BRAND_NAME = "nerilio"
FREE_EMAIL_LOGO_CID = "nerilio-logo"


@dataclass(frozen=True)
class FreeAccount:
    display_name: str
    email: str
    password_salt: str
    password_hash: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class PendingFreeSignup:
    display_name: str
    email: str
    password_salt: str
    password_hash: str
    verification_salt: str
    verification_hash: str
    created_at: str
    updated_at: str
    expires_at: str
    last_sent_at: str
    send_count: int
    failed_attempts: int


@dataclass(frozen=True)
class PendingFreePasswordReset:
    email: str
    verification_salt: str
    verification_hash: str
    created_at: str
    updated_at: str
    expires_at: str
    last_sent_at: str
    send_count: int
    failed_attempts: int


@dataclass(frozen=True)
class FreeSession:
    display_name: str
    email: str


@dataclass(frozen=True)
class FreeVerificationChallenge:
    email: str
    expires_in_seconds: int


class FreeAuthError(Exception):
    def __init__(self, error_key: str, status_code: int = 400):
        super().__init__(error_key)
        self.error_key = error_key
        self.status_code = status_code


def normalize_free_email(raw_email: str | None) -> str | None:
    normalized_email = (raw_email or "").strip().lower()
    if not normalized_email:
        return None

    local_part, separator, domain = normalized_email.partition("@")
    if not separator or not local_part or "." not in domain or domain.startswith(".") or domain.endswith("."):
        return None
    if any(character.isspace() for character in normalized_email):
        return None
    return normalized_email


def format_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)


class FreeAuthStore:
    def __init__(
        self,
        *,
        blob_manager: BlobManager,
        session_secret: str | None,
        smtp_host: str | None,
        smtp_port: int,
        smtp_username: str | None,
        smtp_password: str | None,
        email_from: str | None,
        email_from_name: str = FREE_EMAIL_BRAND_NAME,
        auth_container: str = FREE_AUTH_CONTAINER,
        session_cookie_name: str = FREE_AUTH_COOKIE,
        session_max_age_seconds: int = FREE_SESSION_MAX_AGE_SECONDS,
        running_in_production: bool = False,
    ):
        self.blob_manager = blob_manager
        self.auth_container = auth_container
        self.session_cookie_name = session_cookie_name
        self.session_max_age_seconds = session_max_age_seconds
        self.session_secret = session_secret
        self.session_serializer: URLSafeTimedSerializer | None = None
        self.smtp_host = (smtp_host or "").strip()
        self.smtp_port = smtp_port
        self.smtp_username = (smtp_username or "").strip()
        self.smtp_password = smtp_password or ""
        self.email_from = (email_from or "").strip()
        self.email_from_name = (email_from_name.strip() or FREE_EMAIL_BRAND_NAME).replace(
            "Nerilio Bot", FREE_EMAIL_BRAND_NAME
        )
        self.running_in_production = running_in_production

    async def setup(self):
        self.session_secret = await self.resolve_session_secret()
        # Legacy serializer salt — kept as-is so existing signed session cookies stay valid.
        self.session_serializer = URLSafeTimedSerializer(self.session_secret, salt="public-test-auth-session")

    @staticmethod
    def hash_email(email: str) -> str:
        return hashlib.sha256(email.encode("utf-8")).hexdigest()

    @staticmethod
    def build_secret_hash(secret_value: str, salt: bytes | None = None) -> tuple[str, str]:
        actual_salt = salt or secrets.token_bytes(16)
        value_hash = hashlib.pbkdf2_hmac(
            "sha256",
            secret_value.encode("utf-8"),
            actual_salt,
            FREE_PASSWORD_HASH_ITERATIONS,
        )
        salt_token = base64.urlsafe_b64encode(actual_salt).decode("ascii")
        value_hash_token = base64.urlsafe_b64encode(value_hash).decode("ascii")
        return salt_token, value_hash_token

    @staticmethod
    def verify_secret_value(secret_value: str, salt_token: str, hash_token: str) -> bool:
        try:
            salt = base64.urlsafe_b64decode(salt_token.encode("ascii"))
        except Exception:
            return False

        _, computed_hash_token = FreeAuthStore.build_secret_hash(secret_value, salt=salt)
        return hmac.compare_digest(computed_hash_token, hash_token)

    @staticmethod
    def validate_password_requirements(password: str) -> None:
        if len(password) < FREE_PASSWORD_MIN_LENGTH:
            raise FreeAuthError("authErrors.passwordTooShort")

    def get_account_blob_name(self, email: str) -> str:
        return f"accounts/{self.hash_email(email)}.json"

    def get_pending_signup_blob_name(self, email: str) -> str:
        return f"pending-signups/{self.hash_email(email)}.json"

    def get_pending_password_reset_blob_name(self, email: str) -> str:
        return f"password-resets/{self.hash_email(email)}.json"

    async def ensure_container_exists(self):
        container_client = self.blob_manager.blob_service_client.get_container_client(self.auth_container)
        if not await container_client.exists():
            await container_client.create_container()
        return container_client

    async def resolve_session_secret(self) -> str:
        if self.session_secret:
            return self.session_secret

        logger.warning(
            "AZURE_SERVER_APP_SECRET is not set. Falling back to a blob-backed shared session secret for free."
        )
        container_client = await self.ensure_container_exists()
        blob_client = container_client.get_blob_client(FREE_SESSION_SECRET_BLOB)

        download_response = await self.blob_manager.download_blob(
            FREE_SESSION_SECRET_BLOB,
            container=self.auth_container,
        )
        if download_response is not None:
            content, _properties = download_response
            existing_secret = content.decode("utf-8").strip()
            if existing_secret:
                return existing_secret

        generated_secret = secrets.token_urlsafe(48)
        try:
            await blob_client.upload_blob(
                io.BytesIO(generated_secret.encode("utf-8")),
                overwrite=False,
                content_settings=ContentSettings(content_type="text/plain"),
            )
            return generated_secret
        except ResourceExistsError:
            download_response = await self.blob_manager.download_blob(
                FREE_SESSION_SECRET_BLOB,
                container=self.auth_container,
            )
            if download_response is None:
                raise RuntimeError("Unable to resolve free session secret from shared storage")
            content, _properties = download_response
            persisted_secret = content.decode("utf-8").strip()
            if not persisted_secret:
                raise RuntimeError("Persisted free session secret is empty")
            return persisted_secret

    def get_session_serializer(self) -> URLSafeTimedSerializer:
        if self.session_serializer is None:
            raise RuntimeError("Free auth store has not been initialized")
        return self.session_serializer

    async def load_json_blob(self, blob_name: str) -> dict | None:
        result = await self.blob_manager.download_blob(blob_name, container=self.auth_container)
        if result is None:
            return None

        content, _properties = result
        try:
            payload = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            logger.warning("Invalid JSON payload for blob %s", blob_name)
            return None
        if not isinstance(payload, dict):
            logger.warning("Unexpected JSON payload type for blob %s", blob_name)
            return None
        return payload

    async def save_json_blob(self, blob_name: str, payload: dict) -> None:
        container_client = await self.ensure_container_exists()
        await container_client.upload_blob(
            blob_name,
            io.BytesIO(json.dumps(payload, ensure_ascii=True).encode("utf-8")),
            overwrite=True,
            content_settings=ContentSettings(content_type="application/json"),
        )

    async def delete_blob_if_exists(self, blob_name: str) -> None:
        container_client = await self.ensure_container_exists()
        try:
            await container_client.delete_blob(blob_name, delete_snapshots="include")
        except ResourceNotFoundError:
            logger.debug("Blob already removed from %s: %s", self.auth_container, blob_name)

    async def load_account(self, email: str) -> FreeAccount | None:
        normalized_email = normalize_free_email(email)
        if normalized_email is None:
            return None

        payload = await self.load_json_blob(self.get_account_blob_name(normalized_email))
        if payload is None:
            return None

        required_fields = {
            "display_name",
            "email",
            "password_salt",
            "password_hash",
            "created_at",
            "updated_at",
        }
        if not required_fields.issubset(payload):
            logger.warning("Incomplete free account payload for email %s", normalized_email)
            return None

        return FreeAccount(
            display_name=str(payload["display_name"]).strip(),
            email=str(payload["email"]).strip().lower(),
            password_salt=str(payload["password_salt"]),
            password_hash=str(payload["password_hash"]),
            created_at=str(payload["created_at"]),
            updated_at=str(payload["updated_at"]),
        )

    async def load_pending_signup(self, email: str) -> PendingFreeSignup | None:
        normalized_email = normalize_free_email(email)
        if normalized_email is None:
            return None

        payload = await self.load_json_blob(self.get_pending_signup_blob_name(normalized_email))
        if payload is None:
            return None

        required_fields = {
            "display_name",
            "email",
            "password_salt",
            "password_hash",
            "verification_salt",
            "verification_hash",
            "created_at",
            "updated_at",
            "expires_at",
            "last_sent_at",
            "send_count",
            "failed_attempts",
        }
        if not required_fields.issubset(payload):
            logger.warning("Incomplete pending signup payload for email %s", normalized_email)
            return None

        return PendingFreeSignup(
            display_name=str(payload["display_name"]).strip(),
            email=str(payload["email"]).strip().lower(),
            password_salt=str(payload["password_salt"]),
            password_hash=str(payload["password_hash"]),
            verification_salt=str(payload["verification_salt"]),
            verification_hash=str(payload["verification_hash"]),
            created_at=str(payload["created_at"]),
            updated_at=str(payload["updated_at"]),
            expires_at=str(payload["expires_at"]),
            last_sent_at=str(payload["last_sent_at"]),
            send_count=int(payload["send_count"]),
            failed_attempts=int(payload["failed_attempts"]),
        )

    async def save_pending_signup(self, pending_signup: PendingFreeSignup) -> None:
        await self.save_json_blob(self.get_pending_signup_blob_name(pending_signup.email), asdict(pending_signup))

    async def delete_pending_signup(self, email: str) -> None:
        normalized_email = normalize_free_email(email)
        if normalized_email is None:
            return
        await self.delete_blob_if_exists(self.get_pending_signup_blob_name(normalized_email))

    async def load_pending_password_reset(self, email: str) -> PendingFreePasswordReset | None:
        normalized_email = normalize_free_email(email)
        if normalized_email is None:
            return None

        payload = await self.load_json_blob(self.get_pending_password_reset_blob_name(normalized_email))
        if payload is None:
            return None

        required_fields = {
            "email",
            "verification_salt",
            "verification_hash",
            "created_at",
            "updated_at",
            "expires_at",
            "last_sent_at",
            "send_count",
            "failed_attempts",
        }
        if not required_fields.issubset(payload):
            logger.warning("Incomplete pending password reset payload for email %s", normalized_email)
            return None

        return PendingFreePasswordReset(
            email=str(payload["email"]).strip().lower(),
            verification_salt=str(payload["verification_salt"]),
            verification_hash=str(payload["verification_hash"]),
            created_at=str(payload["created_at"]),
            updated_at=str(payload["updated_at"]),
            expires_at=str(payload["expires_at"]),
            last_sent_at=str(payload["last_sent_at"]),
            send_count=int(payload["send_count"]),
            failed_attempts=int(payload["failed_attempts"]),
        )

    async def save_pending_password_reset(self, pending_password_reset: PendingFreePasswordReset) -> None:
        await self.save_json_blob(
            self.get_pending_password_reset_blob_name(pending_password_reset.email),
            asdict(pending_password_reset),
        )

    async def delete_pending_password_reset(self, email: str) -> None:
        normalized_email = normalize_free_email(email)
        if normalized_email is None:
            return
        await self.delete_blob_if_exists(self.get_pending_password_reset_blob_name(normalized_email))

    async def save_account(self, account: FreeAccount) -> None:
        container_client = await self.ensure_container_exists()
        try:
            await container_client.upload_blob(
                self.get_account_blob_name(account.email),
                io.BytesIO(json.dumps(asdict(account), ensure_ascii=True).encode("utf-8")),
                overwrite=False,
                content_settings=ContentSettings(content_type="application/json"),
            )
        except ResourceExistsError as resource_exists_error:
            raise FreeAuthError("authErrors.accountExists") from resource_exists_error

    async def list_accounts(self) -> list[FreeAccount]:
        container_client = await self.ensure_container_exists()
        accounts: list[FreeAccount] = []
        async for blob in container_client.list_blobs(name_starts_with="accounts/"):
            blob_name = getattr(blob, "name", None)
            if not blob_name:
                continue
            payload = await self.load_json_blob(blob_name)
            if payload is None:
                continue

            required_fields = {
                "display_name",
                "email",
                "password_salt",
                "password_hash",
                "created_at",
                "updated_at",
            }
            if not required_fields.issubset(payload):
                logger.warning("Incomplete free account payload in blob %s", blob_name)
                continue

            accounts.append(
                FreeAccount(
                    display_name=str(payload["display_name"]).strip(),
                    email=str(payload["email"]).strip().lower(),
                    password_salt=str(payload["password_salt"]),
                    password_hash=str(payload["password_hash"]),
                    created_at=str(payload["created_at"]),
                    updated_at=str(payload["updated_at"]),
                )
            )

        return sorted(accounts, key=lambda account: account.updated_at, reverse=True)

    async def delete_account(self, email: str) -> bool:
        normalized_email = normalize_free_email(email)
        if normalized_email is None:
            return False

        existing_account = await self.load_account(normalized_email)
        await self.delete_blob_if_exists(self.get_account_blob_name(normalized_email))
        await self.delete_pending_signup(normalized_email)
        await self.delete_pending_password_reset(normalized_email)
        return existing_account is not None

    async def reset_account_password(
        self,
        *,
        email: str,
        password: str,
        confirm_password: str,
    ) -> FreeAccount:
        normalized_email = normalize_free_email(email)
        if normalized_email is None:
            raise FreeAuthError("authErrors.invalidEmail")
        if not password:
            raise FreeAuthError("authErrors.passwordRequired")
        self.validate_password_requirements(password)
        if not confirm_password:
            raise FreeAuthError("authErrors.confirmPasswordRequired")
        if password != confirm_password:
            raise FreeAuthError("authErrors.passwordMismatch")

        account = await self.load_account(normalized_email)
        if account is None:
            raise FreeAuthError("authErrors.invalidCredentials", status_code=404)

        password_salt, password_hash = self.build_secret_hash(password)
        updated_account = FreeAccount(
            display_name=account.display_name,
            email=account.email,
            password_salt=password_salt,
            password_hash=password_hash,
            created_at=account.created_at,
            updated_at=format_utc(datetime.now(timezone.utc)),
        )
        await self.save_json_blob(self.get_account_blob_name(updated_account.email), asdict(updated_account))
        await self.delete_pending_password_reset(updated_account.email)
        return updated_account

    def generate_verification_code(self) -> str:
        return f"{secrets.randbelow(1_000_000):06d}"

    def build_verification_challenge(self, email: str) -> FreeVerificationChallenge:
        return FreeVerificationChallenge(
            email=email,
            expires_in_seconds=FREE_VERIFICATION_CODE_TTL_SECONDS,
        )

    @staticmethod
    def get_frontend_logo_asset_path() -> Path | None:
        backend_root = Path(__file__).resolve().parents[1]
        static_root = backend_root / "static"
        index_path = static_root / "index.html"

        if index_path.exists():
            for line in index_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                if 'rel="icon"' not in line and "rel='icon'" not in line:
                    continue
                href_match = re.search(r"href=[\"']([^\"']+)[\"']", line)
                if not href_match:
                    continue
                candidate = static_root / href_match.group(1).lstrip("/")
                if candidate.exists():
                    return candidate

        for pattern in ("assets/robo1*.png", "assets/*fbn*.png"):
            matches = sorted(static_root.glob(pattern))
            if matches:
                return matches[0]

        repo_root = backend_root.parents[1]
        for candidate in (
            repo_root / "app" / "frontend" / "src" / "assets" / "robo1.png",
            repo_root / "app" / "frontend" / "src" / "chatbots" / "nerilio" / "assets" / "robo1.png",
        ):
            if candidate.exists():
                return candidate

        return None

    def load_email_logo(self) -> tuple[bytes, str] | None:
        logo_path = self.get_frontend_logo_asset_path()
        if logo_path is None:
            return None

        image_subtype = logo_path.suffix.lower().lstrip(".") or "png"
        if image_subtype == "jpg":
            image_subtype = "jpeg"
        try:
            return logo_path.read_bytes(), image_subtype
        except OSError:
            logger.warning("Unable to read free email logo from %s", logo_path)
            return None

    @staticmethod
    def build_code_email_html(*, headline: str, intro: str, verification_code: str, include_logo: bool) -> str:
        escaped_headline = html.escape(headline)
        escaped_intro = html.escape(intro)
        escaped_code = html.escape(verification_code)
        logo_html = (
            f'<img src="cid:{FREE_EMAIL_LOGO_CID}" alt="nerilio" width="76" '
            'style="display:block;width:76px;max-width:76px;height:auto;margin:0 auto 18px;" />'
            if include_logo
            else ""
        )

        return f"""<!doctype html>
<html lang="de">
<body style="margin:0;background:#f5f7f2;color:#19231d;font-family:'Segoe UI',Arial,sans-serif;">
    <div style="display:none;max-height:0;overflow:hidden;opacity:0;">Dein nerilio Code: {escaped_code}</div>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f5f7f2;">
        <tr>
            <td align="center" style="padding:34px 16px;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;background:#ffffff;border:1px solid #dfe9da;border-radius:24px;overflow:hidden;box-shadow:0 18px 48px rgba(45,68,47,0.14);">
                    <tr>
                        <td style="padding:34px 34px 30px;text-align:center;">
                            {logo_html}
                            <div style="font-size:13px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#58745f;">nerilio</div>
                            <h1 style="margin:12px 0 12px;font-size:28px;line-height:1.2;color:#132017;">{escaped_headline}</h1>
                            <p style="margin:0 auto 24px;max-width:410px;font-size:16px;line-height:1.6;color:#4b5e50;">{escaped_intro}</p>
                            <div style="display:inline-block;padding:18px 26px;border-radius:18px;background:#eef6ea;border:1px solid #cfe0c8;color:#132017;font-size:34px;line-height:1;font-weight:800;letter-spacing:0.18em;">{escaped_code}</div>
                            <p style="margin:24px auto 0;max-width:420px;font-size:14px;line-height:1.6;color:#657669;">Der Code ist 15 Minuten gültig. Wenn du diese E-Mail nicht angefordert hast, kannst du sie einfach ignorieren.</p>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding:18px 34px;background:#fbfcf8;border-top:1px solid #edf2e8;text-align:center;color:#7a887d;font-size:12px;line-height:1.5;">
                            Diese Nachricht wurde automatisch von nerilio gesendet.
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""

    def build_code_email_message(
        self,
        *,
        to_email: str,
        subject: str,
        greeting: str,
        intro: str,
        verification_code: str,
    ) -> EmailMessage:
        logo_payload = self.load_email_logo()
        email_message = EmailMessage()
        email_message["Subject"] = subject
        email_message["From"] = formataddr((self.email_from_name, self.email_from))
        email_message["To"] = to_email
        email_message.set_content(
            "\n".join(
                [
                    greeting,
                    "",
                    intro,
                    "",
                    verification_code,
                    "",
                    "Der Code ist 15 Minuten gültig.",
                    "",
                    "Wenn du diese E-Mail nicht angefordert hast, kannst du sie einfach ignorieren.",
                    "",
                    "nerilio",
                ]
            )
        )
        email_message.add_alternative(
            self.build_code_email_html(
                headline=subject,
                intro=intro,
                verification_code=verification_code,
                include_logo=logo_payload is not None,
            ),
            subtype="html",
        )

        html_part = email_message.get_body(("html",))
        if logo_payload is not None and html_part is not None:
            logo_bytes, image_subtype = logo_payload
            html_part.add_related(
                logo_bytes,
                maintype="image",
                subtype=image_subtype,
                cid=f"<{FREE_EMAIL_LOGO_CID}>",
                filename="nerilio.png",
            )

        return email_message

    async def send_verification_email(self, email: str, verification_code: str) -> None:
        if not self.smtp_host or not self.email_from:
            message = (
                "Free verification email requested, but SMTP is not configured."
                if self.running_in_production
                else f"nerilio verification code for {email}: {verification_code}"
            )
            if self.running_in_production:
                logger.error(message)
                raise FreeAuthError("authErrors.verificationEmailUnavailable", status_code=503)
            logger.warning(message)
            return

        email_message = self.build_code_email_message(
            to_email=email,
            subject="Dein nerilio Bestätigungscode",
            greeting="Hallo,",
            intro="nutze den folgenden Code, um deine E-Mail-Adresse für dein nerilio-Konto zu bestätigen:",
            verification_code=verification_code,
        )

        try:
            await asyncio.to_thread(self.send_email_sync, email_message)
        except FreeAuthError:
            raise
        except Exception as error:
            logger.exception("Failed to send free verification email to %s", email)
            raise FreeAuthError("authErrors.verificationEmailFailed", status_code=503) from error

    async def send_password_reset_email(self, email: str, verification_code: str) -> None:
        if not self.smtp_host or not self.email_from:
            message = (
                "Free password reset email requested, but SMTP is not configured."
                if self.running_in_production
                else f"nerilio password reset code for {email}: {verification_code}"
            )
            if self.running_in_production:
                logger.error(message)
                raise FreeAuthError("authErrors.verificationEmailUnavailable", status_code=503)
            logger.warning(message)
            return

        email_message = self.build_code_email_message(
            to_email=email,
            subject="Dein nerilio Code zum Zurücksetzen des Passworts",
            greeting="Hallo,",
            intro="nutze den folgenden Code, um dein Passwort für dein nerilio-Konto zurückzusetzen:",
            verification_code=verification_code,
        )

        try:
            await asyncio.to_thread(self.send_email_sync, email_message)
        except FreeAuthError:
            raise
        except Exception as error:
            logger.exception("Failed to send free password reset email to %s", email)
            raise FreeAuthError("authErrors.verificationEmailFailed", status_code=503) from error

    def send_email_sync(self, email_message: EmailMessage) -> None:
        ssl_context = ssl.create_default_context()
        if self.smtp_port == 465:
            smtp_client_context = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=20, context=ssl_context)
        else:
            smtp_client_context = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=20)

        with smtp_client_context as smtp_client:
            smtp_client.ehlo()
            if self.smtp_port != 465:
                smtp_client.starttls(context=ssl_context)
                smtp_client.ehlo()
            if self.smtp_username:
                smtp_client.login(self.smtp_username, self.smtp_password)
            smtp_client.send_message(email_message)

    async def start_signup(
        self,
        *,
        display_name: str,
        email: str,
        password: str,
        confirm_password: str,
    ) -> FreeVerificationChallenge:
        normalized_display_name = display_name.strip()
        normalized_email = normalize_free_email(email)

        if not normalized_display_name:
            raise FreeAuthError("authErrors.displayNameRequired")
        if normalized_email is None:
            if not (email or "").strip():
                raise FreeAuthError("authErrors.emailRequired")
            raise FreeAuthError("authErrors.invalidEmail")
        if not password:
            raise FreeAuthError("authErrors.passwordRequired")
        self.validate_password_requirements(password)
        if not confirm_password:
            raise FreeAuthError("authErrors.confirmPasswordRequired")
        if password != confirm_password:
            raise FreeAuthError("authErrors.passwordMismatch")
        if await self.load_account(normalized_email):
            raise FreeAuthError("authErrors.accountExists")

        verification_code = self.generate_verification_code()
        password_salt, password_hash = self.build_secret_hash(password)
        verification_salt, verification_hash = self.build_secret_hash(verification_code)
        now = datetime.now(timezone.utc)
        pending_signup = PendingFreeSignup(
            display_name=normalized_display_name,
            email=normalized_email,
            password_salt=password_salt,
            password_hash=password_hash,
            verification_salt=verification_salt,
            verification_hash=verification_hash,
            created_at=format_utc(now),
            updated_at=format_utc(now),
            expires_at=format_utc(now + timedelta(seconds=FREE_VERIFICATION_CODE_TTL_SECONDS)),
            last_sent_at=format_utc(now),
            send_count=1,
            failed_attempts=0,
        )
        await self.save_pending_signup(pending_signup)
        await self.send_verification_email(normalized_email, verification_code)
        return self.build_verification_challenge(normalized_email)

    async def resend_signup_code(self, *, email: str) -> FreeVerificationChallenge:
        normalized_email = normalize_free_email(email)
        if normalized_email is None:
            raise FreeAuthError("authErrors.invalidEmail")

        pending_signup = await self.load_pending_signup(normalized_email)
        if pending_signup is None:
            raise FreeAuthError("authErrors.verificationSessionNotFound", status_code=404)
        if await self.load_account(normalized_email):
            await self.delete_pending_signup(normalized_email)
            raise FreeAuthError("authErrors.accountExists")

        now = datetime.now(timezone.utc)
        if (
            parse_utc(pending_signup.last_sent_at) + timedelta(seconds=FREE_VERIFICATION_RESEND_INTERVAL_SECONDS)
            > now
        ):
            raise FreeAuthError("authErrors.verificationResendTooSoon", status_code=429)

        verification_code = self.generate_verification_code()
        verification_salt, verification_hash = self.build_secret_hash(verification_code)
        refreshed_pending_signup = PendingFreeSignup(
            display_name=pending_signup.display_name,
            email=pending_signup.email,
            password_salt=pending_signup.password_salt,
            password_hash=pending_signup.password_hash,
            verification_salt=verification_salt,
            verification_hash=verification_hash,
            created_at=pending_signup.created_at,
            updated_at=format_utc(now),
            expires_at=format_utc(now + timedelta(seconds=FREE_VERIFICATION_CODE_TTL_SECONDS)),
            last_sent_at=format_utc(now),
            send_count=pending_signup.send_count + 1,
            failed_attempts=0,
        )
        await self.save_pending_signup(refreshed_pending_signup)
        await self.send_verification_email(normalized_email, verification_code)
        return self.build_verification_challenge(normalized_email)

    async def verify_signup(self, *, email: str, verification_code: str) -> FreeSession:
        normalized_email = normalize_free_email(email)
        normalized_code = (verification_code or "").strip()
        if normalized_email is None:
            raise FreeAuthError("authErrors.invalidEmail")
        if not normalized_code:
            raise FreeAuthError("authErrors.verificationCodeRequired")

        pending_signup = await self.load_pending_signup(normalized_email)
        if pending_signup is None:
            raise FreeAuthError("authErrors.verificationSessionNotFound", status_code=404)
        if await self.load_account(normalized_email):
            await self.delete_pending_signup(normalized_email)
            raise FreeAuthError("authErrors.accountExists")

        now = datetime.now(timezone.utc)
        if parse_utc(pending_signup.expires_at) < now:
            await self.delete_pending_signup(normalized_email)
            raise FreeAuthError("authErrors.verificationCodeExpired")

        if pending_signup.failed_attempts >= FREE_VERIFICATION_MAX_ATTEMPTS:
            await self.delete_pending_signup(normalized_email)
            raise FreeAuthError("authErrors.verificationTooManyAttempts", status_code=429)

        if not self.verify_secret_value(
            normalized_code,
            pending_signup.verification_salt,
            pending_signup.verification_hash,
        ):
            updated_pending_signup = PendingFreeSignup(
                display_name=pending_signup.display_name,
                email=pending_signup.email,
                password_salt=pending_signup.password_salt,
                password_hash=pending_signup.password_hash,
                verification_salt=pending_signup.verification_salt,
                verification_hash=pending_signup.verification_hash,
                created_at=pending_signup.created_at,
                updated_at=format_utc(now),
                expires_at=pending_signup.expires_at,
                last_sent_at=pending_signup.last_sent_at,
                send_count=pending_signup.send_count,
                failed_attempts=pending_signup.failed_attempts + 1,
            )
            await self.save_pending_signup(updated_pending_signup)
            raise FreeAuthError("authErrors.invalidVerificationCode")

        account = FreeAccount(
            display_name=pending_signup.display_name,
            email=pending_signup.email,
            password_salt=pending_signup.password_salt,
            password_hash=pending_signup.password_hash,
            created_at=format_utc(now),
            updated_at=format_utc(now),
        )
        await self.save_account(account)
        await self.delete_pending_signup(account.email)
        return FreeSession(display_name=account.display_name, email=account.email)

    async def start_password_reset(self, *, email: str) -> FreeVerificationChallenge:
        normalized_email = normalize_free_email(email)
        if normalized_email is None:
            if not (email or "").strip():
                raise FreeAuthError("authErrors.emailRequired")
            raise FreeAuthError("authErrors.invalidEmail")

        account = await self.load_account(normalized_email)
        if account is None:
            raise FreeAuthError("authErrors.accountNotFound", status_code=404)

        now = datetime.now(timezone.utc)
        existing_pending_password_reset = await self.load_pending_password_reset(normalized_email)
        if (
            existing_pending_password_reset is not None
            and parse_utc(existing_pending_password_reset.last_sent_at)
            + timedelta(seconds=FREE_VERIFICATION_RESEND_INTERVAL_SECONDS)
            > now
        ):
            raise FreeAuthError("authErrors.verificationResendTooSoon", status_code=429)

        verification_code = self.generate_verification_code()
        verification_salt, verification_hash = self.build_secret_hash(verification_code)
        pending_password_reset = PendingFreePasswordReset(
            email=normalized_email,
            verification_salt=verification_salt,
            verification_hash=verification_hash,
            created_at=(
                existing_pending_password_reset.created_at if existing_pending_password_reset else format_utc(now)
            ),
            updated_at=format_utc(now),
            expires_at=format_utc(now + timedelta(seconds=FREE_VERIFICATION_CODE_TTL_SECONDS)),
            last_sent_at=format_utc(now),
            send_count=(existing_pending_password_reset.send_count + 1) if existing_pending_password_reset else 1,
            failed_attempts=0,
        )
        await self.save_pending_password_reset(pending_password_reset)
        await self.send_password_reset_email(normalized_email, verification_code)
        return self.build_verification_challenge(normalized_email)

    async def resend_password_reset_code(self, *, email: str) -> FreeVerificationChallenge:
        normalized_email = normalize_free_email(email)
        if normalized_email is None:
            raise FreeAuthError("authErrors.invalidEmail")

        pending_password_reset = await self.load_pending_password_reset(normalized_email)
        if pending_password_reset is None:
            raise FreeAuthError("authErrors.passwordResetSessionNotFound", status_code=404)

        account = await self.load_account(normalized_email)
        if account is None:
            await self.delete_pending_password_reset(normalized_email)
            raise FreeAuthError("authErrors.accountNotFound", status_code=404)

        now = datetime.now(timezone.utc)
        if (
            parse_utc(pending_password_reset.last_sent_at)
            + timedelta(seconds=FREE_VERIFICATION_RESEND_INTERVAL_SECONDS)
            > now
        ):
            raise FreeAuthError("authErrors.verificationResendTooSoon", status_code=429)

        verification_code = self.generate_verification_code()
        verification_salt, verification_hash = self.build_secret_hash(verification_code)
        refreshed_pending_password_reset = PendingFreePasswordReset(
            email=pending_password_reset.email,
            verification_salt=verification_salt,
            verification_hash=verification_hash,
            created_at=pending_password_reset.created_at,
            updated_at=format_utc(now),
            expires_at=format_utc(now + timedelta(seconds=FREE_VERIFICATION_CODE_TTL_SECONDS)),
            last_sent_at=format_utc(now),
            send_count=pending_password_reset.send_count + 1,
            failed_attempts=0,
        )
        await self.save_pending_password_reset(refreshed_pending_password_reset)
        await self.send_password_reset_email(normalized_email, verification_code)
        return self.build_verification_challenge(normalized_email)

    async def verify_password_reset(
        self,
        *,
        email: str,
        verification_code: str,
        password: str,
        confirm_password: str,
    ) -> FreeSession:
        normalized_email = normalize_free_email(email)
        normalized_code = (verification_code or "").strip()
        if normalized_email is None:
            if not (email or "").strip():
                raise FreeAuthError("authErrors.emailRequired")
            raise FreeAuthError("authErrors.invalidEmail")
        if not normalized_code:
            raise FreeAuthError("authErrors.verificationCodeRequired")
        if not password:
            raise FreeAuthError("authErrors.passwordRequired")
        self.validate_password_requirements(password)
        if not confirm_password:
            raise FreeAuthError("authErrors.confirmPasswordRequired")
        if password != confirm_password:
            raise FreeAuthError("authErrors.passwordMismatch")

        pending_password_reset = await self.load_pending_password_reset(normalized_email)
        if pending_password_reset is None:
            raise FreeAuthError("authErrors.passwordResetSessionNotFound", status_code=404)

        account = await self.load_account(normalized_email)
        if account is None:
            await self.delete_pending_password_reset(normalized_email)
            raise FreeAuthError("authErrors.accountNotFound", status_code=404)

        now = datetime.now(timezone.utc)
        if parse_utc(pending_password_reset.expires_at) < now:
            await self.delete_pending_password_reset(normalized_email)
            raise FreeAuthError("authErrors.verificationCodeExpired")

        if pending_password_reset.failed_attempts >= FREE_VERIFICATION_MAX_ATTEMPTS:
            await self.delete_pending_password_reset(normalized_email)
            raise FreeAuthError("authErrors.verificationTooManyAttempts", status_code=429)

        if not self.verify_secret_value(
            normalized_code,
            pending_password_reset.verification_salt,
            pending_password_reset.verification_hash,
        ):
            updated_pending_password_reset = PendingFreePasswordReset(
                email=pending_password_reset.email,
                verification_salt=pending_password_reset.verification_salt,
                verification_hash=pending_password_reset.verification_hash,
                created_at=pending_password_reset.created_at,
                updated_at=format_utc(now),
                expires_at=pending_password_reset.expires_at,
                last_sent_at=pending_password_reset.last_sent_at,
                send_count=pending_password_reset.send_count,
                failed_attempts=pending_password_reset.failed_attempts + 1,
            )
            await self.save_pending_password_reset(updated_pending_password_reset)
            raise FreeAuthError("authErrors.invalidVerificationCode")

        password_salt, password_hash = self.build_secret_hash(password)
        updated_account = FreeAccount(
            display_name=account.display_name,
            email=account.email,
            password_salt=password_salt,
            password_hash=password_hash,
            created_at=account.created_at,
            updated_at=format_utc(now),
        )
        await self.save_json_blob(self.get_account_blob_name(updated_account.email), asdict(updated_account))
        await self.delete_pending_password_reset(updated_account.email)
        return FreeSession(display_name=updated_account.display_name, email=updated_account.email)

    async def login_user(self, *, email: str, password: str) -> FreeSession:
        normalized_email = normalize_free_email(email)
        if normalized_email is None or not password:
            raise FreeAuthError("authErrors.invalidCredentials", status_code=401)

        account = await self.load_account(normalized_email)
        if account is None:
            raise FreeAuthError("authErrors.invalidCredentials", status_code=401)

        if not self.verify_secret_value(password, account.password_salt, account.password_hash):
            raise FreeAuthError("authErrors.invalidCredentials", status_code=401)

        return FreeSession(display_name=account.display_name, email=account.email)

    def create_session_token(self, session: FreeSession) -> str:
        return self.get_session_serializer().dumps({"email": session.email})

    async def load_session(self, session_token: str | None) -> FreeSession | None:
        if not session_token:
            return None

        try:
            session_payload = self.get_session_serializer().loads(
                session_token,
                max_age=self.session_max_age_seconds,
            )
        except (BadSignature, SignatureExpired):
            return None

        email = normalize_free_email(session_payload.get("email") if isinstance(session_payload, dict) else None)
        if email is None:
            return None

        account = await self.load_account(email)
        if account is None:
            return None

        return FreeSession(display_name=account.display_name, email=account.email)

    def set_session_cookie(self, response, session: FreeSession, *, secure: bool) -> None:
        response.set_cookie(
            self.session_cookie_name,
            self.create_session_token(session),
            max_age=self.session_max_age_seconds,
            httponly=True,
            secure=secure,
            samesite="Lax",
            path="/",
        )

    def clear_session_cookie(self, response) -> None:
        response.delete_cookie(self.session_cookie_name, path="/", samesite="Lax")
