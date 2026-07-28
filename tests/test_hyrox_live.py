"""Live (opt-in) smoke test for the HYROX assessment bot against the REAL Azure OpenAI model.

Unlike ``test_hyrox_assessment.py`` (pure, deterministic unit tests of the engine), this drives a
few real turns through the production pipeline —
``derive_turn_state → build_state_injection → the REAL gpt-5.4-mini → render_assessment_turn`` —
with Search/Blob unused (the assessment bot skips retrieval). It exists to answer the one thing the
mocks cannot: does the real model actually obey the prompt/marker contract?

It is NON-deterministic, needs Azure credentials + network, and is therefore OFF by default. Run it:

    # load the azd env so AZURE_OPENAI_SERVICE etc. are present, then sign in, then opt in:
    az login            # or: azd auth login
    RUN_HYROX_LIVE=1 pytest tests/test_hyrox_live.py -s     # -s to see the transcript

Assertions are INVARIANTS that must hold whatever the model says (well-formed markers, no rubric
leak, one question per turn, the run progresses and grades) — never exact text, which would flake.
This is a canary, not a per-commit gate; keep it out of the fast CI suite.
"""

import os
import re

import pytest

from approaches.chatbots.hyrox_assessment import results
from approaches.chatbots.hyrox_assessment.questions import key_point_count, max_points

RUN_LIVE = os.getenv("RUN_HYROX_LIVE") == "1"
AZURE_OPENAI_SERVICE = os.getenv("AZURE_OPENAI_SERVICE")

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (RUN_LIVE and AZURE_OPENAI_SERVICE),
        reason="live model test — set RUN_HYROX_LIVE=1, load the azd env (AZURE_OPENAI_SERVICE), and 'az login'",
    ),
]

OVERRIDES = {"include_category": "hyrox-assessment", "language": "en", "reasoning_effort": "high"}
QUESTION_HEADER_RE = re.compile(r"Question\s+(\d+)\s+of\s+\d+", re.IGNORECASE)
# Things the learner must NEVER see: rubric sections, any control marker, or raw point syntax.
FORBIDDEN_LEAKS = ("MODEL ANSWER", "REQUIRED KEY POINT", "ACCEPTED ALTERNATIVE", "[[", "points=")


def build_real_approach():
    """Construct the real chat approach with a live Azure OpenAI client (Search/Blob unused)."""
    from azure.core.credentials import AzureKeyCredential
    from azure.identity.aio import AzureDeveloperCliCredential
    from azure.search.documents.aio import SearchClient

    from approaches.chatreadretrieveread import ChatReadRetrieveReadApproach
    from approaches.promptmanager import PromptManager
    from prepdocslib.servicesetup import OpenAIHost, setup_openai_client

    credential = AzureDeveloperCliCredential(process_timeout=60)
    openai_client, _endpoint = setup_openai_client(
        openai_host=OpenAIHost.AZURE,
        azure_credential=credential,
        azure_openai_service=AZURE_OPENAI_SERVICE,
    )
    model = os.getenv("AZURE_OPENAI_CHATGPT_MODEL", "gpt-5.4-mini")
    deployment = os.getenv("AZURE_OPENAI_CHATGPT_DEPLOYMENT", "gpt-5.4-mini")
    approach = ChatReadRetrieveReadApproach(
        # The bot skips retrieval, so the search client is never called — a dummy is fine.
        search_client=SearchClient(
            endpoint="https://unused.search.windows.net", index_name="unused", credential=AzureKeyCredential("unused")
        ),
        search_index_name=None,
        knowledgebase_model=None,
        knowledgebase_deployment=None,
        knowledgebase_client=None,
        openai_client=openai_client,
        chatgpt_model=model,
        chatgpt_deployment=deployment,
        embedding_deployment="text-embedding-3-large",
        embedding_model="text-embedding-3-large",
        embedding_dimensions=3072,
        embedding_field="embedding3",
        sourcepage_field="",
        content_field="",
        query_language="en-us",
        query_speller="lexicon",
        prompt_manager=PromptManager(),
        reasoning_effort="high",
    )
    return approach, openai_client, credential


