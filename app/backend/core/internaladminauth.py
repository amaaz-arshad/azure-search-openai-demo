import hmac
import io
import secrets
from dataclasses import dataclass

from azure.core.exceptions import ResourceExistsError
from azure.storage.blob import ContentSettings
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from prepdocslib.blobmanager import BlobManager

INTERNAL_ADMIN_AUTH_CONTAINER = "chatbot-prompts"
INTERNAL_ADMIN_AUTH_COOKIE = "internal_tools_admin_session"
INTERNAL_ADMIN_AUTH_MAX_AGE_SECONDS = 60 * 60 * 12
INTERNAL_ADMIN_SESSION_SECRET_BLOB = ".auth/session-secret.txt"
INTERNAL_ADMIN_REQUIRED_MESSAGE = "Internal admin authentication required."
INTERNAL_ADMIN_PASSWORD_MISSING_MESSAGE = "Internal admin password is not configured."
INTERNAL_ADMIN_INVALID_PASSWORD_MESSAGE = "Incorrect password. Please try again."


@dataclass(frozen=True)
class InternalAdminSession:
    role: str = "internal-admin"


class InternalAdminAuthStore:
    def __init__(
        self,
        *,
        blob_manager: BlobManager,
        session_secret: str | None,
        admin_password: str | None,
        auth_container: str = INTERNAL_ADMIN_AUTH_CONTAINER,
        session_cookie_name: str = INTERNAL_ADMIN_AUTH_COOKIE,
        session_max_age_seconds: int = INTERNAL_ADMIN_AUTH_MAX_AGE_SECONDS,
    ):
        self.blob_manager = blob_manager
        self.auth_container = auth_container
        self.session_cookie_name = session_cookie_name
        self.session_max_age_seconds = session_max_age_seconds
        self.session_secret = session_secret
        self.admin_password = (admin_password or "").strip()
        self.session_serializer: URLSafeTimedSerializer | None = None

    async def setup(self):
        self.session_secret = await self.resolve_session_secret()
        self.session_serializer = URLSafeTimedSerializer(self.session_secret, salt="internal-admin-session")

    async def ensure_container_exists(self):
        container_client = self.blob_manager.blob_service_client.get_container_client(self.auth_container)
        if not await container_client.exists():
            await container_client.create_container()
        return container_client

    async def resolve_session_secret(self) -> str:
        if self.session_secret:
            return self.session_secret

        container_client = await self.ensure_container_exists()
        blob_client = container_client.get_blob_client(INTERNAL_ADMIN_SESSION_SECRET_BLOB)
        download_response = await self.blob_manager.download_blob(
            INTERNAL_ADMIN_SESSION_SECRET_BLOB,
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
                INTERNAL_ADMIN_SESSION_SECRET_BLOB,
                container=self.auth_container,
            )
            if download_response is None:
                raise RuntimeError("Unable to resolve internal admin session secret from shared storage")
            content, _properties = download_response
            persisted_secret = content.decode("utf-8").strip()
            if not persisted_secret:
                raise RuntimeError("Persisted internal admin session secret is empty")
            return persisted_secret

    def has_password_configured(self) -> bool:
        return bool(self.admin_password)

    def verify_password(self, password: str) -> bool:
        if not self.admin_password:
            return False
        return hmac.compare_digest(password, self.admin_password)

    def get_session_serializer(self) -> URLSafeTimedSerializer:
        if self.session_serializer is None:
            raise RuntimeError("Internal admin auth store has not been initialized")
        return self.session_serializer

    def create_session_token(self) -> str:
        return self.get_session_serializer().dumps({"role": InternalAdminSession().role})

    async def load_session(self, session_token: str | None) -> InternalAdminSession | None:
        if not session_token:
            return None

        try:
            session_payload = self.get_session_serializer().loads(
                session_token,
                max_age=self.session_max_age_seconds,
            )
        except (BadSignature, SignatureExpired):
            return None

        role = session_payload.get("role") if isinstance(session_payload, dict) else None
        if role != InternalAdminSession().role:
            return None
        return InternalAdminSession()

    def set_session_cookie(self, response, *, secure: bool) -> None:
        response.set_cookie(
            self.session_cookie_name,
            self.create_session_token(),
            max_age=self.session_max_age_seconds,
            httponly=True,
            secure=secure,
            samesite="Lax",
            path="/",
        )

    def clear_session_cookie(self, response) -> None:
        response.delete_cookie(self.session_cookie_name, path="/", samesite="Lax")
