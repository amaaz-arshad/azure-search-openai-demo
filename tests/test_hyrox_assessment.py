import asyncio
from collections import Counter

from approaches.chatbot_config_registry import (
    get_chatbot_config,
    load_chatbot_config,
    render_chatbot_prompt,
)
from approaches.chatbot_prompt_registry import get_chatbot_prompt, get_registered_chatbot_names
from approaches.chatbots.hyrox_assessment import results
from approaches.chatbots.hyrox_assessment.questions import (
    CATEGORIES,
    QUESTIONS,
    TOTAL_MAX_POINTS,
    TOTAL_QUESTIONS,
    category_of,
    key_point_count,
    max_points,
)
from approaches.chatbots.hyrox_assessment.sampleprompt import (
    QUESTIONS_PER_RUN,
    SAMPLE_PROMPT,
    render_question_pool,
)

CHATBOT_NAME = "hyrox-assessment"


def _full_points(qid: int) -> str:
    return ",".join(["1"] * key_point_count(qid))


def _score_marker(qid: int, all_correct: bool = True) -> str:
    bit = "1" if all_correct else "0"
    pts = ",".join([bit] * key_point_count(qid))
    return f'[[SCORE q={qid} points="{pts}" max={max_points(qid)} cat="{category_of(qid)}"]]'


# --- Question pool --------------------------------------------------------


def test_question_pool_shape() -> None:
    assert TOTAL_QUESTIONS == 32
    assert len(QUESTIONS) == 32
    assert TOTAL_MAX_POINTS == 167
    assert len(CATEGORIES) == 8
    numbers = [q["number"] for q in QUESTIONS]
    assert numbers == list(range(1, 33))  # 1..32, no gaps/dupes
    for q in QUESTIONS:
        assert q["question"].strip()
        assert q["primary_answer"].strip()
        assert q["key_points"], f"Q{q['number']} has no key points"
        assert q["max_pts"] > 0
        assert q["category"] in CATEGORIES


def test_render_question_pool_includes_every_question() -> None:
    rendered = render_question_pool()
    for q in QUESTIONS:
        assert f"### Q{q['number']} —" in rendered
        assert f"MAX POINTS: {q['max_pts']}" in rendered


def test_question_accessors() -> None:
    assert key_point_count(1) == len(QUESTIONS[0]["key_points"])
    assert max_points(1) == QUESTIONS[0]["max_pts"]
    assert category_of(1) == QUESTIONS[0]["category"]
    # unknown ids are safe
    assert key_point_count(999) == 0 and max_points(999) == 0 and category_of(999) == ""


# --- Registry / config / prompt -------------------------------------------


def test_chatbot_is_registered() -> None:
    assert CHATBOT_NAME in get_registered_chatbot_names()


def test_config_loads_with_expected_values() -> None:
    load_chatbot_config.cache_clear()
    cfg = get_chatbot_config(CHATBOT_NAME)
    assert cfg is not None
    assert cfg.name == CHATBOT_NAME
    assert cfg.chatgpt_model == "gpt-5-mini"
    assert cfg.reasoning_effort == "medium"
    assert cfg.prompt_mode == "override"
    assert cfg.support_email == "info@lemon-systems.de"
    # language_locale must stay None so the per-request LMS language is honoured.
    assert cfg.language_locale is None


def test_prompt_loads_and_renders_placeholders() -> None:
    prompt = get_chatbot_prompt(CHATBOT_NAME)
    assert prompt is not None
    # The model emits only the per-key-point SCORE marker; the backend owns PLAN/RESULT.
    assert '[[SCORE q=' in prompt
    assert 'points="' in prompt
    assert "CURRENT TURN STATE" in prompt  # references the backend-injected control block
    assert "### Q1 —" in prompt and "### Q32 —" in prompt
    assert str(QUESTIONS_PER_RUN) in SAMPLE_PROMPT

    rendered = render_chatbot_prompt(prompt, CHATBOT_NAME, None, "en")
    assert "{{SUPPORT_EMAIL}}" not in rendered
    assert "info@lemon-systems.de" in rendered
    assert "{{language_locale}}" not in rendered
    assert "English" in rendered


