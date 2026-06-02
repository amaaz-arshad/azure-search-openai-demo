"""Deterministic state engine, session log, and LMS-reporting stub for the HYROX assessment bot.

The assessment is **backend-driven and stateless**. On every turn the backend
reconstructs authoritative state from hidden control markers that persist in the
replayed conversation history (the frontend hides them at render but keeps them in
the stored message, so they replay into the next request):

* ``[[PLAN ids=...]]`` — the fixed list of 20 question numbers for a run. **The
  backend authors this** (a balanced random sample of 20 of the 32 pool questions),
  appends it to the first assistant message, and reads it back thereafter. The model
  never chooses questions.
* ``[[SCORE q=K points="1,1,0,1" max=Y cat="..."]]`` — emitted by the model when it
  finalises question K. The model only supplies the **per-key-point 0/1 verdict**; the
  backend computes ``awarded = min(sum(points), max_pts)`` from ``questions.py`` (the
  authoritative rubric), validates the array length, and forces ``q`` to the pinned id.

The backend owns the question counter, selection, no-repeat guarantee, running tally,
percentage, and pass/fail — it renders all of these numbers into the message itself
(``render_*``) so the model can neither miscount nor mis-add. When the 20th question is
finalised, ``record_assessment_result`` writes a session log and calls the LMS stub.
"""

import json
import logging
import random
import re
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Optional

from approaches.chatbots.hyrox_assessment.questions import (
    CATEGORIES,
    QUESTIONS,
    category_of,
    key_point_count,
    max_points,
)

logger = logging.getLogger("hyrox_assessment")

QUESTIONS_PER_RUN = 20
PASS_THRESHOLD_PERCENT = 80

# Hidden control markers. Kept permissive (case-insensitive, tolerant of spacing).
PLAN_MARKER_RE = re.compile(r"\[\[\s*PLAN\b([^\]]*)\]\]", re.IGNORECASE)
SCORE_MARKER_RE = re.compile(r"\[\[\s*SCORE\b([^\]]*)\]\]", re.IGNORECASE)
RESULT_MARKER_RE = re.compile(r"\[\[\s*RESULT\b([^\]]*)\]\]", re.IGNORECASE)
ANY_MARKER_RE = re.compile(r"\[\[\s*(?:PLAN|SCORE|RESULT)\b[^\]]*\]\]", re.IGNORECASE)
# Placement token the model writes immediately before a question it is asking; the backend
# replaces it with the localized "Question N of 20" header so the header lands right above
# the question and only on messages that actually ask one.
ASK_TOKEN_RE = re.compile(r"\[\[\s*ASK\s*\]\]", re.IGNORECASE)

# Lines the model is told NOT to write (the backend renders them) — stripped as defense
# in depth so a stray model-written header/total can never duplicate or contradict ours.
_HEADER_LINE_RE = re.compile(
    r"^\s*\*{0,2}\s*(?:Question|Frage|Vraag)\s+\d+\s+(?:of|von|van)\s+\d+\s*\*{0,2}\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_TOTAL_LINE_RE = re.compile(
    r"^\s*\*{0,2}\s*(?:Score so far|Punktestand|Stand|Gesamtpunkte|Totaal|Total)\b[^\n]*\d+\s*/\s*\d+[^\n]*$",
    re.IGNORECASE | re.MULTILINE,
)
_COMPLETE_LINE_RE = re.compile(
    r"^\s*\*{0,2}\s*(?:Assessment complete|Bewertung abgeschlossen|Beoordeling voltooid)\b[^\n]*$",
    re.IGNORECASE | re.MULTILINE,
)


