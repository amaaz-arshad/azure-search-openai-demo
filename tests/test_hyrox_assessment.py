import asyncio

from approaches.chatbot_config_registry import (
    get_chatbot_config,
    load_chatbot_config,
    render_chatbot_prompt,
)
from approaches.chatbot_prompt_registry import get_chatbot_prompt, get_registered_chatbot_names
from approaches.chatbots.hyrox_assessment import results
from approaches.chatbots.hyrox_assessment.questions import (
    MODULES,
    QUESTIONS,
    TOTAL_MAX_POINTS,
    TOTAL_QUESTIONS,
    get_question,
    is_last_module,
    key_point_count,
    max_points,
    module_label,
    module_of,
    module_questions,
    next_module,
)
from approaches.chatbots.hyrox_assessment.sampleprompt import SAMPLE_PROMPT, render_question_pool

CHATBOT_NAME = "hyrox-assessment"


# --- helpers --------------------------------------------------------------


def _score_marker(qid: int, all_correct: bool = True) -> str:
    bit = "1" if all_correct else "0"
    pts = ",".join([bit] * key_point_count(qid))
    return f'[[SCORE q={qid} points="{pts}" max={max_points(qid)} mod="{module_of(qid)}"]]'


def _partial_score_marker(qid: int) -> str:
    """A below-full-marks score: first key point earned, the rest missing."""
    pts = ["1"] + ["0"] * (key_point_count(qid) - 1)
    return f'[[SCORE q={qid} points="{",".join(pts)}" max={max_points(qid)} mod="{module_of(qid)}"]]'


def _question_text(qid: int) -> str:
    question = get_question(qid)
    assert question is not None
    return str(question["question"])


def _fake_model(state: dict, full_marks: bool = True) -> str:
    """Mimic the LLM given the backend's pinned CURRENT TURN STATE."""
    cid = state.get("current_id")
    if state.get("assessment_complete") or cid is None:
        return "Understood."
    if not state.get("current_question_asked"):
        return "[[ASK]]"
    if state.get("latest_user_answer_pending"):
        kpc = key_point_count(cid)
        pts = ",".join(["1"] * kpc) if full_marks else ",".join(["1"] + ["0"] * (kpc - 1))
        # The model authors no ending — even the final question is just feedback + score. The backend
        # renders the module-by-module summary, motivational, and closing/certificate messages itself.
        return f'Thanks.\n\n[[SCORE q={cid} points="{pts}" max={max_points(cid)} mod="{module_of(cid)}"]]'
    return "continue"


def _turn(messages: list, user: str, full_marks: bool = True):
    """One request/response cycle against the real engine. Returns (messages, content, state, done)."""
    messages = messages + [{"role": "user", "content": user}]
    state = results.derive_turn_state(messages)
    content, _scores, _tally, done = results.render_assessment_turn(_fake_model(state, full_marks), state, "en")
    return messages + [{"role": "assistant", "content": content}], content, state, done


def _answer_module(messages: list, full_marks: bool = True):
    """Answer questions (with revision turns when partial) until the module hits a boundary or the
    whole assessment completes. Returns (messages, last_content, done)."""
    for _ in range(80):
        messages, content, _state, done = _turn(messages, "my answer", full_marks)
        if done or "[[MODPASS" in content or "[[MODFAIL" in content:
            return messages, content, done
    raise AssertionError("module never terminated")


# --- Question pool --------------------------------------------------------


def test_question_pool_shape() -> None:
    assert TOTAL_QUESTIONS == 52
    assert len(QUESTIONS) == 52
    assert TOTAL_MAX_POINTS == 211
    assert MODULES == ["M1", "M2", "M3", "M4", "M5", "M6", "M7.1", "M7.2", "M7.3", "M7.4", "M8", "M9", "M10"]
    numbers = [q["number"] for q in QUESTIONS]
    assert numbers == list(range(1, 53))  # 1..52, no gaps/dupes
    for q in QUESTIONS:
        assert q["question"].strip()
        assert q["primary_answer"].strip()
        assert q["key_points"], f"Q{q['number']} has no key points"
        # one point per key point, no weighting — the scorer relies on this
        assert len(q["key_points"]) == q["max_pts"]
        assert q["module"] in MODULES
        assert q["qid"].startswith(q["module"] + "-")