# --- Question selection (deterministic, balanced, no repeats) -------------


def test_select_question_plan_is_20_distinct_in_range() -> None:
    plan = results.select_question_plan(seed=42)
    assert len(plan) == QUESTIONS_PER_RUN == 20
    assert len(set(plan)) == 20  # all distinct
    assert all(1 <= x <= 32 for x in plan)


def test_select_question_plan_is_category_balanced() -> None:
    plan = results.select_question_plan(seed=42)
    counts = Counter(category_of(i) for i in plan)
    assert len(counts) == 8  # every category represented
    assert all(2 <= c <= 3 for c in counts.values())  # 20 over 8 cats → 2 or 3 each
    assert sum(counts.values()) == 20


def test_select_question_plan_is_deterministic_under_seed() -> None:
    assert results.select_question_plan(seed=7) == results.select_question_plan(seed=7)


# --- Per-point scoring (backend authoritative) ----------------------------


def test_parse_points() -> None:
    assert results.parse_points("1,1,0,1") == [1, 1, 0, 1]
    assert results.parse_points("1, 0 ,1") == [1, 0, 1]
    assert results.parse_points("") == []
    assert results.parse_points(None) == []


def test_normalize_score_computes_awarded_and_validates_length() -> None:
    # Q1 has 5 key points, max 5.
    s = results.normalize_score(1, [1, 1, 1, 0, 0])
    assert s["awarded"] == 3 and s["max"] == 5 and len(s["points"]) == 5
    assert s["cat"].startswith("CATEGORY 1")
    # too many values are truncated to the key-point count, then capped at max
    assert results.normalize_score(1, [1, 1, 1, 1, 1, 1, 1])["awarded"] == 5
    # too few values are padded with 0
    short = results.normalize_score(1, [1, 1])
    assert short["points"] == [1, 1, 0, 0, 0] and short["awarded"] == 2


def test_parse_new_score_forces_pinned_question_id() -> None:
    # model mislabels q=99, but the backend forces the pinned current_id
    entry = results.parse_new_score('ok [[SCORE q=99 points="1,1,1,1,1" max=5 cat="x"]]', current_id=1)
    assert entry is not None
    assert entry["q"] == 1 and entry["awarded"] == 5 and entry["max"] == 5
    assert results.parse_new_score("no marker", current_id=1) is None


def test_compute_tally_pass_threshold_is_80_percent_inclusive() -> None:
    at_threshold = results.compute_tally([{"awarded": 8, "max": 10}])
    assert at_threshold["pct"] == 80 and at_threshold["passed"] is True
    below = results.compute_tally([{"awarded": 79, "max": 100}])
    assert below["pct"] == 79 and below["passed"] is False
    empty = results.compute_tally([])
    assert empty["max"] == 0 and empty["passed"] is False


def test_category_breakdown() -> None:
    scores = [
        {"awarded": 5, "max": 5, "cat": "A"},
        {"awarded": 2, "max": 6, "cat": "A"},
        {"awarded": 4, "max": 5, "cat": "B"},
    ]
    breakdown = results.category_breakdown(scores)
    assert breakdown["A"] == {"awarded": 7, "max": 11}
    assert breakdown["B"] == {"awarded": 4, "max": 5}


# --- State machine: counter, selection, no-repeat, completion -------------


def test_derive_turn_state_fresh_run() -> None:
    st = results.derive_turn_state([{"role": "user", "content": "start"}])
    assert st["plan_is_new"] is True
    assert st["n_scored"] == 0
    assert st["current_id"] == st["plan"][0]
    assert len(st["plan"]) == 20