# --- localisation of the rendered numbers ---------------------------------------------
_LOCALES: dict[str, dict[str, str]] = {
    "en": {
        "header": "**Question {n} of {total}**",
        "question_score": "**Question {n}: {s}/{m}**",
        "result": "**Assessment complete** — Total: {s}/{m} ({p}%) — **{verdict}**",
        "passed": "PASSED",
        "failed": "NOT PASSED",
    },
    "de": {
        "header": "**Frage {n} von {total}**",
        "question_score": "**Frage {n}: {s}/{m}**",
        "result": "**Bewertung abgeschlossen** — Gesamt: {s}/{m} ({p}%) — **{verdict}**",
        "passed": "BESTANDEN",
        "failed": "NICHT BESTANDEN",
    },
    "nl": {
        "header": "**Vraag {n} van {total}**",
        "question_score": "**Vraag {n}: {s}/{m}**",
        "result": "**Beoordeling voltooid** — Totaal: {s}/{m} ({p}%) — **{verdict}**",
        "passed": "GESLAAGD",
        "failed": "NIET GESLAAGD",
    },
}


def _locale(language: Optional[str]) -> dict[str, str]:
    code = (language or "en")[:2].lower()
    return _LOCALES.get(code, _LOCALES["en"])


# --- question selection (deterministic given a seed) ----------------------------------
def select_question_plan(seed: Any = None) -> list[int]:
    """Pick exactly ``QUESTIONS_PER_RUN`` distinct question numbers, balanced across the
    8 categories and in randomised ask order. With a fixed ``seed`` the result is
    reproducible (used for audit + tests)."""
    rng = random.Random(seed)
    by_cat: dict[str, list[int]] = {c: [] for c in CATEGORIES}
    for q in QUESTIONS:
        by_cat.setdefault(q["category"], []).append(q["number"])
    cats = [c for c in by_cat if by_cat[c]]
    rng.shuffle(cats)
    for c in cats:
        rng.shuffle(by_cat[c])

    chosen: list[int] = []
    cursor = {c: 0 for c in cats}
    while len(chosen) < QUESTIONS_PER_RUN:
        progressed = False
        for c in cats:
            if len(chosen) >= QUESTIONS_PER_RUN:
                break
            i = cursor[c]
            if i < len(by_cat[c]):
                chosen.append(by_cat[c][i])
                cursor[c] += 1
                progressed = True
        if not progressed:  # exhausted the pool (should not happen: 32 >= 20)
            break
    rng.shuffle(chosen)  # round-robin order is too predictable — randomise the sequence
    return chosen


def format_plan_marker(plan_ids: list[int]) -> str:
    return "[[PLAN ids=" + ",".join(str(i) for i in plan_ids) + "]]"


def parse_plan_ids(body: str) -> list[int]:
    match = re.search(r"ids\s*=\s*([0-9,\s]+)", body or "", re.IGNORECASE)
    if not match:
        return []
    return [int(x) for x in re.findall(r"\d+", match.group(1))]


# --- score markers --------------------------------------------------------------------
def _parse_attrs(body: str) -> dict[str, Any]:
    attrs: dict[str, Any] = {}
    for key, qval, uval in re.findall(r'(\w+)\s*=\s*(?:"([^"]*)"|([^\s\]]+))', body or ""):
        attrs[key] = qval if qval != "" else uval
    return attrs


def parse_points(value: Any) -> list[int]:
    """Parse a ``points`` attribute (e.g. ``"1,1,0,1"``) into a list of 0/1 ints."""
    if value is None:
        return []
    return [1 if x.strip() not in ("", "0") else 0 for x in str(value).split(",") if x.strip() != ""]


def normalize_score(q: Any, points: list[int]) -> dict[str, Any]:
    """Authoritative per-question score from ``questions.py`` — the model's arithmetic is
    not trusted. Validates/clamps the per-point array to the question's key-point count
    and caps ``awarded`` at the question's ``max_pts``."""
    try:
        qid = int(q)
    except (TypeError, ValueError):
        qid = q
    expected = key_point_count(qid) if isinstance(qid, int) else 0
    cap = max_points(qid) if isinstance(qid, int) else 0
    pts = [1 if p else 0 for p in points]
    if expected:
        if len(pts) > expected:
            logger.warning("HYROX SCORE q=%s: %d points for %d key points; truncating", qid, len(pts), expected)
            pts = pts[:expected]
        elif len(pts) < expected:
            logger.warning("HYROX SCORE q=%s: %d points for %d key points; padding 0", qid, len(pts), expected)
            pts = pts + [0] * (expected - len(pts))
    awarded = min(sum(pts), cap) if cap else sum(pts)
    return {
        "q": qid,
        "points": pts,
        "awarded": awarded,
        "max": cap,
        "cat": category_of(qid) if isinstance(qid, int) else "",
    }