def test_modules_partition_all_questions_in_order() -> None:
    flattened = [n for m in MODULES for n in module_questions(m)]
    assert flattened == list(range(1, 53))  # modules cover every question, in fixed order
    # module point sums match the per-module question maxima
    for m in MODULES:
        assert sum(max_points(n) for n in module_questions(m)) > 0
    assert next_module("M10") is None and is_last_module("M10")
    assert next_module("M6") == "M7.1"


def test_render_question_pool_includes_every_question_and_module_headings() -> None:
    rendered = render_question_pool()
    for q in QUESTIONS:
        assert f"### Q{q['number']} ({q['qid']})" in rendered
        assert f"MAX POINTS: {q['max_pts']}" in rendered
    for m in MODULES:
        assert f"## MODULE {m}" in rendered
    assert "ACCEPTED ALTERNATIVE ANSWER" in rendered


def test_question_accessors() -> None:
    assert key_point_count(1) == len(QUESTIONS[0]["key_points"])
    assert max_points(1) == QUESTIONS[0]["max_pts"]
    assert module_of(1) == QUESTIONS[0]["module"]
    assert module_label("M7.1") == "Module 7.1"
    # unknown ids are safe
    assert key_point_count(999) == 0 and max_points(999) == 0 and module_of(999) == ""


# --- Registry / config / prompt -------------------------------------------


def test_chatbot_is_registered() -> None:
    assert CHATBOT_NAME in get_registered_chatbot_names()


def test_config_loads_with_expected_values() -> None:
    load_chatbot_config.cache_clear()
    cfg = get_chatbot_config(CHATBOT_NAME)
    assert cfg is not None
    assert cfg.name == CHATBOT_NAME
    assert cfg.chatgpt_model == "gpt-5.4-mini"
    assert cfg.reasoning_effort == "high"
    assert cfg.prompt_mode == "override"
    assert cfg.support_email == "info@lemon-systems.de"
    assert cfg.language_locale is None


def test_prompt_loads_and_renders_placeholders() -> None:
    prompt = get_chatbot_prompt(CHATBOT_NAME)
    assert prompt is not None
    assert "[[SCORE q=" in prompt
    assert 'points="' in prompt
    assert "NO visible question text" in prompt
    assert "CURRENT TURN STATE" in prompt
    assert "module by module" in prompt.lower()
    assert "Level 2" in prompt
    assert "### Q1 (M1-Q01)" in prompt and "### Q52 (M10-Q05)" in prompt
    assert str(len(MODULES)) in SAMPLE_PROMPT

    rendered = render_chatbot_prompt(prompt, CHATBOT_NAME, None, "en")
    assert "{{SUPPORT_EMAIL}}" not in rendered
    assert "info@lemon-systems.de" in rendered
    assert "{{language_locale}}" not in rendered
    assert "English" in rendered


# --- Per-point scoring (backend authoritative) ----------------------------


def test_parse_points() -> None:
    assert results.parse_points("1,1,0,1") == [1, 1, 0, 1]
    assert results.parse_points("1, 0 ,1") == [1, 0, 1]
    assert results.parse_points("") == []
    assert results.parse_points(None) == []


def test_normalize_score_computes_awarded_and_validates_length() -> None:
    kpc = key_point_count(1)
    s = results.normalize_score(1, [1] * kpc)
    assert s["awarded"] == max_points(1) and s["max"] == max_points(1) and len(s["points"]) == kpc
    assert s["mod"] == "M1"
    # too many values truncated to the key-point count, capped at max
    assert results.normalize_score(1, [1] * (kpc + 3))["awarded"] == max_points(1)
    # too few padded with 0
    short = results.normalize_score(1, [1, 1])
    assert short["points"][:2] == [1, 1] and short["awarded"] == 2 and len(short["points"]) == kpc


def test_parse_new_score_forces_pinned_question_id() -> None:
    entry = results.parse_new_score('ok [[SCORE q=99 points="1,1,1" max=3 mod="x"]]', current_id=1)
    assert entry is not None
    assert entry["q"] == 1 and entry["max"] == max_points(1)
    assert results.parse_new_score("no marker", current_id=1) is None


