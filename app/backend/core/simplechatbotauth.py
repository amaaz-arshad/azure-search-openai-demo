import hmac
import re
from dataclasses import dataclass

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

SIMPLE_CHATBOT_AUTH_COOKIE_PREFIX = "chatbot_basic_auth"
SIMPLE_CHATBOT_AUTH_MAX_AGE_SECONDS = 60 * 60 * 12
SIMPLE_CHATBOT_AUTH_REQUIRED_MESSAGE = "Chatbot authentication required."
SIMPLE_CHATBOT_AUTH_INVALID_CREDENTIALS_MESSAGE = "Incorrect username or password."


@dataclass(frozen=True)
class SimpleChatbotCredentials:
    usernames: frozenset[str]
    password: str


@dataclass(frozen=True)
class SimpleChatbotSession:
    chatbot_name: str
    user: str


class SimpleChatbotAuthStore:
    def __init__(
        self,
        *,
        session_secret: str,
        credentials: dict[str, SimpleChatbotCredentials],
        cookie_prefix: str = SIMPLE_CHATBOT_AUTH_COOKIE_PREFIX,
        session_max_age_seconds: int = SIMPLE_CHATBOT_AUTH_MAX_AGE_SECONDS,
    ):
        self.session_secret = session_secret
        self.credentials = credentials
        self.cookie_prefix = cookie_prefix
        self.session_max_age_seconds = session_max_age_seconds
        self.session_serializer = URLSafeTimedSerializer(session_secret, salt="simple-chatbot-auth-session")

    def is_protected_chatbot(self, chatbot_name: str | None) -> bool:
        return bool(chatbot_name) and chatbot_name in self.credentials

    def get_session_cookie_name(self, chatbot_name: str) -> str:
        safe_chatbot_name = re.sub(r"[^a-z0-9_-]+", "-", chatbot_name.lower()).strip("-")
        return f"{self.cookie_prefix}_{safe_chatbot_name}"

    def verify_credentials(self, chatbot_name: str, username: str, password: str) -> SimpleChatbotSession | None:
        credentials = self.credentials.get(chatbot_name)
        if credentials is None:
            return None

        normalized_username = username.strip()
        if normalized_username not in credentials.usernames:
            return None
        if not hmac.compare_digest(password, credentials.password):
            return None

        return SimpleChatbotSession(chatbot_name=chatbot_name, user=normalized_username)

    def create_session_token(self, session: SimpleChatbotSession) -> str:
        return self.session_serializer.dumps({"chatbot_name": session.chatbot_name, "user": session.user})

    def load_session(self, chatbot_name: str, session_token: str | None) -> SimpleChatbotSession | None:
        if not session_token:
            return None

        try:
            session_payload = self.session_serializer.loads(
                session_token,
                max_age=self.session_max_age_seconds,
            )
        except (BadSignature, SignatureExpired):
            return None

        if not isinstance(session_payload, dict):
            return None

        session_chatbot_name = session_payload.get("chatbot_name")
        session_user = session_payload.get("user")
        if session_chatbot_name != chatbot_name or not isinstance(session_user, str):
            return None

        credentials = self.credentials.get(chatbot_name)
        if credentials is None or session_user not in credentials.usernames:
            return None

        return SimpleChatbotSession(chatbot_name=chatbot_name, user=session_user)

    def set_session_cookie(self, response, session: SimpleChatbotSession, *, secure: bool) -> None:
        response.set_cookie(
            self.get_session_cookie_name(session.chatbot_name),
            self.create_session_token(session),
            max_age=self.session_max_age_seconds,
            httponly=True,
            secure=secure,
            samesite="Lax",
            path="/",
        )

    def clear_session_cookie(self, response, chatbot_name: str) -> None:
        response.delete_cookie(self.get_session_cookie_name(chatbot_name), path="/", samesite="Lax")