def test_derive_turn_state_counts_scores_after_plan() -> None:
    plan = results.select_question_plan(seed=7)
    hist = [
        {"role": "user", "content": "start"},
        {"role": "assistant", "content": "Intro " + results.format_plan_marker(plan)},
        {"role": "user", "content": "ans"},
        {"role": "assistant", "content": "ok " + _score_marker(plan[0])},
        {"role": "user", "content": "ans"},
        {"role": "assistant", "content": "ok " + _score_marker(plan[1])},
    ]
    st = results.derive_turn_state(hist)
    assert st["plan_is_new"] is False
    assert st["n_scored"] == 2
    assert st["current_id"] == plan[2]


def test_full_run_asks_exactly_20_unique_questions_then_completes() -> None:
    plan = results.select_question_plan(seed=11)
    hist = [
        {"role": "user", "content": "start"},
        {"role": "assistant", "content": results.format_plan_marker(plan)},
    ]
    asked: list[int] = []
    for _ in range(20):
        st = results.derive_turn_state(hist)
        cid = st["current_id"]
        assert cid is not None
        asked.append(cid)
        hist.append({"role": "assistant", "content": _score_marker(cid)})
    assert asked == plan  # asked in plan order, exactly the 20 planned ids
    assert len(set(asked)) == 20  # no repeats
    final = results.derive_turn_state(hist)
    assert final["current_id"] is None
    assert final["completed_passed"] is True


def test_failed_completed_run_auto_restarts() -> None:
    plan = results.select_question_plan(seed=13)
    hist = [
        {"role": "user", "content": "start"},
        {"role": "assistant", "content": results.format_plan_marker(plan)},
    ]
    for cid in plan:
        hist.append({"role": "assistant", "content": _score_marker(cid, all_correct=False)})
    st = results.derive_turn_state(hist)
    assert st["plan_is_new"] is True  # fail → next turn begins a brand-new run
    assert st["n_scored"] == 0
    assert st["current_id"] is not None


# --- Rendering the authoritative numbers ----------------------------------


def test_render_progress_header_localized() -> None:
    assert results.render_progress_header(0, "en") == "**Question 1 of 20**"
    assert results.render_progress_header(0, "de") == "**Frage 1 von 20**"
    assert results.render_progress_header(0, "nl") == "**Vraag 1 van 20**"
    assert results.render_progress_header(5, "en") == "**Question 6 of 20**"


def test_render_question_score_localized() -> None:
    assert results.render_question_score(1, 4, 6, "en") == "**Question 1: 4/6**"
    assert results.render_question_score(2, 3, 5, "de") == "**Frage 2: 3/5**"
    assert results.render_question_score(3, 5, 5, "nl") == "**Vraag 3: 5/5**"


def test_render_final_result_localized() -> None:
    passed = results.render_final_result({"score": 90, "max": 100, "pct": 90, "passed": True}, "en")
    assert "PASSED" in passed and "NOT PASSED" not in passed and "90/100" in passed
    failed = results.render_final_result({"score": 50, "max": 100, "pct": 50, "passed": False}, "de")
    assert "NICHT BESTANDEN" in failed


def test_strip_rendered_numbers_removes_model_written_numbers() -> None:
    text = "**Question 3 of 20**\nWhat is X?\nScore so far: 5/10 (50%)\nkeep me"
    out = results.strip_rendered_numbers(text)
    assert "Question 3 of 20" not in out
    assert "Score so far" not in out
    assert "What is X?" in out and "keep me" in out
    complete = "**Assessment complete** — Total: 9/10 (90%) — **PASSED**\nWell done"
    out2 = results.strip_rendered_numbers(complete)
    assert "Assessment complete" not in out2 and "Well done" in out2


def test_render_assessment_turn_asks_question_via_ask_token() -> None:
    plan = results.select_question_plan(seed=3)
    prior = results.normalize_score(2, [1, 1, 1])  # one question already finalised
    state = {
        "plan": plan,
        "plan_is_new": False,
        "scores": [prior],
        "n_scored": 1,
        "current_id": plan[1],
        "tally": results.compute_tally([prior]),
        "completed_passed": False,
    }
    content = "Let's continue.\n[[ASK]]\nWhat is X?"  # asking the next question (no new score)
    assembled, all_scores, _tally, just_completed = results.render_assessment_turn(content, state, "en")
    assert "**Question 2 of 20**" in assembled  # 1 finalised → asking question 2
    assert "[[ASK]]" not in assembled  # token replaced
    assert "What is X?" in assembled
    assert "Score so far" not in assembled  # no running cumulative total mid-assessment
    assert len(all_scores) == 1 and just_completed is False


