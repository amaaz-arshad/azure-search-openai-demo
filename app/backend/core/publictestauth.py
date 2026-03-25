import base64
import hashlib
import hmac
import io
import json
import logging
import secrets
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

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


@dataclass(frozen=True)
class PublicTestAccount:
    display_name: str
    email: str
    password_salt: str
    password_hash: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class PublicTestSession:
    display_name: str
    email: str


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


class PublicTestAuthStore:
    def __init__(
        self,
        *,
        blob_manager: BlobManager,
        session_secret: str | None,
        auth_container: str = PUBLIC_TEST_AUTH_CONTAINER,
        session_cookie_name: str = PUBLIC_TEST_AUTH_COOKIE,
        session_max_age_seconds: int = PUBLIC_TEST_SESSION_MAX_AGE_SECONDS,
    ):
        self.blob_manager = blob_manager
        self.auth_container = auth_container
        self.session_cookie_name = session_cookie_name
        self.session_max_age_seconds = session_max_age_seconds
        self.session_secret = session_secret
        self.session_serializer: URLSafeTimedSerializer | None = None

    async def setup(self):
        self.session_secret = await self.resolve_session_secret()
        self.session_serializer = URLSafeTimedSerializer(self.session_secret, salt="public-test-auth-session")

    @staticmethod
    def hash_email(email: str) -> str:
        return hashlib.sha256(email.encode("utf-8")).hexdigest()

    @staticmethod
    def build_password_hash(password: str, salt: bytes | None = None) -> tuple[str, str]:
        actual_salt = salt or secrets.token_bytes(16)
        password_hash = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            actual_salt,
            PUBLIC_TEST_PASSWORD_HASH_ITERATIONS,
        )
        salt_token = base64.urlsafe_b64encode(actual_salt).decode("ascii")
        password_hash_token = base64.urlsafe_b64encode(password_hash).decode("ascii")
        return salt_token, password_hash_token

    @staticmethod
    def verify_password(password: str, salt_token: str, password_hash_token: str) -> bool:
        try:
            salt = base64.urlsafe_b64decode(salt_token.encode("ascii"))
        except Exception:
            return False

        _, computed_hash_token = PublicTestAuthStore.build_password_hash(password, salt=salt)
        return hmac.compare_digest(computed_hash_token, password_hash_token)

    def get_account_blob_name(self, email: str) -> str:
        return f"accounts/{self.hash_email(email)}.json"

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

    async def load_account(self, email: str) -> PublicTestAccount | None:
        normalized_email = normalize_public_test_email(email)
        if normalized_email is None:
            return None

        result = await self.blob_manager.download_blob(
            self.get_account_blob_name(normalized_email),
            container=self.auth_container,
        )
        if result is None:
            return None

        content, _properties = result
        try:
            payload = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            logger.warning("Invalid public-test account payload for email %s", normalized_email)
            return None
        if not isinstance(payload, dict):
            logger.warning("Unexpected public-test account payload type for email %s", normalized_email)
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

    async def register_user(
        self,
        *,
        display_name: str,
        email: str,
        password: str,
        confirm_password: str,
    ) -> PublicTestSession:
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

        timestamp = datetime.now(timezone.utc).isoformat()
        password_salt, password_hash = self.build_password_hash(password)
        account = PublicTestAccount(
            display_name=normalized_display_name,
            email=normalized_email,
            password_salt=password_salt,
            password_hash=password_hash,
            created_at=timestamp,
            updated_at=timestamp,
        )

        container_client = await self.ensure_container_exists()
        payload = json.dumps(asdict(account), ensure_ascii=True).encode("utf-8")
        try:
            await container_client.upload_blob(
                self.get_account_blob_name(normalized_email),
                io.BytesIO(payload),
                overwrite=False,
                content_settings=ContentSettings(content_type="application/json"),
            )
        except ResourceExistsError as resource_exists_error:
            raise PublicTestAuthError("authErrors.accountExists") from resource_exists_error

        return PublicTestSession(display_name=account.display_name, email=account.email)

    async def login_user(self, *, email: str, password: str) -> PublicTestSession:
        normalized_email = normalize_public_test_email(email)
        if normalized_email is None or not password:
            raise PublicTestAuthError("authErrors.invalidCredentials", status_code=401)

        account = await self.load_account(normalized_email)
        if account is None:
            raise PublicTestAuthError("authErrors.invalidCredentials", status_code=401)

        if not self.verify_password(password, account.password_salt, account.password_hash):
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