def test_compute_tally_pass_threshold_is_80_percent_inclusive() -> None:
    at_threshold = results.compute_tally([{"awarded": 8, "max": 10}])
    assert at_threshold["pct"] == 80 and at_threshold["passed"] is True
    below = results.compute_tally([{"awarded": 79, "max": 100}])
    assert below["pct"] == 79 and below["passed"] is False
    empty = results.compute_tally([])
    assert empty["max"] == 0 and empty["passed"] is False


def test_module_breakdown() -> None:
    scores = [
        {"awarded": 5, "max": 5, "mod": "M1"},
        {"awarded": 2, "max": 6, "mod": "M1"},
        {"awarded": 4, "max": 5, "mod": "M2"},
    ]
    breakdown = results.module_breakdown(scores)
    assert breakdown["M1"] == {"awarded": 7, "max": 11}
    assert breakdown["M2"] == {"awarded": 4, "max": 5}


# --- State machine: start, module gating, advance, retry, completion ------


def test_fresh_run_starts_first_module() -> None:
    st = results.derive_turn_state([{"role": "user", "content": "Start"}])
    assert st["plan_is_new"] is True and st["module_is_new"] is True
    assert st["current_module"] == "M1"
    assert st["attempt"] == 1
    assert st["current_id"] == module_questions("M1")[0]


def test_start_turn_renders_module_heading_plan_and_module_markers() -> None:
    messages, content, _state, done = _turn([], "Start")
    assert done is False
    assert results.format_plan_marker() in content
    assert "[[MODULE m=M1 attempt=1]]" in content
    assert results.format_asked_marker(module_questions("M1")[0]) in content
    disp = results.strip_markers(content)
    assert f"**{module_label('M1')}**" in disp
    assert "**Question 1 of 4**" in disp
    assert _question_text(module_questions("M1")[0]) in disp


def test_passing_a_module_emits_modpass_and_continue_prompt_not_done() -> None:
    messages, _content, _state, _done = _turn([], "Start")
    messages, content, done = _answer_module(messages, full_marks=True)
    assert done is False
    assert "[[MODPASS m=M1]]" in content
    assert "[[DONE]]" not in content and "[[PROGRESS" not in content
    disp = results.strip_markers(content)
    assert "Passed" in disp
    assert "continue to the next module" in disp.lower()


def test_continue_advances_to_next_module() -> None:
    messages, _content, _state, _done = _turn([], "Start")
    messages, _content, _done = _answer_module(messages, full_marks=True)
    messages, content, state, done = _turn(messages, "Continue")
    assert done is False
    assert state["current_module"] == "M2" and state["module_is_new"] is True
    assert "[[MODULE m=M2 attempt=1]]" in content
    disp = results.strip_markers(content)
    assert f"**{module_label('M2')}**" in disp
    assert "**Question 1 of 4**" in disp


def test_failing_a_module_emits_modfail_and_retry_prompt() -> None:
    messages, _content, _state, _done = _turn([], "Start")
    messages, content, done = _answer_module(messages, full_marks=False)
    assert done is False
    assert "[[MODFAIL m=M1]]" in content
    assert "[[MODPASS" not in content and "[[DONE]]" not in content
    disp = results.strip_markers(content)
    assert "80%" in disp
    assert "again" in disp.lower()


def test_retry_restarts_same_module_fresh_excluding_failed_scores() -> None:
    messages, _content, _state, _done = _turn([], "Start")
    messages, _content, _done = _answer_module(messages, full_marks=False)
    messages, content, state, done = _turn(messages, "Retry")
    assert state["current_module"] == "M1" and state["attempt"] == 2
    assert state["scores"] == []  # the failed attempt's scores do not carry into the retry
    assert "[[MODULE m=M1 attempt=2]]" in content
    assert "**Question 1 of 4**" in results.strip_markers(content)


def test_full_assessment_completes_only_after_final_module() -> None:
    messages, _content, _state, _done = _turn([], "Start")
    completed = False
    for mi, module_key in enumerate(MODULES):
        messages, content, done = _answer_module(messages, full_marks=True)
        if done:
            completed = True
            assert module_key == MODULES[-1] == "M10"
            assert "[[DONE]]" in content and "[[PROGRESS value=100]]" in content
            disp = results.strip_markers(content)
            assert "passed every module" in disp.lower()
            assert "certificate" in disp.lower()
            break
        # intermediate module → continue
        assert "[[MODPASS" in content and "[[DONE]]" not in content
        messages, _content, _state, _done = _turn(messages, "Continue")
    assert completed