def parse_new_score(text: Optional[str], current_id: Optional[int]) -> Optional[dict[str, Any]]:
    """Parse the (single) finalising ``[[SCORE]]`` marker from this turn's output, if any.
    The question id is forced to ``current_id`` (the backend-pinned question)."""
    if not text:
        return None
    match = SCORE_MARKER_RE.search(text)
    if not match:
        return None
    attrs = _parse_attrs(match.group(1))
    qid = current_id if current_id is not None else attrs.get("q")
    return normalize_score(qid, parse_points(attrs.get("points")))


def compute_tally(scores: list[dict[str, Any]]) -> dict[str, Any]:
    """Authoritative cumulative tally from normalised per-question scores."""
    awarded = sum(int(s.get("awarded", 0) or 0) for s in scores)
    maximum = sum(int(s.get("max", 0) or 0) for s in scores)
    pct = round(100 * awarded / maximum) if maximum else 0
    return {
        "questions_scored": len(scores),
        "score": awarded,
        "max": maximum,
        "pct": pct,
        "passed": maximum > 0 and pct >= PASS_THRESHOLD_PERCENT,
    }


def category_breakdown(scores: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Per-category awarded/max — the basis for the strengths/weaknesses take-aways."""
    out: dict[str, dict[str, int]] = {}
    for s in scores:
        cat = str(s.get("cat", "")) or "(uncategorised)"
        bucket = out.setdefault(cat, {"awarded": 0, "max": 0})
        bucket["awarded"] += int(s.get("awarded", 0) or 0)
        bucket["max"] += int(s.get("max", 0) or 0)
    return out


# --- per-turn state machine -----------------------------------------------------------
def assistant_texts(messages: list[dict[str, Any]], final_content: Optional[str] = None) -> list[str]:
    texts: list[str] = []
    for msg in messages or []:
        if isinstance(msg, dict) and msg.get("role") == "assistant":
            content = msg.get("content")
            if isinstance(content, str):
                texts.append(content)
    if isinstance(final_content, str):
        texts.append(final_content)
    return texts


def _scores_in_window(window: str, plan_ids: list[int]) -> list[dict[str, Any]]:
    by_q: dict[int, dict[str, Any]] = {}
    for m in SCORE_MARKER_RE.finditer(window):
        attrs = _parse_attrs(m.group(1))
        q_raw = attrs.get("q")
        if q_raw is None:
            continue
        try:
            qid = int(q_raw)
        except (TypeError, ValueError):
            continue
        if qid in plan_ids:
            by_q[qid] = normalize_score(qid, parse_points(attrs.get("points")))
    # preserve plan order so current_id == plan[n_scored]
    return [by_q[q] for q in plan_ids if q in by_q]


def _fresh_run_state(seed: Any = None) -> dict[str, Any]:
    plan = select_question_plan(seed)
    return {
        "plan": plan,
        "plan_is_new": True,
        "scores": [],
        "n_scored": 0,
        "current_id": plan[0] if plan else None,
        "tally": compute_tally([]),
        "completed_passed": False,
    }


def derive_turn_state(messages: list[dict[str, Any]], final_content: Optional[str] = None) -> dict[str, Any]:
    """Reconstruct the authoritative assessment state for this turn from replayed history.

    A run's score window is everything after the most recent ``[[PLAN]]`` marker. A new
    session (no PLAN) starts a fresh run; a *failed* completed run auto-starts a fresh run
    on the next turn (``fail → restart immediately``); a *passed* completed run is done.
    """
    texts = assistant_texts(messages, final_content)
    blob = "\n".join(texts)

    plan_match = None
    for m in PLAN_MARKER_RE.finditer(blob):
        plan_match = m
    if plan_match is None:
        return _fresh_run_state()

    plan_ids = parse_plan_ids(plan_match.group(1))
    if not plan_ids:
        return _fresh_run_state()

    window = blob[plan_match.end():]
    scores = _scores_in_window(window, plan_ids)
    n_scored = len(scores)
    tally = compute_tally(scores)

    if n_scored >= QUESTIONS_PER_RUN:
        if not tally["passed"]:
            return _fresh_run_state()  # failed run complete → next turn begins a new run
        return {
            "plan": plan_ids,
            "plan_is_new": False,
            "scores": scores,
            "n_scored": n_scored,
            "current_id": None,
            "tally": tally,
            "completed_passed": True,
        }

    return {
        "plan": plan_ids,
        "plan_is_new": False,
        "scores": scores,
        "n_scored": n_scored,
        "current_id": plan_ids[n_scored],
        "tally": tally,
        "completed_passed": False,
    }


def build_state_injection(state: dict[str, Any], language: Optional[str] = None) -> str:
    """The system-controlled block appended to the prompt each turn. Pins the LLM to a
    single question and forbids it from producing any numbers or owning the plan."""
    total = QUESTIONS_PER_RUN
    current_id = state.get("current_id")

    if current_id is None:
        # Completed + passed (a failed run would have auto-restarted with a current_id).
        return (
            "\n\n## CURRENT TURN STATE (system-controlled — obey exactly)\n"
            f"- All {total} questions are finalised and the learner has passed. Do NOT ask any further question "
            "and do NOT emit any marker.\n"
            "- Briefly acknowledge that the assessment is complete; if they want another attempt, tell them to "
            "start a new assessment. The system renders the final score and verdict.\n"
        )

    n = state.get("n_scored", 0)
    kpc = key_point_count(current_id)
    cap = max_points(current_id)
    cat = category_of(current_id)
    is_last = (n == total - 1)
    is_first_of_run = (n == 0)

    lines = [
        "\n\n## CURRENT TURN STATE (system-controlled — authoritative; overrides any conflicting instruction)",
        f"- Questions finalised so far this run: {n} of {total}.",
        f"- The ONLY question you may handle this turn is pool question #{current_id} "
        f"(category: {cat}); it has {kpc} required key points and a maximum of {cap} points.",
        f"- If question #{current_id} has not yet been asked in this conversation, ask it now: put the token "
        "[[ASK]] on its own line IMMEDIATELY before the question text, then the question. Translate the question "
        "faithfully into the learner's language and reveal ONLY the question text (never the pool number, "
        "category, point values, or rubric).",
        "- If the learner has already answered it, give reduced feedback and run the one-correction protocol; "
        "when the question is finalised, end your message with EXACTLY one marker on its own line:",
        f'  [[SCORE q={current_id} points="<{kpc} comma-separated values, one 0 or 1 per key point in listed '
        f'order>" max={cap} cat="{cat}"]]',
        "- Award 1 for each key point the learner demonstrated and 0 otherwise (apply the safeguarding "
        "critical-fail rule). The system sums these values — your job is the per-point judgement only.",
        "- Write NO numbers anywhere (no question number, per-question score, running total, percentage, or "
        "pass/fail). Place [[ASK]] ONLY on a message where you actually ask the question — never on a feedback, "
        "correction-offer, or finalisation/score-only message. The system replaces [[ASK]] with the correct "
        '"Question N of 20" header, shows each question\'s score when it is graded, and shows the cumulative '
        "result only at the end. Never emit [[PLAN]] or [[RESULT]]; the system owns those.",
    ]
    if is_first_of_run:
        lines.append(
            "- This is the first question of the run: open with a brief, friendly intro (20 questions, free-text "
            "answers, one correction each, 80% overall to pass, a topic summary at the end), then ask the question."
        )
    if is_last:
        lines.append(
            "- This is the final planned question: after finalising it, add a brief closing message and, only if "
            "appropriate, topic take-aways. Ask nothing further. The system appends the final score and verdict."
        )
    return "\n".join(lines) + "\n"


# --- rendering the authoritative numbers into the message -----------------------------
def strip_rendered_numbers(text: Optional[str]) -> str:
    """Remove any progress header / running total / completion line the model wrote
    (it is told not to; this guarantees only the backend's numbers appear)."""
    if not text:
        return text or ""
    cleaned = _HEADER_LINE_RE.sub("", text)
    cleaned = _TOTAL_LINE_RE.sub("", cleaned)
    cleaned = _COMPLETE_LINE_RE.sub("", cleaned)
    cleaned = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", cleaned)
    return cleaned.strip()


def strip_markers(text: Optional[str]) -> str:
    """Remove all hidden control markers from text (defense in depth; the frontend also hides them)."""
    if not text:
        return text or ""
    cleaned = ANY_MARKER_RE.sub("", text)
    cleaned = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", cleaned)
    return cleaned.strip()


def render_progress_header(n_scored_after: int, language: Optional[str] = None) -> str:
    L = _locale(language)
    return L["header"].format(n=n_scored_after + 1, total=QUESTIONS_PER_RUN)


def render_question_score(position: int, awarded: int, maximum: int, language: Optional[str] = None) -> str:
    """The score for a single question, shown once that question is graded (e.g. "Question 1: 4/6")."""
    L = _locale(language)
    return L["question_score"].format(n=position, s=awarded, m=maximum)


def render_final_result(tally: dict[str, Any], language: Optional[str] = None) -> str:
    L = _locale(language)
    verdict = L["passed"] if tally["passed"] else L["failed"]
    return L["result"].format(s=tally["score"], m=tally["max"], p=tally["pct"], verdict=verdict)


def render_assessment_turn(
    content: Optional[str],
    state: dict[str, Any],
    language: Optional[str] = None,
) -> tuple[str, list[dict[str, Any]], dict[str, Any], bool]:
    """Post-process one assistant message:

    * strip any numbers the model wrote (defense in depth),
    * replace the model's ``[[ASK]]`` placement token with the authoritative
      "Question N of 20" header, so the header sits right above the question and only
      on messages that actually ask one,
    * when a question is finalised this turn, show that single question's score,
    * at the very end (20th question), show the cumulative total + pass/fail,
    * keep the hidden [[SCORE]] markers so they replay, and append the backend-authored
      [[PLAN]] marker on a fresh run.

    There is intentionally NO running cumulative total mid-assessment — only the
    per-question score when graded and the final cumulative result.

    Returns ``(content, all_scores, tally, just_completed)``.
    """
    body = strip_rendered_numbers(content)

    new_score = parse_new_score(content, state.get("current_id"))
    all_scores = list(state.get("scores", []))
    if new_score is not None:
        all_scores = [s for s in all_scores if s["q"] != new_score["q"]] + [new_score]
    tally = compute_tally(all_scores)
    n_after = len(all_scores)
    just_completed = new_score is not None and n_after >= QUESTIONS_PER_RUN

    # Replace the model's [[ASK]] token with the header for the question being asked.
    # The asked question's run position is n_after + 1 (any question finalised in this
    # same message has already been counted into n_after). Past completion, drop the token.
    if n_after < QUESTIONS_PER_RUN:
        body = ASK_TOKEN_RE.sub(render_progress_header(n_after, language), body, count=1)
    body = ASK_TOKEN_RE.sub("", body)  # remove any stray/extra token

    parts: list[str] = []
    if new_score is not None:
        # The just-graded question's run position is n_after (it is the latest finalised one).
        parts.append(render_question_score(n_after, new_score["awarded"], new_score["max"], language))
    if body:
        parts.append(body)
    if just_completed:
        parts.append(render_final_result(tally, language))
    assembled = "\n\n".join(p for p in parts if p)

    if state.get("plan_is_new") and state.get("plan"):
        assembled = (assembled + "\n\n" + format_plan_marker(state["plan"])).strip()

    return assembled, all_scores, tally, just_completed


# --- result recording + LMS stub ------------------------------------------------------
def build_result_payload(
    *,
    session_id: Optional[str],
    user_id: Optional[str],
    language: Optional[str],
    tally: dict[str, Any],
    scores: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the result payload the LMS will consume (pass→certificate)."""
    return {
        "session_id": session_id,
        "user_id": user_id,
        "language": language,
        "passed": tally["passed"],
        "score": tally["score"],
        "max": tally["max"],
        "percent": tally["pct"],
        "pass_threshold_percent": PASS_THRESHOLD_PERCENT,
        "category_breakdown": category_breakdown(scores),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }


def report_result_to_lms(payload: dict[str, Any]) -> None:
    """STUB: hand the assessment result to the Lemon LMS.

    Lemon owns the real interface (endpoint, payload schema, auth). Until that is
    defined, this logs the payload so the result is observable and the wiring point is
    unambiguous. Replace the body with the real HTTP call when ready.
    """
    logger.info("HYROX assessment result (LMS report stub): %s", json.dumps(payload, ensure_ascii=False))


async def record_assessment_result(
    *,
    scores: list[dict[str, Any]],
    tally: dict[str, Any],
    messages: list[dict[str, Any]],
    final_content: Optional[str],
    overrides: dict[str, Any],
    auth_claims: dict[str, Any],
    session_state: Any,
    blob_manager: Any = None,
) -> Optional[dict[str, Any]]:
    """Write the session log and report to the LMS for a just-completed assessment.

    Called by the chat approach only when the 20th question is finalised this turn
    (``render_assessment_turn`` returns ``just_completed=True``). Best-effort: never
    raises into the chat flow.
    """
    try:
        session_id = session_state if isinstance(session_state, str) else None
        user_id = auth_claims.get("oid") or overrides.get("user")
        language = overrides.get("language")

        payload = build_result_payload(
            session_id=session_id,
            user_id=user_id,
            language=language,
            tally=tally,
            scores=scores,
        )
        log_record = {
            **payload,
            "scores": scores,
            "transcript": [
                {"role": m.get("role"), "content": m.get("content")}
                for m in (messages or [])
                if isinstance(m, dict) and isinstance(m.get("content"), str)
            ]
            + ([{"role": "assistant", "content": final_content}] if isinstance(final_content, str) else []),
        }

        await _write_session_log(blob_manager, session_id, log_record)
        report_result_to_lms(payload)
        logger.info(
            "HYROX assessment finalised: session=%s passed=%s score=%s/%s (%s%%)",
            session_id,
            tally["passed"],
            tally["score"],
            tally["max"],
            tally["pct"],
        )
        return payload
    except Exception:  # logging must never break the chat response
        logger.exception("Failed to record HYROX assessment result")
        return None


async def _write_session_log(blob_manager: Any, session_id: Optional[str], log_record: dict[str, Any]) -> None:
    """Persist the session log to blob storage when a BlobManager is available."""
    if blob_manager is None or not hasattr(blob_manager, "upload_blob_data"):
        logger.info("HYROX assessment session log (no blob manager): %s", json.dumps(log_record, ensure_ascii=False))
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    blob_name = f"hyrox-assessment-logs/{session_id or 'session'}-{stamp}.json"
    data = BytesIO(json.dumps(log_record, ensure_ascii=False, indent=2).encode("utf-8"))
    try:
        await blob_manager.upload_blob_data(data, blob_name, content_type="application/json")
        logger.info("HYROX assessment session log written: %s", blob_name)
    except Exception:
        logger.exception("Failed to upload HYROX assessment session log to blob: %s", blob_name)
