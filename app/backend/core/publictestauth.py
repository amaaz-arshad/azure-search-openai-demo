import asyncio
import base64
import hashlib
import hmac
import io
import json
import logging
import secrets
import smtplib
import ssl
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr

from azure.core.exceptions import ResourceExistsError
from azure.storage.blob import ContentSettings
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from prepdocslib.blobmanager import BlobManager

logger = logging.getLogger("scripts")

PUBLIC_TEST_AUTH_CONTAINER = "public-test-auth"
PUBLIC_TEST_AUTH_COOKIE = "public_test_session"
PUBLIC_TEST_SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 7
PUBLIC_TEST_PASSWORD_HASH_ITERATIONS = 600_000
PUBLIC_TEST_SESSION_SECRET_BLOB = "session-secret.txt"
PUBLIC_TEST_VERIFICATION_CODE_TTL_SECONDS = 15 * 60
PUBLIC_TEST_VERIFICATION_RESEND_INTERVAL_SECONDS = 45
PUBLIC_TEST_VERIFICATION_MAX_ATTEMPTS = 5


@dataclass(frozen=True)
class PublicTestAccount:
    display_name: str
    email: str
    password_salt: str
    password_hash: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class PendingPublicTestSignup:
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
class PublicTestSession:
    display_name: str
    email: str


@dataclass(frozen=True)
class PublicTestVerificationChallenge:
    email: str
    expires_in_seconds: int


class PublicTestAuthError(Exception):
    def __init__(self, error_key: str, status_code: int = 400):
        super().__init__(error_key)
        self.error_key = error_key
        self.status_code = status_code


def normalize_public_test_email(raw_email: str | None) -> str | None:
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