def test_render_assessment_turn_finalization_shows_question_score_no_header() -> None:
    state = {
        "plan": results.select_question_plan(seed=3),
        "plan_is_new": False,
        "scores": [],
        "n_scored": 0,
        "current_id": 1,
        "tally": results.compute_tally([]),
        "completed_passed": False,
    }
    content = 'Good work — solid start.\n[[SCORE q=1 points="1,1,1,1,0" max=5 cat="x"]]'
    assembled, all_scores, _tally, just_completed = results.render_assessment_turn(content, state, "en")
    assert "**Question 1: 4/5**" in assembled  # this question's score, shown once graded
    assert "of 20" not in assembled  # NO progress header on a finalisation message
    assert "[[SCORE" in assembled  # hidden marker retained for replay
    assert len(all_scores) == 1 and just_completed is False


def test_render_assessment_turn_appends_plan_on_fresh_run() -> None:
    plan = results.select_question_plan(seed=5)
    state = {
        "plan": plan,
        "plan_is_new": True,
        "scores": [],
        "n_scored": 0,
        "current_id": plan[0],
        "tally": results.compute_tally([]),
        "completed_passed": False,
    }
    content = "Welcome!\n[[ASK]]\nHere is your first question?"
    assembled, all_scores, _tally, just_completed = results.render_assessment_turn(content, state, "en")
    assert results.format_plan_marker(plan) in assembled  # backend persists the plan
    assert "**Question 1 of 20**" in assembled  # [[ASK]] → header, position 1
    assert "[[ASK]]" not in assembled
    assert all_scores == [] and just_completed is False


def test_render_assessment_turn_completion_emits_final_result() -> None:
    prior_ids = list(range(2, 21))  # 19 questions already finalised (full marks)
    scores = [results.normalize_score(i, [1] * key_point_count(i)) for i in prior_ids]
    state = {
        "plan": [1] + prior_ids,
        "plan_is_new": False,
        "scores": scores,
        "n_scored": 19,
        "current_id": 1,
        "tally": results.compute_tally(scores),
        "completed_passed": False,
    }
    content = f'Final one done.\n{_score_marker(1)}'
    assembled, all_scores, tally, just_completed = results.render_assessment_turn(content, state, "en")
    assert just_completed is True
    assert len(all_scores) == 20
    assert results.render_final_result(tally, "en") in assembled  # cumulative result only at the end
    # the 20th question's own score is shown too (full marks on Q1's rubric)
    assert results.render_question_score(20, max_points(1), max_points(1), "en") in assembled


# --- record_assessment_result --------------------------------------------


def test_record_assessment_result_builds_payload_from_backend_tally() -> None:
    scores = [results.normalize_score(1, [1, 1, 1, 1, 1]), results.normalize_score(2, [1] * key_point_count(2))]
    tally = results.compute_tally(scores)
    payload = asyncio.run(
        results.record_assessment_result(
            scores=scores,
            tally=tally,
            messages=[{"role": "user", "content": "start"}],
            final_content="done",
            overrides={"language": "en", "user": "lms-user-1"},
            auth_claims={"oid": "oid-1"},
            session_state="sess-123",
            blob_manager=None,
        )
    )
    assert payload is not None
    assert payload["score"] == tally["score"]
    assert payload["max"] == tally["max"]
    assert payload["percent"] == tally["pct"]
    assert payload["passed"] is True
    assert payload["session_id"] == "sess-123"
    assert payload["user_id"] == "oid-1"
    assert payload["language"] == "en"
    assert payload["category_breakdown"]  # non-empty per-category breakdown
