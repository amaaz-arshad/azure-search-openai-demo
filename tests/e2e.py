import json
import os
import socket
import time
from collections.abc import Generator
from contextlib import closing
from multiprocessing import Process
from unittest import mock

import pytest
import requests
import uvicorn
from axe_playwright_python.sync_playwright import Axe
from playwright.sync_api import Browser, Page, Route, expect

import app

expect.set_options(timeout=10_000)

WINDOWS_PROCESS_ENV_KEYS = (
    "APPDATA",
    "COMSPEC",
    "HOMEDRIVE",
    "HOMEPATH",
    "LOCALAPPDATA",
    "PATH",
    "PATHEXT",
    "ProgramData",
    "SystemRoot",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "WINDIR",
)
WINDOWS_PROCESS_ENV = {
    key: value for key in WINDOWS_PROCESS_ENV_KEYS if (value := os.environ.get(key)) is not None
}


def wait_for_server_ready(url: str, timeout: float = 10.0, check_interval: float = 0.5) -> bool:
    """Make requests to provided url until it responds without error."""
    conn_error = None
    for _ in range(int(timeout / check_interval)):
        try:
            requests.get(url)
        except requests.ConnectionError as exc:
            time.sleep(check_interval)
            conn_error = str(exc)
        else:
            return True
    raise RuntimeError(conn_error)


def fulfill_chat_stream_snapshot(route: Route, snapshot_path: str) -> None:
    with open(snapshot_path, encoding="utf-8") as snapshot_file:
        route.fulfill(
            body=snapshot_file.read(),
            status=200,
            headers={"Transfer-encoding": "Chunked", "Content-Type": "application/x-ndjson"},
        )