def test_completion_renders_five_break_separated_bubbles() -> None:
    messages, _content, _state, _done = _turn([], "Start")
    final_content = ""
    for module_key in MODULES:
        messages, content, done = _answer_module(messages, full_marks=True)
        final_content = content
        if done:
            break
        messages, _content, _state, _done = _turn(messages, "Continue")
    bubbles = [b.strip() for b in final_content.split(results.BUBBLE_BREAK_TOKEN)]
    assert len(bubbles) == 5
    assert "passed every module" in bubbles[1].lower()
    # Bubble 3 is the deterministic module-by-module summary — every module listed, in order.
    summary_display = results.strip_markers(bubbles[2])
    assert "Summary by module" in summary_display
    assert "Strengths:" in summary_display  # full marks → every module lists earned topics
    for module_key in MODULES:
        assert results._module_display(module_key, "en") in summary_display
    assert "Managing performance" in bubbles[3]
    assert "certificate" in bubbles[4].lower()
    assert "[[" not in results.strip_markers(final_content)  # frontend display parity


def test_render_module_summary_lists_earned_and_missed_topics() -> None:
    # Verdict-driven topic breakdown: earned key points become Strengths, missed ones Worth revisiting.
    q1 = get_question(module_questions("M1")[0])
    assert q1 is not None
    kps = q1["key_points"]
    assert len(kps) >= 3
    score = results.normalize_score(q1["number"], [1, 1, 0])  # earn first two, miss the third
    display = results.strip_markers(results.render_module_summary([("M1", [score])], "en"))
    assert "Summary by module" in display
    assert results._module_display("M1", "en") in display
    assert "worth revisiting" in display.lower()  # band: 2/3 < 90%
    assert f"Strengths: {kps[0]}; {kps[1]}" in display
    assert f"Worth revisiting: {kps[2]}" in display


def test_done_marker_absent_mid_module() -> None:
    messages, content, _state, done = _turn([], "Start")
    # answer the first question of M1 (4 questions) → chains Q2, no completion
    messages, content, _state, done = _turn(messages, "my answer", full_marks=True)
    assert done is False
    assert "[[DONE" not in content and "[[MODPASS" not in content
    assert "**Question 2 of 4**" in results.strip_markers(content)


# --- one-correction guard (per-question, within a module) -----------------


def _grade_first_messages():
    """History where M1-Q1 has been asked and the learner's first (partial) answer is pending."""
    messages, _content, _state, _done = _turn([], "Start")
    return messages + [{"role": "user", "content": "a partial first answer"}]


def test_premature_partial_first_score_is_discarded_with_correction_offer() -> None:
    messages = _grade_first_messages()
    state = results.derive_turn_state(messages)
    cid = state["current_id"]
    assert state["latest_user_answer_pending"] and not state["must_finalize_current"]
    content, all_scores, _tally, done = results.render_assessment_turn(
        f"Good start — one part missing.\n{_partial_score_marker(cid)}", state, "en"
    )
    assert all_scores == [] and done is False
    assert "[[SCORE" not in content  # discarded
    assert "add to or revise your answer" in content
    assert "**Question 2 of 4**" not in results.strip_markers(content)  # position held


def test_full_marks_first_answer_is_accepted_and_chains_next() -> None:
    messages = _grade_first_messages()
    state = results.derive_turn_state(messages)
    cid = state["current_id"]
    content, all_scores, _tally, done = results.render_assessment_turn(
        f"Spot on.\n{_score_marker(cid)}", state, "en"
    )
    assert len(all_scores) == 1 and done is False
    assert "[[SCORE" in content
    assert "add to or revise your answer" not in content
    assert "**Question 2 of 4**" in results.strip_markers(content)


