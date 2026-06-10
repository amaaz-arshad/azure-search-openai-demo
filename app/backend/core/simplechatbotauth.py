import hmac
import re
from dataclasses import dataclass

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

SIMPLE_CHATBOT_AUTH_COOKIE_PREFIX = "chatbot_basic_auth"
SIMPLE_CHATBOT_AUTH_MAX_AGE_SECONDS = 60 * 60 * 12
SIMPLE_CHATBOT_AUTH_REQUIRED_MESSAGE = "Chatbot authentication required."
SIMPLE_CHATBOT_AUTH_INVALID_CREDENTIALS_MESSAGE = "Incorrect username or password."


def mark_set_cookie_partitioned(response, cookie_name: str) -> None:
    """Append the `Partitioned` (CHIPS) attribute to a previously emitted Set-Cookie header.

    Quart/Werkzeug `set_cookie` does not yet expose a `partitioned` parameter, so we patch the
    header in place. Partitioned cookies let the per-chatbot login cookie work inside a
    cross-site iframe (the embeddable widget) without relying on third-party cookies.
    """
    set_cookie_values = response.headers.getlist("Set-Cookie")
    if not set_cookie_values:
        return
    patched = []
    for value in set_cookie_values:
        if value.startswith(f"{cookie_name}=") and "Partitioned" not in value:
            value = f"{value}; Partitioned"
        patched.append(value)
    response.headers.setlist("Set-Cookie", patched)


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
        cookie_name = self.get_session_cookie_name(session.chatbot_name)
        # When served over HTTPS we want the login cookie to survive inside a cross-site
        # iframe (the embeddable widget), which requires SameSite=None; Secure; Partitioned
        # (CHIPS). On plain HTTP (local dev) SameSite=None would be rejected, so fall back to
        # the original Lax behaviour. Quart's set_cookie has no "partitioned" parameter, so the
        # attribute is appended to the emitted Set-Cookie header afterwards.
        response.set_cookie(
            cookie_name,
            self.create_session_token(session),
            max_age=self.session_max_age_seconds,
            httponly=True,
            secure=secure,
            samesite="None" if secure else "Lax",
            path="/",
        )
        if secure:
            mark_set_cookie_partitioned(response, cookie_name)

    def clear_session_cookie(self, response, chatbot_name: str, *, secure: bool = False) -> None:
        cookie_name = self.get_session_cookie_name(chatbot_name)
        # Deletion must match the attributes the cookie was set with, otherwise the browser
        # keeps the partitioned cross-site cookie around.
        response.delete_cookie(
            cookie_name,
            path="/",
            secure=secure,
            samesite="None" if secure else "Lax",
        )
        if secure:
            mark_set_cookie_partitioned(response, cookie_name)
