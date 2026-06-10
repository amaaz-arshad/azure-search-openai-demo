from quart import Response as QuartResponse

from core.simplechatbotauth import (
    SIMPLE_CHATBOT_AUTH_COOKIE_PREFIX,
    SimpleChatbotAuthStore,
    SimpleChatbotCredentials,
    SimpleChatbotSession,
)


def make_store() -> SimpleChatbotAuthStore:
    return SimpleChatbotAuthStore(
        session_secret="unit-test-secret",
        credentials={"demo": SimpleChatbotCredentials(usernames=frozenset({"demouser"}), password="demo@123")},
    )


def get_demo_cookie_header(response: QuartResponse) -> str | None:
    cookie_name = f"{SIMPLE_CHATBOT_AUTH_COOKIE_PREFIX}_demo"
    for value in response.headers.getlist("Set-Cookie"):
        if value.startswith(f"{cookie_name}="):
            return value
    return None


def test_set_session_cookie_secure_is_partitioned_cross_site():
    """Over HTTPS the login cookie must work inside a cross-site iframe (the embeddable widget)."""
    store = make_store()
    response = QuartResponse("")
    store.set_session_cookie(response, SimpleChatbotSession(chatbot_name="demo", user="demouser"), secure=True)

    header = get_demo_cookie_header(response)
    assert header is not None
    lowered = header.lower()
    assert "; secure" in lowered
    assert "samesite=none" in lowered
    assert "; partitioned" in lowered
    assert "; httponly" in lowered


def test_set_session_cookie_insecure_stays_lax():
    """On plain HTTP (local dev) SameSite=None would be rejected, so keep the original Lax cookie."""
    store = make_store()
    response = QuartResponse("")
    store.set_session_cookie(response, SimpleChatbotSession(chatbot_name="demo", user="demouser"), secure=False)

    header = get_demo_cookie_header(response)
    assert header is not None
    lowered = header.lower()
    assert "samesite=lax" in lowered
    assert "; partitioned" not in lowered
    assert "; secure" not in lowered


def test_clear_session_cookie_secure_matches_set_attributes():
    """Deletion must mirror the set attributes or the browser keeps the partitioned cookie."""
    store = make_store()
    response = QuartResponse("")
    store.clear_session_cookie(response, "demo", secure=True)

    header = get_demo_cookie_header(response)
    assert header is not None
    lowered = header.lower()
    assert "samesite=none" in lowered
    assert "; partitioned" in lowered