def test_forced_finalisation_accepts_partial_score() -> None:
    messages = _grade_first_messages()
    # the learner has used their one correction (assistant offered, learner answered again)
    messages = messages + [
        {"role": "assistant", "content": results._locale("en")["correction_offer"]},
        {"role": "user", "content": "still partial"},
    ]
    state = results.derive_turn_state(messages)
    assert state["must_finalize_current"] is True
    cid = state["current_id"]
    content, all_scores, _tally, done = results.render_assessment_turn(
        f"That's where we'll leave it.\n{_partial_score_marker(cid)}", state, "en"
    )
    assert len(all_scores) == 1 and done is False
    assert "[[SCORE" in content
    assert "**Question 2 of 4**" in results.strip_markers(content)


def test_chained_next_question_is_recognized_as_asked() -> None:
    messages, _content, _state, _done = _turn([], "Start")  # asks M1-Q1
    messages, _content, _state, _done = _turn(messages, "answer to q1", full_marks=True)  # grades Q1, chains Q2
    # learner answers Q2 with no "next" in between → must be graded, not re-asked
    messages = messages + [{"role": "user", "content": "answer to q2"}]
    state = results.derive_turn_state(messages)
    assert state["n_in_module"] == 1
    assert state["current_id"] == module_questions("M1")[1]
    assert state["current_question_asked"] is True and state["latest_user_answer_pending"] is True
    injection = results.build_state_injection(state, "en")
    assert "CURRENT ACTION: GRADE" in injection and "CURRENT ACTION: ASK" not in injection


def _drive_to_final_question(full_marks: bool = True):
    """History positioned at M10's last question — already asked, with the learner's first answer pending."""
    messages, _content, _state, _done = _turn([], "Start")
    for module_key in MODULES:
        if module_key == "M10":
            break
        messages, _content, _done = _answer_module(messages, full_marks=True)
        messages, _content, _state, _done = _turn(messages, "Continue")
    m10 = module_questions("M10")
    for _ in range(len(m10) - 1):
        messages, _content, _state, _done = _turn(messages, "answer", full_marks=full_marks)
    return messages + [{"role": "user", "content": "a first answer to the last question"}]


def test_state_injection_final_question_has_no_summary_and_finalises_like_any_last_question() -> None:
    # The model no longer authors the ending: the final question is handled like any last question
    # (brief feedback + [[SCORE]]); the backend renders the summary. So the injection must NOT ask for
    # [[SUMMARY]]/take-aways.
    messages = _drive_to_final_question()
    state = results.derive_turn_state(messages)
    assert state["is_last_in_module"] and state["is_final_module"]
    injection = results.build_state_injection(state, "en")
    assert "[[SUMMARY]]" not in injection
    assert "LAST question of the FINAL module" in injection
    assert "do NOT write any summary" in injection


def test_final_question_partial_first_answer_offers_correction_without_summary() -> None:
    # The exact screenshot scenario: a partial first answer to the very last question. The learner must
    # get a correction offer (position held) — and NO premature summary/take-aways may leak, even from a
    # model that misbehaves and tries to author the whole ending.
    messages = _drive_to_final_question()
    state = results.derive_turn_state(messages)
    assert state["is_last_in_module"] and state["is_final_module"]
    assert state["latest_user_answer_pending"] and not state["must_finalize_current"]
    cid = state["current_id"]
    misbehaving = (
        "Good start, but something is still missing.\n\n"
        "[[SUMMARY]]\nStrengths: pacing. Worth revisiting: periodization.\n\n"
        f"{_partial_score_marker(cid)}"
    )
    content, all_scores, _tally, done = results.render_assessment_turn(misbehaving, state, "en")
    assert done is False
    assert "[[SCORE" not in content and "[[DONE" not in content and "[[PROGRESS" not in content
    assert "add to or revise your answer" in content  # correction offered, position held
    # The final question is NOT scored yet (only the earlier M10 questions are).
    assert len(all_scores) == len(module_questions("M10")) - 1
    display = results.strip_markers(content)
    assert "periodization" not in display and "Worth revisiting" not in display  # take-aways cut
    assert "Summary by module" not in display  # no premature summary