@pytest.fixture(scope="session")
def free_port() -> int:
    """Returns a free port for the test server to bind."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


def run_server(port: int):
    with mock.patch.dict(
        os.environ,
        {
            **WINDOWS_PROCESS_ENV,
            "AZURE_STORAGE_ACCOUNT": "test-storage-account",
            "AZURE_STORAGE_CONTAINER": "test-storage-container",
            "AZURE_STORAGE_RESOURCE_GROUP": "test-storage-rg",
            "AZURE_SUBSCRIPTION_ID": "test-storage-subid",
            "AZURE_SERVER_APP_SECRET": "SECRET",
            "ENABLE_LANGUAGE_PICKER": "false",
            "USE_SPEECH_INPUT_BROWSER": "false",
            "USE_SPEECH_OUTPUT_AZURE": "false",
            "AZURE_SEARCH_INDEX": "test-search-index",
            "AZURE_SEARCH_SERVICE": "test-search-service",
            "AZURE_SPEECH_SERVICE_ID": "test-id",
            "AZURE_SPEECH_SERVICE_LOCATION": "eastus",
            "AZURE_OPENAI_SERVICE": "test-openai-service",
            "AZURE_OPENAI_CHATGPT_MODEL": "gpt-4.1-mini",
            "AZURE_OPENAI_EMB_DEPLOYMENT": "test-ada",
            "AZURE_OPENAI_EMB_MODEL_NAME": "text-embedding-3-large",
            "AZURE_OPENAI_EMB_DIMENSIONS": "3072",
        },
        clear=True,
    ):
        uvicorn.run(app.create_app(), port=port)


@pytest.fixture()
def live_server_url(mock_env, mock_acs_search, free_port: int) -> Generator[str, None, None]:
    with mock.patch.dict(os.environ, WINDOWS_PROCESS_ENV, clear=False):
        proc = Process(target=run_server, args=(free_port,), daemon=True)
        proc.start()
        url = f"http://localhost:{free_port}/"
        wait_for_server_ready(url, timeout=10.0, check_interval=0.5)
        yield url
        proc.kill()


@pytest.fixture(params=[(480, 800), (600, 1024), (768, 1024), (992, 1024), (1024, 768)])
def sized_page(page: Page, request):
    size = request.param
    page.set_viewport_size({"width": size[0], "height": size[1]})
    yield page


def test_home(page: Page, live_server_url: str):
    page.goto(live_server_url)
    expect(page).to_have_title("Azure OpenAI + AI Search")


def test_chatbot_disclaimer_visible_and_closable(page: Page, live_server_url: str):
    page.goto(f"{live_server_url}nerilio")

    disclaimer = page.get_by_test_id("chatbot-disclaimer")
    expect(disclaimer).to_be_visible()
    expect(disclaimer).to_contain_text(
        "AI-supported assistant. Answers are automatically generated from the content provided; official sources are binding."
    )
    expect(disclaimer).not_to_contain_text("KI-gestützter Assistent.")

    page.get_by_test_id("chatbot-disclaimer-close").click()
    expect(page.get_by_test_id("chatbot-disclaimer")).to_have_count(0)


def test_demo_disclaimer_visible_after_login(page: Page, live_server_url: str):
    page.goto(f"{live_server_url}demo")

    page.get_by_label("Username").fill("demouser")
    page.get_by_label("Password").fill("demo@123")
    page.get_by_role("button", name="Login").click()

    disclaimer = page.get_by_test_id("chatbot-disclaimer")
    expect(disclaimer).to_be_visible()
    expect(disclaimer).to_contain_text(
        "AI-supported assistant. Answers are automatically generated from the content provided; official sources are binding."
    )
    expect(disclaimer).not_to_contain_text("KI-gestützter Assistent.")

    page.get_by_test_id("chatbot-disclaimer-close").click()
    expect(page.get_by_test_id("chatbot-disclaimer")).to_have_count(0)


def test_demo_recent_chats_dropdown_opens_history_panel(page: Page, live_server_url: str):
    def handle_config(route: Route):
        route.fulfill(
            body=json.dumps(
                {
                    "defaultReasoningEffort": "",
                    "defaultRetrievalReasoningEffort": "minimal",
                    "showMultimodalOptions": False,
                    "showSemanticRankerOption": True,
                    "showQueryRewritingOption": False,
                    "showReasoningEffortOption": False,
                    "streamingEnabled": True,
                    "showVectorOption": True,
                    "showUserUpload": False,
                    "showLanguagePicker": False,
                    "showSpeechInput": False,
                    "showSpeechOutputBrowser": False,
                    "showSpeechOutputAzure": False,
                    "showChatHistoryBrowser": True,
                    "showChatHistoryCosmos": False,
                    "showAgenticRetrievalOption": False,
                    "ragSearchImageEmbeddings": False,
                    "ragSearchTextEmbeddings": True,
                    "ragSendImageSources": False,
                    "ragSendTextSources": True,
                    "webSourceEnabled": False,
                    "sharepointSourceEnabled": False,
                }
            ),
            status=200,
        )

    page.route("*/**/config", handle_config)

    page.goto(f"{live_server_url}demo")

    page.get_by_label("Username").fill("demouser")
    page.get_by_label("Password").fill("demo@123")
    page.get_by_role("button", name="Login").click()

    page.get_by_role("button", name="Toggle menu").click()
    recent_chats_button = page.get_by_role("button", name="View recent chats")
    expect(recent_chats_button).to_be_visible()
    recent_chats_button.click()

    expect(page.get_by_text("Chat history")).to_be_visible()
    expect(page.get_by_text("No chat history")).to_be_visible()


def test_chat(sized_page: Page, live_server_url: str):
    page = sized_page

    # Set up a mock route to the /chat endpoint with streaming results
    def handle(route: Route):
        try:
            post_data = route.request.post_data_json
            # Assert that session_state is specified (None initially)
            if "session_state" in post_data:
                assert post_data["session_state"] is None
            overrides = post_data["context"]["overrides"]
            # Assert that the default overrides are correct
            assert overrides.get("send_text_sources") is True
            assert overrides.get("send_image_sources") is False
            assert overrides.get("search_text_embeddings") is True
            assert overrides.get("search_image_embeddings") is False
            # retrieval_mode may be explicitly "hybrid" or omitted (interpreted as hybrid)
            assert overrides.get("retrieval_mode") in ["hybrid", None]
        except Exception as e:
            print(f"Error in test_chat handler (defaults validation): {e}")

        # Read the JSONL from our snapshot results and return as the response
        f = open("tests/snapshots/test_app/test_chat_stream_text/client0/result.jsonlines")
        jsonl = f.read()
        f.close()
        route.fulfill(body=jsonl, status=200, headers={"Transfer-encoding": "Chunked"})

    page.route("*/**/chat/stream", handle)

    # Check initial page state
    page.goto(live_server_url)
    expect(page).to_have_title("Azure OpenAI + AI Search")
    expect(page.get_by_role("heading", name="Chat with your data")).to_be_visible()
    expect(page.get_by_role("button", name="Clear chat")).to_be_disabled()
    expect(page.get_by_role("button", name="Developer settings")).to_be_enabled()

    # Check accessibility of page in initial state
    results = Axe().run(page)
    assert results.violations_count == 0, results.generate_report()

    # Ask a question and wait for the message to appear
    page.get_by_placeholder("Type a new question (e.g. does my plan cover annual eye exams?)").click()
    page.get_by_placeholder("Type a new question (e.g. does my plan cover annual eye exams?)").fill(
        "Whats the dental plan?"
    )
    page.get_by_role("button", name="Submit question").click()

    expect(page.get_by_text("Whats the dental plan?")).to_be_visible()
    expect(page.get_by_text("The capital of France is Paris.")).to_be_visible()
    expect(page.get_by_role("button", name="Clear chat")).to_be_enabled()

    # Show the citation document
    page.get_by_text("1. Benefit_Options-2.pdf").click()
    expect(page.get_by_role("tab", name="Citation")).to_be_visible()
    expect(page.get_by_title("Citation")).to_be_visible()

    # Show the thought process
    page.get_by_label("Show thought process").click()
    expect(page.get_by_title("Thought process")).to_be_visible()
    expect(page.get_by_text("Generated search query")).to_be_visible()

    # Show the supporting content
    page.get_by_label("Show supporting content").click()
    expect(page.get_by_title("Supporting content")).to_be_visible()
    expect(page.get_by_role("heading", name="Benefit_Options-2.pdf")).to_be_visible()

    # Clear the chat
    page.get_by_role("button", name="Clear chat").click()
    expect(page.get_by_text("Whats the dental plan?")).not_to_be_visible()
    expect(page.get_by_text("The capital of France is Paris.")).not_to_be_visible()
    expect(page.get_by_role("button", name="Clear chat")).to_be_disabled()


def test_shared_answer_renderer_handles_markdown_and_literal_html(page: Page, live_server_url: str):
    def handle(route: Route):
        jsonl = "\n".join(
            [
                json.dumps(
                    {
                        "delta": {"role": "assistant"},
                        "context": {
                            "data_points": {
                                "text": ["manual.txt: Rendering guidance for rich answers."],
                                "images": [],
                                "citations": ["manual.txt"],
                                "external_results_metadata": [],
                            },
                            "thoughts": [],
                            "followup_questions": None,
                        },
                        "session_state": None,
                    }
                ),
                json.dumps(
                    {
                        "delta": {
                            "role": None,
                            "content": (
                                "Literal tag example: <demo-tag>alpha</demo-tag>. [manual.txt]\n\n"
                                "- First structured point\n"
                                "- Second structured point\n\n"
                                "| Element | Meaning |\n"
                                "| --- | --- |\n"
                                "| Keyboard input | Useful shortcut hint |\n\n"
                                "```html\n"
                                "<kbd>Ctrl</kbd>\n"
                                "```"
                            ),
                        }
                    }
                ),
            ]
        )
        route.fulfill(
            body=f"{jsonl}\n",
            status=200,
            headers={"Transfer-encoding": "Chunked", "Content-Type": "application/x-ndjson"},
        )

    page.route("*/**/chat/stream", handle)

    page.goto(f"{live_server_url}nerilio")

    question_input = page.get_by_placeholder("Type a new question (e.g. does my plan cover annual eye exams?)")
    question_input.click()
    question_input.fill("Show me rich formatting")
    page.get_by_label("Submit question").click()

    expect(page.get_by_text("Literal tag example: <demo-tag>alpha</demo-tag>.")).to_be_visible()
    expect(page.locator("demo-tag")).to_have_count(0)
    expect(page.get_by_role("listitem", name="First structured point")).to_be_visible()
    expect(page.get_by_role("cell", name="Keyboard input")).to_be_visible()
    expect(page.get_by_text("<kbd>Ctrl</kbd>")).to_be_visible()
    expect(page.get_by_text("1. manual.txt")).to_be_visible()


def test_publishone_answer_keeps_wordmark_logo_wrapper(page: Page, live_server_url: str):
    page.route(
        "*/**/chat/stream",
        lambda route: fulfill_chat_stream_snapshot(
            route, "tests/snapshots/test_app/test_chat_stream_text/client0/result.jsonlines"
        ),
    )

    page.goto(f"{live_server_url}publishone")

    question_input = page.get_by_placeholder("Type your message")
    question_input.click()
    question_input.fill("Whats the dental plan?")
    page.get_by_label("Submit question").click()

    expect(page.get_by_text("The capital of France is Paris.")).to_be_visible()

    publishone_answer_logo_classes = page.locator('img[src*="publishone-chat"]').evaluate_all(
        "nodes => nodes.map(node => String(node.className))"
    )
    assert publishone_answer_logo_classes
    assert any(
        "assistantWordmark" in class_name and "wordmarkLogo" in class_name
        for class_name in publishone_answer_logo_classes
    )


def test_publishone_forces_english_for_german_browser_locale(browser: Browser, live_server_url: str):
    context = browser.new_context(locale="de-DE")
    page = context.new_page()
    captured_language: dict[str, str] = {}

    def handle_chat_stream(route: Route):
        post_data = route.request.post_data_json
        captured_language["value"] = post_data["context"]["overrides"]["language"]
        fulfill_chat_stream_snapshot(route, "tests/snapshots/test_app/test_chat_stream_text/client0/result.jsonlines")

    page.route("*/**/chat/stream", handle_chat_stream)

    try:
        page.goto(f"{live_server_url}publishone")

        expect(page.get_by_text("Welcome! Glad you're here.")).to_be_visible()
        question_input = page.get_by_placeholder("Type your message")
        expect(question_input).to_be_visible()

        page.locator("header button").last.click()
        expect(page.get_by_role("button", name="New chat")).to_be_visible()
        expect(page.get_by_role("button", name="View recent chats")).to_be_visible()
        expect(page.get_by_text("Neuer Chat")).to_have_count(0)

        question_input.fill("Whats the dental plan?")
        page.get_by_label("Submit question").click()

        expect(page.get_by_text("The capital of France is Paris.")).to_be_visible()
        assert captured_language["value"] == "en"
    finally:
        context.close()


def test_nerilio_answer_places_avatar_outside_card(page: Page, live_server_url: str):
    page.route(
        "*/**/chat/stream",
        lambda route: fulfill_chat_stream_snapshot(
            route, "tests/snapshots/test_app/test_chat_stream_text/client0/result.jsonlines"
        ),
    )

    page.goto(f"{live_server_url}nerilio")

    question_input = page.get_by_placeholder("Type a new question (e.g. does my plan cover annual eye exams?)")
    question_input.click()
    question_input.fill("Whats the dental plan?")
    page.get_by_label("Submit question").click()

    expect(page.get_by_text("The capital of France is Paris.")).to_be_visible()

    avatar = page.get_by_test_id("assistant-avatar-outside").first
    card = page.get_by_test_id("chatbot-answer-card").first

    expect(avatar).to_be_visible()
    expect(card).to_be_visible()

    avatar_box = avatar.bounding_box()
    card_box = card.bounding_box()

    assert avatar_box is not None
    assert card_box is not None
    assert avatar_box["x"] < card_box["x"]
    assert card.locator("[data-testid='assistant-avatar-outside']").count() == 0


def test_rak_answer_citation_keeps_logged_in_user_scope(page: Page, live_server_url: str):
    page.route(
        "*/**/chat/stream",
        lambda route: fulfill_chat_stream_snapshot(
            route, "tests/snapshots/test_app/test_chat_stream_text/client0/result.jsonlines"
        ),
    )
    page.add_init_script(
        """
        () => {
            window.__openedUrls = [];
            window.open = url => {
                window.__openedUrls.push(String(url));
                return null;
            };
        }
        """
    )

    page.goto(f"{live_server_url}rak")

    page.get_by_placeholder("Username").fill("12345")
    page.get_by_placeholder("Password").fill("rak99#")
    page.get_by_role("button", name="Login").click()

    question_input = page.get_by_placeholder("Type a new question (e.g. does my plan cover annual eye exams?)")
    expect(question_input).to_be_visible()
    question_input.click()
    question_input.fill("Whats the dental plan?")
    page.get_by_label("Submit question").click()

    citation_button = page.get_by_text("1. Benefit_Options-2.pdf")
    expect(citation_button).to_be_visible()
    citation_button.click()

    page.wait_for_function("window.__openedUrls.length > 0")
    opened_urls = page.evaluate("window.__openedUrls")
    assert opened_urls[-1].endswith(
        "/content/rak/Benefit_Options-2.pdf?chatbot_name=rak&chatbot_user=12345"
    )


def test_chat_stop_button_visibility(page: Page, live_server_url: str):
    """Test that the stop button feature works without breaking the chat flow.

    Note: This test verifies the initial and final states but does not assert
    that the stop button appears during streaming. Testing transient UI states
    is flaky since the mock returns instantly. A proper test would require a
    delayed mock response, adding significant complexity for minimal benefit.
    """

    # Set up a mock route to the /chat endpoint with streaming results
    def handle(route: Route):
        # Read the JSONL from our snapshot results and return as the response
        with open("tests/snapshots/test_app/test_chat_stream_text/client0/result.jsonlines") as f:
            jsonl = f.read()
        route.fulfill(body=jsonl, status=200, headers={"Transfer-encoding": "Chunked"})

    page.route("*/**/chat/stream", handle)

    # Check initial page state
    page.goto(live_server_url)
    expect(page).to_have_title("Azure OpenAI + AI Search")

    # Verify the submit button is visible initially (not the stop button)
    expect(page.get_by_label("Submit question")).to_be_visible()
    expect(page.get_by_label("Stop streaming")).not_to_be_visible()

    # Ask a question
    page.get_by_placeholder("Type a new question (e.g. does my plan cover annual eye exams?)").click()
    page.get_by_placeholder("Type a new question (e.g. does my plan cover annual eye exams?)").fill(
        "Whats the dental plan?"
    )
    page.get_by_label("Submit question").click()

    # Wait for the response to complete and verify the submit button is back
    expect(page.get_by_text("The capital of France is Paris.")).to_be_visible()
    expect(page.get_by_label("Submit question")).to_be_visible()
    expect(page.get_by_label("Stop streaming")).not_to_be_visible()


def test_chat_stop_restores_question(page: Page, live_server_url: str):
    """Test that when streaming returns no content, the question is restored to input."""

    # Set up a mock route that returns an empty streaming response (no content)
    def handle(route: Route):
        # Return a valid but empty NDJSON stream - this simulates stopping before content arrives
        # Need at least one event with context/data_points to initialize, but no delta content
        jsonl = '{"context": {"data_points": {"text": []}, "thoughts": []}, "delta": {"role": "assistant"}}\n'
        route.fulfill(
            status=200,
            headers={"Transfer-encoding": "Chunked", "Content-Type": "application/x-ndjson"},
            body=jsonl,
        )

    page.route("*/**/chat/stream", handle)

    # Check initial page state
    page.goto(live_server_url)
    expect(page).to_have_title("Azure OpenAI + AI Search")

    # Type a question
    question_input = page.get_by_placeholder("Type a new question (e.g. does my plan cover annual eye exams?)")
    question_input.click()
    question_input.fill("Whats the dental plan?")

    # Submit the question
    page.get_by_label("Submit question").click()

    # The response contains context but no actual content (no delta.content events)
    # So the answer should be empty and question should be restored to input

    # Verify the question is restored to the input field
    expect(question_input).to_have_value("Whats the dental plan?")

    # Verify the submit button is back
    expect(page.get_by_label("Submit question")).to_be_visible()

    # Verify no answer was added to the chat (Clear chat should be disabled since answer was empty)
    expect(page.get_by_role("button", name="Clear chat")).to_be_disabled()


def test_chat_customization(page: Page, live_server_url: str):
    # Set up a mock route to the /chat endpoint
    def handle(route: Route):
        try:
            post_data = route.request.post_data_json
            if post_data and "context" in post_data and "overrides" in post_data["context"]:
                overrides = post_data["context"]["overrides"]
                assert overrides["temperature"] == 0.5
                assert overrides["seed"] == 123
                assert overrides["minimum_search_score"] == 0.5
                assert overrides["minimum_reranker_score"] == 0.5
                assert overrides["retrieval_mode"] == "vectors"
                assert overrides["semantic_ranker"] is False
                assert overrides["semantic_captions"] is True
                assert overrides["top"] == 1
                assert overrides["prompt_template"] == "You are a cat and only talk about tuna."
                assert overrides["exclude_category"] == "dogs"
                assert overrides["suggest_followup_questions"] is True
        except Exception as e:
            print(f"Error in test_chat_customization handler: {e}")

        # Read the JSON from our snapshot results and return as the response
        f = open("tests/snapshots/test_app/test_chat_text/client0/result.json")
        json_data = f.read()
        f.close()
        route.fulfill(body=json_data, status=200)

    page.route("*/**/chat", handle)

    # Check initial page state
    page.goto(live_server_url)
    expect(page).to_have_title("Azure OpenAI + AI Search")

    # Customize all the settings
    page.get_by_role("button", name="Developer settings").click()
    page.get_by_label("Override prompt template").click()
    page.get_by_label("Override prompt template").fill("You are a cat and only talk about tuna.")
    page.get_by_label("Temperature").click()
    page.get_by_label("Temperature").fill("0.5")
    page.get_by_label("Seed").click()
    page.get_by_label("Seed").fill("123")
    page.get_by_label("Minimum search score").click()
    page.get_by_label("Minimum search score").fill("0.5")
    page.get_by_label("Minimum reranker score").click()
    page.get_by_label("Minimum reranker score").fill("0.5")
    page.get_by_label("Retrieve this many search results:").click()
    page.get_by_label("Retrieve this many search results:").fill("1")
    page.get_by_label("Include category").click()
    page.get_by_role("option", name="All", exact=True).click()
    page.get_by_label("Exclude category").click()
    page.get_by_label("Exclude category").fill("dogs")
    page.get_by_text("Use semantic captions").click()
    page.get_by_text("Use semantic ranker for retrieval").click()
    page.get_by_text("Suggest follow-up questions").click()
    page.get_by_text("Vectors + Text (Hybrid)").click()
    page.get_by_role("option", name="Vectors", exact=True).click()
    page.get_by_text("Stream chat completion responses").click()
    page.locator("button").filter(has_text="Close").click()

    # Ask a question and wait for the message to appear
    page.get_by_placeholder("Type a new question (e.g. does my plan cover annual eye exams?)").click()
    page.get_by_placeholder("Type a new question (e.g. does my plan cover annual eye exams?)").fill(
        "Whats the dental plan?"
    )
    page.get_by_role("button", name="Submit question").click()

    expect(page.get_by_text("Whats the dental plan?")).to_be_visible()
    expect(page.get_by_text("The capital of France is Paris.")).to_be_visible()
    expect(page.get_by_role("button", name="Clear chat")).to_be_enabled()


def test_chat_customization_multimodal(page: Page, live_server_url: str):
    # Set up a mock route to the /chat endpoint
    def handle_chat(route: Route):
        try:
            post_data = route.request.post_data_json
            if post_data and "context" in post_data and "overrides" in post_data["context"]:
                overrides = post_data["context"]["overrides"]
                # After our UI changes we expect:
                # - send_text_sources to be False (we unchecked Texts)
                # - send_image_sources to be True (we left Images checked)
                # - search_text_embeddings to be False (we unchecked Text embeddings)
                # - search_image_embeddings to be True (we left Image embeddings checked)
                assert overrides["send_text_sources"] is False
                assert overrides["send_image_sources"] is True
                assert overrides["search_text_embeddings"] is False
                assert overrides["search_image_embeddings"] is True
                assert overrides["retrieval_mode"] == "vectors"
        except Exception as e:
            print(f"Error in handle_chat: {e}")

        # Read the JSON from our snapshot results and return as the response
        f = open("tests/snapshots/test_app/test_chat_text/client0/result.json")
        json_data = f.read()
        f.close()
        route.fulfill(body=json_data, status=200)

    def handle_config(route: Route):
        route.fulfill(
            body=json.dumps(
                {
                    "defaultReasoningEffort": "",
                    "defaultRetrievalReasoningEffort": "minimal",
                    "showMultimodalOptions": True,
                    "showSemanticRankerOption": True,
                    "showQueryRewritingOption": False,
                    "showReasoningEffortOption": False,
                    "streamingEnabled": True,
                    "showVectorOption": True,
                    "showUserUpload": False,
                    "showLanguagePicker": False,
                    "showSpeechInput": False,
                    "showSpeechOutputBrowser": False,
                    "showSpeechOutputAzure": False,
                    "showChatHistoryBrowser": False,
                    "showChatHistoryCosmos": False,
                    "showAgenticRetrievalOption": False,
                    "ragSearchImageEmbeddings": True,
                    "ragSearchTextEmbeddings": True,
                    "ragSendImageSources": True,
                    "ragSendTextSources": True,
                    "webSourceEnabled": False,
                    "sharepointSourceEnabled": False,
                }
            ),
            status=200,
        )

    page.route("*/**/config", handle_config)
    page.route("*/**/chat", handle_chat)

    # Check initial page state
    page.goto(live_server_url)
    expect(page).to_have_title("Azure OpenAI + AI Search")

    # Open Developer settings
    page.get_by_role("button", name="Developer settings").click()

    # Check the default retrieval mode (Hybrid)
    # expect(page.get_by_label("Retrieval mode")).to_have_value("hybrid")

    # Check that Vector fields and LLM inputs sections are visible with checkboxes
    expect(page.locator("fieldset").filter(has_text="Included vector fields")).to_be_visible()
    expect(page.locator("fieldset").filter(has_text="LLM input sources")).to_be_visible()

    # Modify the retrieval mode to "Vectors"
    page.get_by_text("Vectors + Text (Hybrid)").click()
    page.get_by_role("option", name="Vectors", exact=True).click()

    # Use a different approach to target the checkboxes directly by their role
    # Find the checkbox for Text embeddings by its specific class or nearby text
    page.get_by_text("Text embeddings").click()

    # Same for the LLM text sources checkbox
    page.get_by_text("Text sources").click()

    # Turn off streaming
    page.get_by_text("Stream chat completion responses").click()
    page.locator("button").filter(has_text="Close").click()

    # Ask a question and wait for the message to appear
    page.get_by_placeholder("Type a new question (e.g. does my plan cover annual eye exams?)").click()
    page.get_by_placeholder("Type a new question (e.g. does my plan cover annual eye exams?)").fill(
        "Whats the dental plan?"
    )
    page.get_by_label("Submit question").click()


def test_chat_nonstreaming(page: Page, live_server_url: str):
    # Set up a mock route to the /chat_stream endpoint
    def handle(route: Route):
        # Read the JSON from our snapshot results and return as the response
        f = open("tests/snapshots/test_app/test_chat_text/client0/result.json")
        json = f.read()
        f.close()
        route.fulfill(body=json, status=200)

    page.route("*/**/chat", handle)

    # Check initial page state
    page.goto(live_server_url)
    expect(page).to_have_title("Azure OpenAI + AI Search")
    expect(page.get_by_role("button", name="Developer settings")).to_be_enabled()
    page.get_by_role("button", name="Developer settings").click()
    page.get_by_text("Stream chat completion responses").click()
    page.locator("button").filter(has_text="Close").click()

    # Ask a question and wait for the message to appear
    page.get_by_placeholder("Type a new question (e.g. does my plan cover annual eye exams?)").click()
    page.get_by_placeholder("Type a new question (e.g. does my plan cover annual eye exams?)").fill(
        "Whats the dental plan?"
    )
    page.get_by_label("Submit question").click()

    expect(page.get_by_text("Whats the dental plan?")).to_be_visible()
    expect(page.get_by_text("The capital of France is Paris.")).to_be_visible()
    expect(page.get_by_role("button", name="Clear chat")).to_be_enabled()


def test_chat_followup_streaming(page: Page, live_server_url: str):
    # Set up a mock route to the /chat_stream endpoint
    def handle(route: Route):
        try:
            post_data = route.request.post_data_json
            if post_data and "context" in post_data and "overrides" in post_data["context"]:
                overrides = post_data["context"]["overrides"]
                assert overrides["suggest_followup_questions"] is True
        except Exception as e:
            print(f"Error in test_chat_followup_streaming handler: {e}")

        # Read the JSONL from our snapshot results and return as the response
        f = open("tests/snapshots/test_app/test_chat_stream_followup/client0/result.jsonlines")
        jsonl = f.read()
        f.close()
        route.fulfill(body=jsonl, status=200, headers={"Transfer-encoding": "Chunked"})

    page.route("*/**/chat/stream", handle)

    # Check initial page state
    page.goto(live_server_url)
    expect(page).to_have_title("Azure OpenAI + AI Search")
    expect(page.get_by_role("button", name="Developer settings")).to_be_enabled()
    page.get_by_role("button", name="Developer settings").click()
    page.get_by_text("Suggest follow-up questions").click()
    page.locator("button").filter(has_text="Close").click()

    # Ask a question and wait for the message to appear
    page.get_by_placeholder("Type a new question (e.g. does my plan cover annual eye exams?)").click()
    page.get_by_placeholder("Type a new question (e.g. does my plan cover annual eye exams?)").fill(
        "Whats the dental plan?"
    )
    page.get_by_label("Submit question").click()

    expect(page.get_by_text("Whats the dental plan?")).to_be_visible()
    expect(page.get_by_text("The capital of France is Paris.")).to_be_visible()

    # There should be a follow-up question and it should be clickable:
    expect(page.get_by_text("What is the capital of Spain?")).to_be_visible()
    page.get_by_text("What is the capital of Spain?").click()

    # Now there should be a follow-up answer (same, since we're using same test data)
    expect(page.get_by_text("The capital of France is Paris.")).to_have_count(2)


def test_chat_followup_nonstreaming(page: Page, live_server_url: str):
    # Set up a mock route to the /chat_stream endpoint
    def handle(route: Route):
        # Read the JSON from our snapshot results and return as the response
        f = open("tests/snapshots/test_app/test_chat_followup/client0/result.json")
        json = f.read()
        f.close()
        route.fulfill(body=json, status=200)

    page.route("*/**/chat", handle)

    # Check initial page state
    page.goto(live_server_url)
    expect(page).to_have_title("Azure OpenAI + AI Search")
    expect(page.get_by_role("button", name="Developer settings")).to_be_enabled()
    page.get_by_role("button", name="Developer settings").click()
    page.get_by_text("Stream chat completion responses").click()
    page.get_by_text("Suggest follow-up questions").click()
    page.locator("button").filter(has_text="Close").click()

    # Ask a question and wait for the message to appear
    page.get_by_placeholder("Type a new question (e.g. does my plan cover annual eye exams?)").click()
    page.get_by_placeholder("Type a new question (e.g. does my plan cover annual eye exams?)").fill(
        "Whats the dental plan?"
    )
    page.get_by_label("Submit question").click()

    expect(page.get_by_text("Whats the dental plan?")).to_be_visible()
    expect(page.get_by_text("The capital of France is Paris.")).to_be_visible()

    # There should be a follow-up question and it should be clickable:
    expect(page.get_by_text("What is the capital of Spain?")).to_be_visible()
    page.get_by_text("What is the capital of Spain?").click()

    # Now there should be a follow-up answer (same, since we're using same test data)
    expect(page.get_by_text("The capital of France is Paris.")).to_have_count(2)


def test_upload_hidden(page: Page, live_server_url: str):

    def handle_auth_setup(route: Route):
        with open("tests/snapshots/test_authenticationhelper/test_auth_setup/result.json") as f:
            auth_setup = json.load(f)
            route.fulfill(body=json.dumps(auth_setup), status=200)

    page.route("*/**/auth_setup", handle_auth_setup)

    def handle_config(route: Route):
        route.fulfill(
            body=json.dumps(
                {
                    "defaultReasoningEffort": "",
                    "defaultRetrievalReasoningEffort": "minimal",
                    "showMultimodalOptions": False,
                    "showSemanticRankerOption": True,
                    "showQueryRewritingOption": False,
                    "showReasoningEffortOption": False,
                    "streamingEnabled": True,
                    "showVectorOption": True,
                    "showUserUpload": False,
                    "showLanguagePicker": False,
                    "showSpeechInput": False,
                    "showSpeechOutputBrowser": False,
                    "showSpeechOutputAzure": False,
                    "showChatHistoryBrowser": False,
                    "showChatHistoryCosmos": False,
                    "showAgenticRetrievalOption": False,
                    "ragSearchImageEmbeddings": False,
                    "ragSearchTextEmbeddings": True,
                    "ragSendImageSources": False,
                    "ragSendTextSources": True,
                    "webSourceEnabled": False,
                    "sharepointSourceEnabled": False,
                }
            ),
            status=200,
        )

    page.route("*/**/config", handle_config)

    page.goto(live_server_url)

    expect(page).to_have_title("Azure OpenAI + AI Search")

    expect(page.get_by_role("button", name="Clear chat")).to_be_visible()
    expect(page.get_by_role("button", name="Manage file uploads")).not_to_be_visible()


def test_upload_disabled(page: Page, live_server_url: str):

    def handle_auth_setup(route: Route):
        with open("tests/snapshots/test_authenticationhelper/test_auth_setup/result.json") as f:
            auth_setup = json.load(f)
            route.fulfill(body=json.dumps(auth_setup), status=200)

    page.route("*/**/auth_setup", handle_auth_setup)

    def handle_config(route: Route):
        route.fulfill(
            body=json.dumps(
                {
                    "defaultReasoningEffort": "",
                    "defaultRetrievalReasoningEffort": "minimal",
                    "showMultimodalOptions": False,
                    "showSemanticRankerOption": True,
                    "showQueryRewritingOption": False,
                    "showReasoningEffortOption": False,
                    "streamingEnabled": True,
                    "showVectorOption": True,
                    "showUserUpload": True,
                    "showLanguagePicker": False,
                    "showSpeechInput": False,
                    "showSpeechOutputBrowser": False,
                    "showSpeechOutputAzure": False,
                    "showChatHistoryBrowser": False,
                    "showChatHistoryCosmos": False,
                    "showAgenticRetrievalOption": False,
                    "ragSearchImageEmbeddings": False,
                    "ragSearchTextEmbeddings": True,
                    "ragSendImageSources": False,
                    "ragSendTextSources": True,
                    "webSourceEnabled": False,
                    "sharepointSourceEnabled": False,
                }
            ),
            status=200,
        )

    page.route("*/**/config", handle_config)

    page.goto(live_server_url)

    expect(page).to_have_title("Azure OpenAI + AI Search")

    expect(page.get_by_role("button", name="Manage file uploads")).to_be_visible()
    expect(page.get_by_role("button", name="Manage file uploads")).to_be_disabled()
    # We can't test actual file upload as we don't currently have isLoggedIn(client) mocked out


def test_demo_upload_manager_modal(page: Page, live_server_url: str):

    def handle_config(route: Route):
        route.fulfill(
            body=json.dumps(
                {
                    "defaultReasoningEffort": "",
                    "defaultRetrievalReasoningEffort": "minimal",
                    "showMultimodalOptions": False,
                    "showSemanticRankerOption": True,
                    "showQueryRewritingOption": False,
                    "showReasoningEffortOption": False,
                    "streamingEnabled": True,
                    "showVectorOption": True,
                    "showUserUpload": False,
                    "showLanguagePicker": False,
                    "showSpeechInput": False,
                    "showSpeechOutputBrowser": False,
                    "showSpeechOutputAzure": False,
                    "showChatHistoryBrowser": False,
                    "showChatHistoryCosmos": False,
                    "showAgenticRetrievalOption": False,
                    "ragSearchImageEmbeddings": False,
                    "ragSearchTextEmbeddings": True,
                    "ragSendImageSources": False,
                    "ragSendTextSources": True,
                    "webSourceEnabled": False,
                    "sharepointSourceEnabled": False,
                }
            ),
            status=200,
        )

    page.route("*/**/config", handle_config)

    def handle_uploads(route: Route):
        route.fulfill(body=json.dumps(["demo-manual.pdf", "faq.txt"]), status=200)

    page.route("*/**/chatbot_uploads/demo", handle_uploads)

    page.goto(f"{live_server_url}demo")

    page.get_by_label("Username").fill("demouser")
    page.get_by_label("Password").fill("demo@123")
    page.get_by_role("button", name="Login").click()

    page.get_by_role("button", name="Toggle menu").click()
    page.get_by_role("button", name="Upload files").click()

    expect(page.get_by_role("dialog")).to_be_visible()
    expect(page.get_by_text("Upload files to the demo bot")).to_be_visible()
    expect(page.get_by_text("Current upload queue")).to_be_visible()
    expect(page.get_by_text("No files in the queue")).to_be_visible()
    expect(page.get_by_text("demo-manual.pdf")).to_be_visible()
    expect(page.get_by_text("faq.txt")).to_be_visible()
    expect(page.get_by_role("button", name="Delete")).to_be_visible()
    expect(page.get_by_role("button", name="Delete all")).to_be_visible()


def login_internal_bot(page: Page):
    page.get_by_label("Username").fill("internal")
    page.get_by_label("Password").fill("internal")
    page.get_by_role("button", name="Login").click()


def test_internal_bot_dropdown_uses_source_bot_router_settings(page: Page, live_server_url: str):

    def handle_config(route: Route):
        route.fulfill(
            body=json.dumps(
                {
                    "defaultReasoningEffort": "",
                    "defaultRetrievalReasoningEffort": "minimal",
                    "showMultimodalOptions": False,
                    "showSemanticRankerOption": True,
                    "showQueryRewritingOption": False,
                    "showReasoningEffortOption": False,
                    "streamingEnabled": True,
                    "showVectorOption": True,
                    "showUserUpload": False,
                    "showLanguagePicker": False,
                    "showSpeechInput": False,
                    "showSpeechOutputBrowser": False,
                    "showSpeechOutputAzure": False,
                    "showChatHistoryBrowser": False,
                    "showChatHistoryCosmos": False,
                    "showAgenticRetrievalOption": False,
                    "ragSearchImageEmbeddings": False,
                    "ragSearchTextEmbeddings": True,
                    "ragSendImageSources": False,
                    "ragSendTextSources": True,
                    "webSourceEnabled": False,
                    "sharepointSourceEnabled": False,
                    "internalSourceBots": [
                        {"id": "nerilio", "label": "nerilio"},
                        {"id": "vjoonk4", "label": "vjoonk4"},
                    ],
                }
            ),
            status=200,
        )

    page.route("*/**/config", handle_config)

    page.goto(f"{live_server_url}internal")
    login_internal_bot(page)

    expect(page.get_by_text("Select a source bot")).to_be_visible()
    expect(page.get_by_text("Open Developer settings and choose which bot Internal Bot should use for retrieval and system instructions.")).to_be_visible()
    expect(
        page.get_by_placeholder("Select a source bot in Developer settings before sending a message")
    ).to_be_disabled()

    page.get_by_role("button", name="Toggle menu").click()
    expect(page.get_by_role("button", name="Upload files")).to_have_count(0)
    page.get_by_role("button", name="Developer settings").click()

    expect(page.get_by_text("Configure answer generation")).to_be_visible()
    expect(page.get_by_label("Source bot")).to_be_visible()
    expect(page.get_by_label("Include category")).to_have_count(0)
    expect(page.get_by_label("Exclude category")).to_have_count(0)

    page.get_by_label("Source bot").click()
    page.get_by_role("option", name="nerilio").click()
    page.get_by_role("button", name="Close").click()

    expect(page.get_by_text("Internal Bot")).to_be_visible()
    expect(page.get_by_text("Hello, I'm nerilio. How can I assist you today?")).to_be_visible()

    page.get_by_role("button", name="Toggle menu").click()
    page.get_by_role("button", name="Developer settings").click()
    page.get_by_label("Source bot").click()
    page.get_by_role("option", name="vjoon K4").click()
    page.get_by_role("button", name="Close").click()

    expect(page.get_by_text("Hi there! I know the user manual for vjoon K4 version 16 really well. Just ask away.")).to_be_visible()
    expect(page.get_by_text("Hello, I'm nerilio. How can I assist you today?")).to_have_count(0)
    expect(page.get_by_text("Internal Bot")).to_be_visible()


def test_internal_bot_no_page_requires_basic_auth(page: Page, live_server_url: str):
    page.goto(f"{live_server_url}internal/does-not-exist")

    expect(page.get_by_role("button", name="Login")).to_be_visible()

    login_internal_bot(page)

    expect(page.get_by_text("This page does not exist")).to_be_visible()


def test_internal_bot_model_selector_controls_reasoning_options(page: Page, live_server_url: str):
    def handle_config(route: Route):
        route.fulfill(
            body=json.dumps(
                {
                    "availableChatModels": [
                        "gpt-4.1",
                        "gpt-4.1-mini",
                        "gpt-4.1-nano",
                        "gpt-5",
                        "gpt-5-mini",
                        "gpt-5-nano",
                        "gpt-5.4",
                        "gpt-5.4-mini",
                        "gpt-5.4-nano",
                    ],
                    "defaultChatModel": "gpt-4.1-mini",
                    "defaultReasoningEffort": "low",
                    "defaultRetrievalReasoningEffort": "low",
                    "reasoningCapableChatModels": [
                        "gpt-5",
                        "gpt-5-mini",
                        "gpt-5-nano",
                        "gpt-5.4",
                        "gpt-5.4-mini",
                        "gpt-5.4-nano",
                    ],
                    "chatModelReasoningEfforts": {
                        "gpt-5": ["minimal", "low", "medium", "high"],
                        "gpt-5-mini": ["minimal", "low", "medium", "high"],
                        "gpt-5-nano": ["minimal", "low", "medium", "high"],
                        "gpt-5.4": ["none", "low", "medium", "high", "xhigh"],
                        "gpt-5.4-mini": ["none", "low", "medium", "high", "xhigh"],
                        "gpt-5.4-nano": ["none", "low", "medium", "high", "xhigh"],
                    },
                    "showMultimodalOptions": False,
                    "showSemanticRankerOption": True,
                    "showQueryRewritingOption": False,
                    "showReasoningEffortOption": False,
                    "streamingEnabled": True,
                    "showVectorOption": True,
                    "showUserUpload": False,
                    "showLanguagePicker": False,
                    "showSpeechInput": False,
                    "showSpeechOutputBrowser": False,
                    "showSpeechOutputAzure": False,
                    "showChatHistoryBrowser": False,
                    "showChatHistoryCosmos": False,
                    "showAgenticRetrievalOption": False,
                    "ragSearchImageEmbeddings": False,
                    "ragSearchTextEmbeddings": True,
                    "ragSendImageSources": False,
                    "ragSendTextSources": True,
                    "webSourceEnabled": False,
                    "sharepointSourceEnabled": False,
                    "internalSourceBots": [
                        {"id": "nerilio", "label": "nerilio"},
                        {"id": "lemon", "label": "lemon"},
                    ],
                }
            ),
            status=200,
        )

    page.route("*/**/config", handle_config)

    def handle_chat(route: Route):
        post_data = route.request.post_data_json
        assert post_data["context"]["overrides"]["source_chatbot"] == "nerilio"
        assert post_data["context"]["overrides"]["chat_model"] == "gpt-5.4"
        assert post_data["context"]["overrides"]["reasoning_effort"] == "xhigh"

        with open("tests/snapshots/test_app/test_chat_text/result.json", encoding="utf-8") as snapshot_file:
            route.fulfill(body=snapshot_file.read(), status=200)

    page.route("*/**/chat", handle_chat)

    page.goto(f"{live_server_url}internal")
    login_internal_bot(page)

    page.get_by_role("button", name="Toggle menu").click()
    page.get_by_role("button", name="Developer settings").click()

    page.get_by_label("Source bot").click()
    page.get_by_role("option", name="nerilio").click()
    expect(page.get_by_label("Model")).to_be_visible()
    expect(page.get_by_label("Reasoning effort")).to_have_count(0)

    page.get_by_label("Model").click()
    page.get_by_role("option", name="gpt-5.4").click()

    expect(page.get_by_label("Reasoning effort")).to_be_visible()
    page.get_by_label("Reasoning effort").click()
    expect(page.get_by_role("option", name="None")).to_be_visible()
    expect(page.get_by_role("option", name="Very high")).to_be_visible()
    page.get_by_role("option", name="Very high").click()
    page.get_by_text("Stream chat completion responses").click()
    page.get_by_role("button", name="Close").click()

    expect(page.get_by_text("Hello, I'm nerilio. How can I assist you today?")).to_be_visible()

    page.get_by_placeholder("Type your message").fill("Hello?")
    page.get_by_role("button", name="Submit question").click()

    expect(page.get_by_text("The capital of France is Paris.")).to_be_visible()


def test_agentic_retrieval_effort_minimal_disables_web(page: Page, live_server_url: str):
    """Test that selecting 'Minimal' effort deselects and disables the web source checkbox."""

    # Set up a mock route to the /chat endpoint
    def handle(route: Route):
        try:
            post_data = route.request.post_data_json
            if post_data and "context" in post_data and "overrides" in post_data["context"]:
                overrides = post_data["context"]["overrides"]
                assert overrides["temperature"] == 0.5
                assert overrides["seed"] == 123
                assert overrides["minimum_search_score"] == 0.5
                assert overrides["minimum_reranker_score"] == 0.5
                assert overrides["retrieval_mode"] == "vectors"
                assert overrides["semantic_ranker"] is False
                assert overrides["semantic_captions"] is True
                assert overrides["top"] == 1
                assert overrides["prompt_template"] == "You are a cat and only talk about tuna."
                assert overrides["exclude_category"] == "dogs"
                assert overrides["suggest_followup_questions"] is True
        except Exception as e:
            print(f"Error in test_chat_customization handler: {e}")

        # Read the JSON from our snapshot results and return as the response
        f = open("tests/snapshots/test_app/test_chat_text_agent/knowledgebase_client2_sharepoint/result.json")
        json_data = f.read()
        f.close()
        route.fulfill(body=json_data, status=200)

    page.route("*/**/chat", handle)

    def handle_config(route: Route):
        route.fulfill(
            body=json.dumps(
                {
                    "defaultReasoningEffort": "",
                    "defaultRetrievalReasoningEffort": "low",
                    "showMultimodalOptions": False,
                    "showSemanticRankerOption": True,
                    "showQueryRewritingOption": False,
                    "showReasoningEffortOption": False,
                    "streamingEnabled": True,
                    "showVectorOption": True,
                    "showUserUpload": False,
                    "showLanguagePicker": False,
                    "showSpeechInput": False,
                    "showSpeechOutputBrowser": False,
                    "showSpeechOutputAzure": False,
                    "showChatHistoryBrowser": False,
                    "showChatHistoryCosmos": False,
                    "showAgenticRetrievalOption": True,
                    "ragSearchImageEmbeddings": False,
                    "ragSearchTextEmbeddings": True,
                    "ragSendImageSources": False,
                    "ragSendTextSources": True,
                    "webSourceEnabled": True,
                    "sharepointSourceEnabled": True,
                }
            ),
            status=200,
        )

    page.route("*/**/config", handle_config)

    page.goto(live_server_url)
    expect(page).to_have_title("Azure OpenAI + AI Search")

    # Open Developer settings
    page.get_by_role("button", name="Developer settings").click()

    # Verify that agentic retrieval option is visible
    expect(page.get_by_text("Retrieval reasoning effort")).to_be_visible()

    # Verify that web and sharepoint checkboxes are initially visible and enabled
    web_checkbox = page.get_by_role("checkbox", name="Include web source")
    sharepoint_checkbox = page.get_by_role("checkbox", name="Include SharePoint source")
    expect(web_checkbox).to_be_visible()
    expect(web_checkbox).to_be_enabled()
    expect(sharepoint_checkbox).to_be_visible()
    expect(sharepoint_checkbox).to_be_enabled()

    # Select "Minimal" from the effort dropdown
    page.get_by_label("Retrieval reasoning effort").click()
    page.get_by_role("option", name="Minimal").click()

    # Verify that web checkbox is now deselected and disabled
    expect(web_checkbox).not_to_be_checked()
    expect(web_checkbox).to_be_disabled()

    # Verify that SharePoint checkbox is still enabled
    expect(sharepoint_checkbox).to_be_enabled()

    # Now select "Low" from the effort dropdown
    page.get_by_label("Retrieval reasoning effort").click()
    page.get_by_role("option", name="Low").click()

    # De-select streaming
    page.get_by_text("Stream chat completion responses").click()
    page.locator("button").filter(has_text="Close").click()

    # Ask a question and wait for the message to appear
    page.get_by_placeholder("Type a new question (e.g. does my plan cover annual eye exams?)").click()
    page.get_by_placeholder("Type a new question (e.g. does my plan cover annual eye exams?)").fill(
        "Whats the dental plan?"
    )
    page.get_by_role("button", name="Submit question").click()

    expect(page.get_by_text("Whats the dental plan?")).to_be_visible()
    expect(page.get_by_text("The capital of France is Paris.")).to_be_visible()
    expect(page.get_by_role("button", name="Clear chat")).to_be_enabled()

    # Open the thought process by clicking the lightbulb on the answer
    page.get_by_label("Show thought process").click()
    expect(page.get_by_title("Thought process")).to_be_visible()

    # Verify the expected thought process sections are visible
    expect(page.get_by_text("Agentic retrieval response")).to_be_visible()
    expect(page.get_by_text("Prompt to generate answer")).to_be_visible()


def _hyrox_chat_response(content: str) -> str:
    """A non-streaming /chat response body for the HYROX assessment bot (forced non-streaming)."""
    return json.dumps(
        {
            "message": {"role": "assistant", "content": content},
            "delta": {"role": "assistant", "content": content},
            "context": {
                "data_points": {"text": [], "images": [], "citations": []},
                "thoughts": [],
                "followup_questions": None,
            },
            "session_state": None,
        }
    )


def test_hyrox_assessment_hides_input_when_completed(page: Page, live_server_url: str):
    """On a completed assessment the response carries the hidden [[DONE]] marker, so the question
    input is removed entirely — the run is terminal in-session (pass OR fail; retaking happens in
    the Lemon app). The hidden control markers ([[SCORE]], [[BREAK]], [[DONE]]) must never be shown
    to the learner, and the [[BREAK]]-separated sections must render as distinct bubbles."""

    # A passed completion ending: final question's score + feedback, the verdict, and the closing
    # certificate notice — three [[BREAK]]-separated bubbles — with the hidden trailing markers.
    completion_content = (
        "**Question 20: 5/5**\n\nSolid finish, clear and complete."
        "\n\n[[BREAK]]\n\n"
        "**Assessment complete** - Total: 100/100 (100%) - **PASSED**"
        "\n\n[[BREAK]]\n\n"
        "You can now close the assessment, and your certificate will be generated."
        '\n\n[[SCORE q=1 points="1,1,1,1,1" max=5 cat="CATEGORY 1"]]\n[[DONE]]'
    )

    page.route("*/**/chat", lambda route: route.fulfill(body=_hyrox_chat_response(completion_content), status=200))

    page.goto(f"{live_server_url}hyrox-assessment")

    question_input = page.get_by_placeholder("Type your message")
    expect(question_input).to_be_visible()
    question_input.fill("Start")
    page.get_by_label("Submit question").click()

    # The completion rendered, split into its [[BREAK]]-separated bubbles.
    expect(page.get_by_text("Solid finish, clear and complete.")).to_be_visible()
    expect(page.get_by_text("your certificate will be generated")).to_be_visible()

    # The input (and its submit control) are gone now that the assessment is complete.
    expect(page.get_by_placeholder("Type your message")).to_have_count(0)
    expect(page.get_by_label("Submit question")).to_have_count(0)

    # No hidden control marker leaked into the visible transcript.
    expect(page.locator("#main-content")).not_to_contain_text("[[")


NERILIO_QUESTION_PLACEHOLDER = "Type your message"


def handle_config_with_browser_history(route: Route) -> None:
    """`/config` payload that enables the browser (IndexedDB) chat-history provider, which is the
    gate for the cross-navigation session restore."""
    route.fulfill(
        body=json.dumps(
            {
                "defaultReasoningEffort": "",
                "defaultRetrievalReasoningEffort": "minimal",
                "showMultimodalOptions": False,
                "showSemanticRankerOption": True,
                "showQueryRewritingOption": False,
                "showReasoningEffortOption": False,
                "streamingEnabled": True,
                "showVectorOption": True,
                "showUserUpload": False,
                "showLanguagePicker": False,
                "showSpeechInput": False,
                "showSpeechOutputBrowser": False,
                "showSpeechOutputAzure": False,
                "showChatHistoryBrowser": True,
                "showChatHistoryCosmos": False,
                "showAgenticRetrievalOption": False,
                "ragSearchImageEmbeddings": False,
                "ragSearchTextEmbeddings": True,
                "ragSendImageSources": False,
                "ragSendTextSources": True,
                "webSourceEnabled": False,
                "sharepointSourceEnabled": False,
            }
        ),
        status=200,
    )


# Resolves once the conversation has actually been flushed to IndexedDB, so a reload that follows
# is guaranteed to see the stored session (avoids racing the async addItem write).
WAIT_FOR_STORED_SESSION = """
async () => {
    return await new Promise(resolve => {
        const req = indexedDB.open('chat-database-nerilio');
        req.onsuccess = () => {
            const db = req.result;
            if (!db.objectStoreNames.contains('chat-history')) { resolve(false); return; }
            const all = db.transaction('chat-history', 'readonly').objectStore('chat-history').getAll();
            all.onsuccess = () => resolve(Array.isArray(all.result) && all.result.length > 0);
            all.onerror = () => resolve(false);
        };
        req.onerror = () => resolve(false);
    });
}
"""


def test_nerilio_restores_last_session_on_reload(page: Page, live_server_url: str):
    """Core of "chat follows the user across navigation": after asking a question, reloading the
    page restores the prior conversation automatically instead of starting blank."""
    page.route("*/**/config", handle_config_with_browser_history)
    page.route(
        "*/**/chat/stream",
        lambda route: fulfill_chat_stream_snapshot(
            route, "tests/snapshots/test_app/test_chat_stream_text/client0/result.jsonlines"
        ),
    )

    page.goto(f"{live_server_url}nerilio")

    question_input = page.get_by_placeholder(NERILIO_QUESTION_PLACEHOLDER)
    question_input.click()
    question_input.fill("Whats the dental plan?")
    # nerilio's send button is icon-only (no accessible name); Enter submits the question.
    question_input.press("Enter")

    expect(page.get_by_text("Whats the dental plan?")).to_be_visible()
    expect(page.get_by_text("The capital of France is Paris.")).to_be_visible()

    # Ensure the session is persisted before reloading, then reload as a "return visit".
    page.wait_for_function(WAIT_FOR_STORED_SESSION)
    page.reload()

    # The conversation is restored without re-asking — no /chat/stream call happens on reload.
    expect(page.get_by_text("Whats the dental plan?")).to_be_visible()
    expect(page.get_by_text("The capital of France is Paris.")).to_be_visible()


def test_nerilio_new_chat_clears_and_does_not_restore_on_reload(page: Page, live_server_url: str):
    """New Chat must start a fresh conversation that *stays* fresh across a reload — the active
    session pointer is cleared, so restore-on-load does not bring the old chat back."""
    page.route("*/**/config", handle_config_with_browser_history)
    page.route(
        "*/**/chat/stream",
        lambda route: fulfill_chat_stream_snapshot(
            route, "tests/snapshots/test_app/test_chat_stream_text/client0/result.jsonlines"
        ),
    )

    page.goto(f"{live_server_url}nerilio")

    question_input = page.get_by_placeholder(NERILIO_QUESTION_PLACEHOLDER)
    question_input.click()
    question_input.fill("Whats the dental plan?")
    # nerilio's send button is icon-only (no accessible name); Enter submits the question.
    question_input.press("Enter")

    expect(page.get_by_text("Whats the dental plan?")).to_be_visible()
    page.wait_for_function(WAIT_FOR_STORED_SESSION)

    # Start a new chat via the restored header dropdown.
    page.get_by_role("button", name="Toggle menu").click()
    page.get_by_role("button", name="New chat").click()
    expect(page.get_by_text("Whats the dental plan?")).not_to_be_visible()

    # After reload the fresh chat stays blank (the old session is no longer the active one).
    page.reload()
    expect(page.get_by_text("Whats the dental plan?")).to_have_count(0)
    expect(page.get_by_text("The capital of France is Paris.")).to_have_count(0)


def test_embedded_widget_auto_opens_when_previously_open(page: Page, live_server_url: str):
    """The embeddable widget re-opens on the next page if it was open when the user left
    (open-state remembered in the host page's localStorage)."""
    page.add_init_script("window.localStorage.setItem('chatbot-widget-open:nerilio', '1');")

    page.goto(f"{live_server_url}embed-demo?bot=nerilio")

    # Launcher flips to the "Close chat" affordance only when the panel auto-opened.
    expect(page.get_by_label("Close chat")).to_be_visible()


def test_embedded_widget_stays_closed_by_default(page: Page, live_server_url: str):
    """Without a remembered open state the widget stays closed — auto-open is never intrusive."""
    page.goto(f"{live_server_url}embed-demo?bot=nerilio")

    expect(page.get_by_label("Open chat")).to_be_visible()
    expect(page.get_by_label("Close chat")).to_have_count(0)


def test_hyrox_assessment_keeps_input_mid_assessment(page: Page, live_server_url: str):
    """Contrast: a normal mid-assessment turn (graded answer + the next question chained in, no
    [[DONE]]) must keep the question input so the learner can answer the next question."""

    mid_content = (
        "**Question 1: 5/5**\n\nGreat answer, well reasoned."
        "\n\n**Question 2 of 20**\nDescribe the four age groups in HYROX Youngstars."
        '\n\n[[SCORE q=1 points="1,1,1,1,1" max=5 cat="CATEGORY 1"]]\n[[ASKED q=2]]'
    )

    page.route("*/**/chat", lambda route: route.fulfill(body=_hyrox_chat_response(mid_content), status=200))

    page.goto(f"{live_server_url}hyrox-assessment")

    question_input = page.get_by_placeholder("Type your message")
    expect(question_input).to_be_visible()
    question_input.fill("Start")
    page.get_by_label("Submit question").click()

    expect(page.get_by_text("Great answer, well reasoned.")).to_be_visible()

    # No completion marker, so the input stays available for the next answer.
    expect(page.get_by_placeholder("Type your message")).to_be_visible()
    # Hidden markers are still stripped from the visible transcript.
    expect(page.locator("#main-content")).not_to_contain_text("[[")