def validate_score_markers(content: str) -> int:
    """Every ``[[SCORE]]`` the model emits must be well-formed against questions.py. Returns count."""
    count = 0
    for m in results.SCORE_MARKER_RE.finditer(content):
        attrs = results._parse_attrs(m.group(1))
        qid = int(attrs["q"])
        points = results.parse_points(attrs.get("points"))
        assert len(points) == key_point_count(qid), f"SCORE q={qid}: {len(points)} points != {key_point_count(qid)}"
        assert int(attrs["max"]) == max_points(qid), f"SCORE q={qid}: max {attrs['max']} != {max_points(qid)}"
        count += 1
    return count


# The line shapes the backend renders itself. Each may appear at most ONCE in a message: a second copy
# means a model imitation survived the strip/dedupe guards — the reported "**Question 2: 4/4**" shown twice.
RENDERED_LINE_SHAPES = (
    results._QUESTION_SCORE_LINE_RE,
    results._HEADER_LINE_RE,
    results._MODULE_HEADING_LINE_RE,
    results._MODULE_RESULT_LINE_RE,
    results._COMPLETE_LINE_RE,
)


def assert_no_duplicated_rendered_lines(visible: str) -> None:
    keys = [
        results._rendered_line_key(line)
        for line in visible.splitlines()
        if any(shape.match(line) for shape in RENDERED_LINE_SHAPES)
    ]
    duplicated = sorted({key for key in keys if keys.count(key) > 1})
    assert not duplicated, f"a backend-rendered line appears more than once: {duplicated}\n---\n{visible}"


def assert_turn_invariants(content: str) -> None:
    visible = results.strip_markers(content)
    assert visible.strip(), "empty learner-visible message"
    for bad in FORBIDDEN_LEAKS:
        assert bad not in visible, f"leak in learner-visible text: {bad!r}\n---\n{visible}"
    headers = QUESTION_HEADER_RE.findall(visible)
    assert len(headers) <= 1, f"more than one question shown in a single turn: {headers}"
    assert_no_duplicated_rendered_lines(visible)
    validate_score_markers(content)


@pytest.mark.asyncio
async def test_hyrox_live_smoke():
    approach, openai_client, credential = build_real_approach()
    history: list[dict] = []
    max_question_seen = 0
    score_markers_total = 0

    async def turn(user_message: str) -> str:
        nonlocal max_question_seen, score_markers_total
        history.append({"role": "user", "content": user_message})
        result = await approach.run_without_streaming(history, OVERRIDES, {}, session_state=None)
        content = result["message"]["content"]
        history.append({"role": "assistant", "content": content})
        assert_turn_invariants(content)
        score_markers_total += len(list(results.SCORE_MARKER_RE.finditer(content)))
        visible = results.strip_markers(content)
        for n in QUESTION_HEADER_RE.findall(visible):
            max_question_seen = max(max_question_seen, int(n))
        print(f"\n=== USER: {user_message!r}\n{visible}\n")
        return content

    try:
        from azure.core.exceptions import ClientAuthenticationError

        try:
            # 1) Start → backend authors the plan and asks Q1.
            first = await turn("Hi, I'd like to begin the assessment.")
        except ClientAuthenticationError as exc:
            pytest.skip(f"not signed in to Azure (run 'az login' / 'azd auth login'): {exc}")

        assert QUESTION_HEADER_RE.search(results.strip_markers(first)), "no question rendered on the first turn"
        assert "[[PLAN" in first, "backend did not author a [[PLAN]] marker on the fresh run"

        # 2) A clearly partial answer (should not earn full marks).
        await turn("It's about adapting during the session.")
        # 3) A substantive answer that contains the word 'next' — must NOT be misread as a skip (Option A).
        await turn(
            "Reflection in action happens live during coaching; reflection on action happens afterwards, "
            "when the coach reviews the session before the next one."
        )
        # 4) A clean give-up — the run must move forward, never loop on the same question.
        await turn("skip")
    finally:
        await openai_client.close()
        await credential.close()

    # Cross-turn invariants that hold regardless of the model's per-answer judgement:
    assert max_question_seen >= 2, f"assessment never progressed past Q{max_question_seen}"
    assert score_markers_total >= 1, "the model never produced a single [[SCORE]] across the whole run"