def test_final_question_completes_after_correction_with_module_summary() -> None:
    # After the one correction is used, finalising the last question completes the whole assessment:
    # module result + the deterministic module-by-module summary + completion markers, in one turn.
    messages = _drive_to_final_question()
    messages = messages + [
        {"role": "assistant", "content": results._locale("en")["correction_offer"]},
        {"role": "user", "content": "my improved final answer"},
    ]
    state = results.derive_turn_state(messages)
    assert state["must_finalize_current"] is True
    cid = state["current_id"]
    content, all_scores, tally, done = results.render_assessment_turn(
        f"Much better — that covers it.\n{_score_marker(cid)}", state, "en"
    )
    assert done is True and tally["passed"]
    assert "[[DONE]]" in content and "[[PROGRESS value=100]]" in content
    bubbles = [b.strip() for b in content.split(results.BUBBLE_BREAK_TOKEN)]
    assert len(bubbles) == 5
    assert "passed every module" in bubbles[1].lower()
    summary_display = results.strip_markers(bubbles[2])
    assert "Summary by module" in summary_display
    for module_key in MODULES:
        assert results._module_display(module_key, "en") in summary_display
    assert "certificate" in bubbles[4].lower()
    assert len(all_scores) == TOTAL_QUESTIONS  # cross-module totals built from every question


# --- give-up / leaked-question / rendering --------------------------------


def test_is_give_up_or_meta_only_matches_whole_message_give_ups() -> None:
    for msg in ["next", "skip", "Next!", "ok, next please", "I don't know", "no clue", "keine Ahnung", "geen idee"]:
        assert results.is_give_up_or_meta(msg) is True, msg
    for msg in [
        "",
        "run to the next station",
        "do it again on the next round",
        "The coach shortens the rest interval before the next attempt and adds a posture cue.",
    ]:
        assert results.is_give_up_or_meta(msg) is False, msg


def test_strip_leaked_question_text_removes_pool_question_but_keeps_feedback_and_markers() -> None:
    leaked = _question_text(1)
    body = f"Excellent — clear and well explained.\n\n{leaked}"
    out = results.strip_leaked_question_text(body)
    assert "Excellent — clear and well explained." in out
    assert results.paragraph_reproduces_pool_question(leaked) is True
    assert results.paragraph_reproduces_pool_question("Got the core idea — something is still missing.") is False
    marker = _score_marker(1)
    assert marker in results.strip_leaked_question_text(f"Nice work.\n\n{marker}")


def test_render_helpers_localized() -> None:
    assert results.render_progress_header(1, 4, "en") == "**Question 1 of 4**"
    assert results.render_progress_header(2, 5, "de") == "**Frage 2 von 5**"
    assert results.render_progress_header(3, 3, "nl") == "**Vraag 3 van 3**"
    assert results.render_question_score(1, 4, 6, "en") == "**Question 1: 4/6**"
    passed = results.render_module_result("M1", {"score": 12, "max": 13, "pct": 92, "passed": True}, "en")
    assert "Module 1" in passed and "Passed" in passed and "12/13" in passed
    failed = results.render_module_result("M2", {"score": 6, "max": 12, "pct": 50, "passed": False}, "de")
    assert "Modul 2" in failed and "80%" in failed


def test_strip_markers_removes_all_assessment_markers() -> None:
    text = 'A\n\n[[BREAK]]\n\nB [[SUMMARY]] [[MODPASS m=M1]] [[MODULE m=M2 attempt=1]] [[SCORE q=1 points="1" max=3 mod="M1"]]'
    out = results.strip_markers(text)
    assert "[[" not in out
    assert "A" in out and "B" in out


# --- record_assessment_result --------------------------------------------


def test_record_assessment_result_builds_payload_with_module_breakdown() -> None:
    scores = [results.normalize_score(1, [1] * key_point_count(1)), results.normalize_score(5, [1] * key_point_count(5))]
    tally = results.compute_tally(scores)
    payload = asyncio.run(
        results.record_assessment_result(
            scores=scores,
            tally=tally,
            messages=[{"role": "user", "content": "start"}],
            final_content="done",
            overrides={"language": "en", "account_id": "123", "first_name": "John", "last_name": "Doe"},
            auth_claims={},
            session_state="sess-123",
            blob_manager=None,
        )
    )
    assert payload is not None
    assert payload["passed"] is True
    assert payload["session_id"] == "sess-123"
    assert payload["user_id"] == "123"
    assert payload["first_name"] == "John" and payload["last_name"] == "Doe"
    assert payload["module_breakdown"]  # non-empty per-module breakdown
    assert "M1" in payload["module_breakdown"]