class PublicTestAuthStore:
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
        email_from_name: str = "Public Test",
        auth_container: str = PUBLIC_TEST_AUTH_CONTAINER,
        session_cookie_name: str = PUBLIC_TEST_AUTH_COOKIE,
        session_max_age_seconds: int = PUBLIC_TEST_SESSION_MAX_AGE_SECONDS,
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
        self.email_from_name = email_from_name.strip() or "Public Test"
        self.running_in_production = running_in_production

    async def setup(self):
        self.session_secret = await self.resolve_session_secret()
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
            PUBLIC_TEST_PASSWORD_HASH_ITERATIONS,
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

        _, computed_hash_token = PublicTestAuthStore.build_secret_hash(secret_value, salt=salt)
        return hmac.compare_digest(computed_hash_token, hash_token)

    def get_account_blob_name(self, email: str) -> str:
        return f"accounts/{self.hash_email(email)}.json"

    def get_pending_signup_blob_name(self, email: str) -> str:
        return f"pending-signups/{self.hash_email(email)}.json"

    async def ensure_container_exists(self):
        container_client = self.blob_manager.blob_service_client.get_container_client(self.auth_container)
        if not await container_client.exists():
            await container_client.create_container()
        return container_client

    async def resolve_session_secret(self) -> str:
        if self.session_secret:
            return self.session_secret

        logger.warning(
            "AZURE_SERVER_APP_SECRET is not set. Falling back to a blob-backed shared session secret for public-test."
        )
        container_client = await self.ensure_container_exists()
        blob_client = container_client.get_blob_client(PUBLIC_TEST_SESSION_SECRET_BLOB)

        download_response = await self.blob_manager.download_blob(
            PUBLIC_TEST_SESSION_SECRET_BLOB,
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
                PUBLIC_TEST_SESSION_SECRET_BLOB,
                container=self.auth_container,
            )
            if download_response is None:
                raise RuntimeError("Unable to resolve public-test session secret from shared storage")
            content, _properties = download_response
            persisted_secret = content.decode("utf-8").strip()
            if not persisted_secret:
                raise RuntimeError("Persisted public-test session secret is empty")
            return persisted_secret

    def get_session_serializer(self) -> URLSafeTimedSerializer:
        if self.session_serializer is None:
            raise RuntimeError("Public-test auth store has not been initialized")
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
        await self.blob_manager.remove_blob_name(blob_name)

    async def load_account(self, email: str) -> PublicTestAccount | None:
        normalized_email = normalize_public_test_email(email)
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
            logger.warning("Incomplete public-test account payload for email %s", normalized_email)
            return None

        return PublicTestAccount(
            display_name=str(payload["display_name"]).strip(),
            email=str(payload["email"]).strip().lower(),
            password_salt=str(payload["password_salt"]),
            password_hash=str(payload["password_hash"]),
            created_at=str(payload["created_at"]),
            updated_at=str(payload["updated_at"]),
        )

    async def load_pending_signup(self, email: str) -> PendingPublicTestSignup | None:
        normalized_email = normalize_public_test_email(email)
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

        return PendingPublicTestSignup(
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

    async def save_pending_signup(self, pending_signup: PendingPublicTestSignup) -> None:
        await self.save_json_blob(self.get_pending_signup_blob_name(pending_signup.email), asdict(pending_signup))

    async def delete_pending_signup(self, email: str) -> None:
        normalized_email = normalize_public_test_email(email)
        if normalized_email is None:
            return
        await self.delete_blob_if_exists(self.get_pending_signup_blob_name(normalized_email))

    async def save_account(self, account: PublicTestAccount) -> None:
        container_client = await self.ensure_container_exists()
        try:
            await container_client.upload_blob(
                self.get_account_blob_name(account.email),
                io.BytesIO(json.dumps(asdict(account), ensure_ascii=True).encode("utf-8")),
                overwrite=False,
                content_settings=ContentSettings(content_type="application/json"),
            )
        except ResourceExistsError as resource_exists_error:
            raise PublicTestAuthError("authErrors.accountExists") from resource_exists_error

    def generate_verification_code(self) -> str:
        return f"{secrets.randbelow(1_000_000):06d}"

    def build_verification_challenge(self, email: str) -> PublicTestVerificationChallenge:
        return PublicTestVerificationChallenge(
            email=email,
            expires_in_seconds=PUBLIC_TEST_VERIFICATION_CODE_TTL_SECONDS,
        )

    async def send_verification_email(self, email: str, verification_code: str) -> None:
        if not self.smtp_host or not self.email_from:
            message = (
                "Public-test verification email requested, but SMTP is not configured."
                if self.running_in_production
                else f"Public-test verification code for {email}: {verification_code}"
            )
            if self.running_in_production:
                logger.error(message)
                raise PublicTestAuthError("authErrors.verificationEmailUnavailable", status_code=503)
            logger.warning(message)
            return

        email_message = EmailMessage()
        email_message["Subject"] = "Your Nerilio AI public test verification code"
        email_message["From"] = formataddr((self.email_from_name, self.email_from))
        email_message["To"] = email
        email_message.set_content(
            "\n".join(
                [
                    "Dear User,",
                    "",
                    "Use the verification code below to finish creating your account:",
                    "",
                    verification_code,
                    "",
                    "This code expires in 15 minutes.",
                    "",
                    "If you did not request this email, you can ignore it.",
                ]
            )
        )

        try:
            await asyncio.to_thread(self.send_email_sync, email_message)
        except PublicTestAuthError:
            raise
        except Exception as error:
            logger.exception("Failed to send public-test verification email to %s", email)
            raise PublicTestAuthError("authErrors.verificationEmailFailed", status_code=503) from error

    def send_email_sync(self, email_message: EmailMessage) -> None:
        with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=20) as smtp_client:
            smtp_client.ehlo()
            smtp_client.starttls(context=ssl.create_default_context())
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
    ) -> PublicTestVerificationChallenge:
        normalized_display_name = display_name.strip()
        normalized_email = normalize_public_test_email(email)

        if not normalized_display_name:
            raise PublicTestAuthError("authErrors.displayNameRequired")
        if normalized_email is None:
            if not (email or "").strip():
                raise PublicTestAuthError("authErrors.emailRequired")
            raise PublicTestAuthError("authErrors.invalidEmail")
        if not password:
            raise PublicTestAuthError("authErrors.passwordRequired")
        if not confirm_password:
            raise PublicTestAuthError("authErrors.confirmPasswordRequired")
        if password != confirm_password:
            raise PublicTestAuthError("authErrors.passwordMismatch")
        if await self.load_account(normalized_email):
            raise PublicTestAuthError("authErrors.accountExists")

        verification_code = self.generate_verification_code()
        password_salt, password_hash = self.build_secret_hash(password)
        verification_salt, verification_hash = self.build_secret_hash(verification_code)
        now = datetime.now(timezone.utc)
        pending_signup = PendingPublicTestSignup(
            display_name=normalized_display_name,
            email=normalized_email,
            password_salt=password_salt,
            password_hash=password_hash,
            verification_salt=verification_salt,
            verification_hash=verification_hash,
            created_at=format_utc(now),
            updated_at=format_utc(now),
            expires_at=format_utc(now + timedelta(seconds=PUBLIC_TEST_VERIFICATION_CODE_TTL_SECONDS)),
            last_sent_at=format_utc(now),
            send_count=1,
            failed_attempts=0,
        )
        await self.save_pending_signup(pending_signup)
        await self.send_verification_email(normalized_email, verification_code)
        return self.build_verification_challenge(normalized_email)

    async def resend_signup_code(self, *, email: str) -> PublicTestVerificationChallenge:
        normalized_email = normalize_public_test_email(email)
        if normalized_email is None:
            raise PublicTestAuthError("authErrors.invalidEmail")

        pending_signup = await self.load_pending_signup(normalized_email)
        if pending_signup is None:
            raise PublicTestAuthError("authErrors.verificationSessionNotFound", status_code=404)
        if await self.load_account(normalized_email):
            await self.delete_pending_signup(normalized_email)
            raise PublicTestAuthError("authErrors.accountExists")

        now = datetime.now(timezone.utc)
        if parse_utc(pending_signup.last_sent_at) + timedelta(
            seconds=PUBLIC_TEST_VERIFICATION_RESEND_INTERVAL_SECONDS
        ) > now:
            raise PublicTestAuthError("authErrors.verificationResendTooSoon", status_code=429)

        verification_code = self.generate_verification_code()
        verification_salt, verification_hash = self.build_secret_hash(verification_code)
        refreshed_pending_signup = PendingPublicTestSignup(
            display_name=pending_signup.display_name,
            email=pending_signup.email,
            password_salt=pending_signup.password_salt,
            password_hash=pending_signup.password_hash,
            verification_salt=verification_salt,
            verification_hash=verification_hash,
            created_at=pending_signup.created_at,
            updated_at=format_utc(now),
            expires_at=format_utc(now + timedelta(seconds=PUBLIC_TEST_VERIFICATION_CODE_TTL_SECONDS)),
            last_sent_at=format_utc(now),
            send_count=pending_signup.send_count + 1,
            failed_attempts=0,
        )
        await self.save_pending_signup(refreshed_pending_signup)
        await self.send_verification_email(normalized_email, verification_code)
        return self.build_verification_challenge(normalized_email)

    async def verify_signup(self, *, email: str, verification_code: str) -> PublicTestSession:
        normalized_email = normalize_public_test_email(email)
        normalized_code = (verification_code or "").strip()
        if normalized_email is None:
            raise PublicTestAuthError("authErrors.invalidEmail")
        if not normalized_code:
            raise PublicTestAuthError("authErrors.verificationCodeRequired")

        pending_signup = await self.load_pending_signup(normalized_email)
        if pending_signup is None:
            raise PublicTestAuthError("authErrors.verificationSessionNotFound", status_code=404)
        if await self.load_account(normalized_email):
            await self.delete_pending_signup(normalized_email)
            raise PublicTestAuthError("authErrors.accountExists")

        now = datetime.now(timezone.utc)
        if parse_utc(pending_signup.expires_at) < now:
            await self.delete_pending_signup(normalized_email)
            raise PublicTestAuthError("authErrors.verificationCodeExpired")

        if pending_signup.failed_attempts >= PUBLIC_TEST_VERIFICATION_MAX_ATTEMPTS:
            await self.delete_pending_signup(normalized_email)
            raise PublicTestAuthError("authErrors.verificationTooManyAttempts", status_code=429)

        if not self.verify_secret_value(
            normalized_code,
            pending_signup.verification_salt,
            pending_signup.verification_hash,
        ):
            updated_pending_signup = PendingPublicTestSignup(
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
            raise PublicTestAuthError("authErrors.invalidVerificationCode")

        account = PublicTestAccount(
            display_name=pending_signup.display_name,
            email=pending_signup.email,
            password_salt=pending_signup.password_salt,
            password_hash=pending_signup.password_hash,
            created_at=format_utc(now),
            updated_at=format_utc(now),
        )
        await self.save_account(account)
        await self.delete_pending_signup(account.email)
        return PublicTestSession(display_name=account.display_name, email=account.email)

    async def login_user(self, *, email: str, password: str) -> PublicTestSession:
        normalized_email = normalize_public_test_email(email)
        if normalized_email is None or not password:
            raise PublicTestAuthError("authErrors.invalidCredentials", status_code=401)

        account = await self.load_account(normalized_email)
        if account is None:
            raise PublicTestAuthError("authErrors.invalidCredentials", status_code=401)

        if not self.verify_secret_value(password, account.password_salt, account.password_hash):
            raise PublicTestAuthError("authErrors.invalidCredentials", status_code=401)

        return PublicTestSession(display_name=account.display_name, email=account.email)

    def create_session_token(self, session: PublicTestSession) -> str:
        return self.get_session_serializer().dumps({"email": session.email})

    async def load_session(self, session_token: str | None) -> PublicTestSession | None:
        if not session_token:
            return None

        try:
            session_payload = self.get_session_serializer().loads(
                session_token,
                max_age=self.session_max_age_seconds,
            )
        except (BadSignature, SignatureExpired):
            return None

        email = normalize_public_test_email(session_payload.get("email") if isinstance(session_payload, dict) else None)
        if email is None:
            return None

        account = await self.load_account(email)
        if account is None:
            return None

        return PublicTestSession(display_name=account.display_name, email=account.email)

    def set_session_cookie(self, response, session: PublicTestSession, *, secure: bool) -> None:
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
