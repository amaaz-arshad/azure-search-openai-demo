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

import difflib
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
    get_question,
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
ANY_MARKER_RE = re.compile(r"\[\[\s*(?:PLAN|SCORE|RESULT|ASKED|ASK|SUMMARY|BREAK|PROGRESS|DONE)\b[^\]]*\]\]", re.IGNORECASE)
# Backend-authored, hidden: emitted once on a passed completion to hand the result back to the
# Lemon app. The frontend hides it at render and fires lemon://save_progress?value=N (see
# lemonBridge.reportLemonProgress). Only emitted on pass — never on a failed completion.
PROGRESS_PASS_VALUE = 100
PROGRESS_MARKER = f"[[PROGRESS value={PROGRESS_PASS_VALUE}]]"
# Backend-authored, hidden: emitted once on ANY completion (pass OR fail) on the turn the final
# question is graded. The frontend hides it at render and uses it to remove the question input,
# since a completed run is terminal in this session regardless of outcome (retaking happens in the
# Lemon app, which launches a fresh session). It replays in history, so a reopened completed
# session stays terminal. Unlike PROGRESS (pass only), this fires for both pass and fail.
DONE_MARKER = "[[DONE]]"
# Written by the model on the final turn only, between its feedback on the last answer and
# its topic take-aways. The backend splits there so the final result verdict can be rendered
# between them as its own display bubble.
SUMMARY_TOKEN_RE = re.compile(r"\[\[\s*SUMMARY\s*\]\]", re.IGNORECASE)
# Backend-authored display split point: the frontend renders one chat bubble per
# [[BREAK]]-separated section while storing the full message, so replay is unaffected.
BUBBLE_BREAK_TOKEN = "[[BREAK]]"
BUBBLE_BREAK_SEPARATOR = f"\n\n{BUBBLE_BREAK_TOKEN}\n\n"
# Placement token the model writes when a question should be asked; the backend replaces it
# with the localized "Question N of 20" header plus the exact pinned question text from
# questions.py. The model must not author visible question text because it can pick the
# wrong pool question from the large rubric prompt.
ASK_TOKEN_RE = re.compile(r"\[\[\s*ASK\s*\]\]", re.IGNORECASE)
# Backend-written (never by the model), hidden: records that the backend rendered (asked)
# pool question K this turn. The next question is presented automatically right after the
# previous question's [[SCORE]] (so the learner never has to type "next"), which puts the
# ask in the SAME message as a score marker. This explicit marker lets the stateless
# re-derivation know the question was already presented regardless of message boundaries.
ASKED_MARKER_RE = re.compile(r"\[\[\s*ASKED\b([^\]]*)\]\]", re.IGNORECASE)

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
# Give-up / meta detection. A give-up or meta turn ("next", "skip", "I don't know", "why are
# you asking?") is one whose WHOLE message is that statement. A substantive answer can
# incidentally contain a trigger word — "...before the next attempt", "run to the next station",
# "do it again", "I don't know if X, but ..." — and must NEVER be mistaken for giving up, because
# that wrongly forces finalisation and skips the learner's one correction. So instead of a
# substring search we anchor a full-message match (modulo trivial wrappers), so the trigger word
# must BE the message, not merely appear in it.

# Politeness / filler that may wrap a bare give-up without changing its meaning, e.g.
# "ok, next please", "sorry — no idea", "yeah let's move on". Stripped (zero or more) from either
# end before matching. "no" is deliberately NOT filler (it begins "no idea" / "no clue").
_GIVE_UP_FILLER = (
    r"ok(?:ay)?|well|um+|uh+|hmm+|so|just|please|sorry|thanks|thank you|yeah|yep|hey|hi|hello|"
    r"i guess|maybe|honestly|lets|can we"
)

# Canonical give-up / meta statements (apostrophes are removed by normalisation first, so the
# patterns are apostrophe-free: "dont", "ill", "lets", "whats").
_GIVE_UP_CORE = (
    r"i dont know(?: it| this| that| the answer| this one| that one)?|"
    r"i do not know(?: it| this| that| the answer| this one| that one)?|"
    r"dont know|do not know|no idea|no clue|not sure|"
    r"skip(?: it| this| this one| the question)?|"
    r"move on|next(?: question| one)?|i pass|ill pass|pass|"
    r"already answered(?: it| this)?|answered (?:it|this)(?: already)?|"
    r"why (?:are|do) you ask(?:ing)?(?: me)?(?: this)?(?: again)?|"
    r"same question(?: again)?|asking again|"
    # German
    r"ich weiss(?: es)? nicht|ich weiß(?: es)? nicht|keine ahnung|überspringen|weiter|nächste(?: frage)?|"
    # Dutch
    r"ik weet het niet|geen idee|overslaan|volgende(?: vraag)?"
)

_GIVE_UP_OR_META_FULL_RE = re.compile(
    rf"^(?:(?:{_GIVE_UP_FILLER})\s+)*(?:{_GIVE_UP_CORE})(?:\s+(?:{_GIVE_UP_FILLER}))*$",
    re.IGNORECASE,
)

# Genuine give-ups are short; cap length as a cheap guard (and to bound regex backtracking).
_GIVE_UP_MAX_WORDS = 8


def normalize_give_up_text(text: str) -> str:
    """Lowercase, drop apostrophes, and collapse every non-letter/digit run to a single space so
    the anchored match is robust to punctuation and quote style ("Next!" / "I don't know." →
    "next" / "i dont know")."""
    lowered = text.lower().replace("'", "").replace("’", "").replace("`", "")
    return re.sub(r"[\W_]+", " ", lowered).strip()


def is_give_up_or_meta(text: Optional[str]) -> bool:
    """True only when the WHOLE message is a give-up/meta statement (modulo trivial filler like
    "ok"/"please"/"sorry") — never for a substantive answer that merely contains a trigger word.
    So "next", "ok next please", "I don't know" are give-ups, while "run to the next station" and
    "...before the next attempt" are answers."""
    if not text or not text.strip():
        return False
    if len(text.split()) > _GIVE_UP_MAX_WORDS:
        return False
    normalized = normalize_give_up_text(text)
    if not normalized:
        return False
    return bool(_GIVE_UP_OR_META_FULL_RE.fullmatch(normalized))


# --- localisation of the rendered numbers ---------------------------------------------
_LOCALES: dict[str, dict[str, str]] = {
    "en": {
        "header": "**Question {n} of {total}**",
        "question_score": "**Question {n}: {s}/{m}**",
        "result": "**Assessment complete** — Total: {s}/{m} ({p}%) — **{verdict}**",
        "passed": "PASSED",
        "failed": "Failed",
        "correction_offer": "You have one opportunity to add to or revise your answer — go ahead if you'd like.",
        "summary_heading": "**Summary by topic**",
        "summary_strengths": "Strengths:",
        "summary_weaknesses": "Needs work:",
        "motivational_passed": (
            "Great job. This wasn't a formality. You worked through the material, you answered the "
            "questions, and you passed.\n\n"
            "Managing performance is one of the most demanding skills a HYROX coach can develop. The fact "
            "that you've completed this module means you're building the kind of foundation that makes a "
            "real difference — to your athletes, and to your practice.\n\n"
            "This is a step in the right direction. Not the last one — but a meaningful one.\n\n"
            "Keep going. Your athletes will feel the difference."
        ),
        "motivational_failed": (
            "That's not the result you were hoping for, and there's no reason to dress it up. What counts "
            "is this: you sat the full assessment and put your knowledge on the line.\n\n"
            "Managing performance and keeping young athletes safe is some of the hardest work a HYROX coach "
            "takes on, and few people get all of it right on the first pass. The gaps this assessment "
            "surfaced are specific, and every one of them is something you can close.\n\n"
            "Go back over the areas flagged above, work through them, and come at it again. The coaches who "
            "make the biggest difference are often the ones who didn't pass first time and kept going. Your "
            "athletes are worth that."
        ),
        "closing_passed": (
            "You can now close the assessment, and your certificate will be generated. Please wait until "
            "you receive the corresponding notification. You will then find the certificate in the app and "
            "receive it again via email."
        ),
        "closing_failed": (
            "You can take this assessment again. Before you do, go back over the topics highlighted above "
            "so your next attempt builds on what you've just worked through. When you're ready, you'll find "
            "the option to restart the assessment in the lemon app. Take the time you need, and come back "
            "when you feel prepared."
        ),
    },
    "de": {
        "header": "**Frage {n} von {total}**",
        "question_score": "**Frage {n}: {s}/{m}**",
        "result": "**Bewertung abgeschlossen** — Gesamt: {s}/{m} ({p}%) — **{verdict}**",
        "passed": "BESTANDEN",
        "failed": "Nicht bestanden",
        "correction_offer": "Du hast jetzt die Möglichkeit, deine Antwort zu ergänzen oder zu überarbeiten.",
        "summary_heading": "**Auswertung nach Themen**",
        "summary_strengths": "Stärken:",
        "summary_weaknesses": "Hier lohnt sich Wiederholung:",
        "motivational_passed": (
            "Stark gemacht. Das war keine Formalität: Du hast das Material durchgearbeitet, die Fragen "
            "beantwortet und bestanden.\n\n"
            "Managing Performance gehört zu den anspruchsvollsten Fähigkeiten, die ein HYROX-Coach "
            "entwickeln kann. Dass du dieses Modul abgeschlossen hast, zeigt, dass du dir ein Fundament "
            "aufbaust, das einen echten Unterschied macht — für deine Athletinnen und Athleten und für "
            "deine Coaching-Praxis.\n\n"
            "Das ist ein Schritt in die richtige Richtung. Nicht der letzte — aber ein bedeutender.\n\n"
            "Bleib dran. Deine Athletinnen und Athleten werden den Unterschied spüren."
        ),
        "motivational_failed": (
            "Das ist nicht das Ergebnis, das du dir erhofft hast, und es gibt keinen Grund, das "
            "schönzureden. Was zählt, ist das: Du hast das gesamte Assessment absolviert und dein Wissen "
            "auf die Probe gestellt.\n\n"
            "Managing Performance und der Schutz junger Athletinnen und Athleten gehören zum "
            "Anspruchsvollsten, was ein HYROX-Coach leistet, und nur wenige bekommen beim ersten Anlauf "
            "alles richtig. Die Lücken, die dieses Assessment sichtbar gemacht hat, sind konkret — und "
            "jede einzelne kannst du schließen.\n\n"
            "Geh die oben markierten Bereiche noch einmal durch, arbeite sie auf und tritt erneut an. Die "
            "Coaches, die den größten Unterschied machen, sind oft die, die beim ersten Mal nicht bestanden "
            "haben und drangeblieben sind. Deine Athletinnen und Athleten sind das wert."
        ),
        "closing_passed": (
            "Du kannst das Assessment jetzt schließen; dein Zertifikat wird erstellt. Bitte warte, bis du "
            "die entsprechende Benachrichtigung erhältst. Du findest das Zertifikat anschließend in der "
            "App und bekommst es zusätzlich per E-Mail."
        ),
        "closing_failed": (
            "Du kannst dieses Assessment erneut absolvieren. Geh vorher noch einmal die oben "
            "hervorgehobenen Themen durch, damit dein nächster Versuch auf dem aufbaut, was du gerade "
            "erarbeitet hast. Wenn du bereit bist, findest du die Option, das Assessment neu zu starten, in "
            "der lemon App. Nimm dir die Zeit, die du brauchst, und komm zurück, wenn du dich vorbereitet "
            "fühlst."
        ),
    },
    "nl": {
        "header": "**Vraag {n} van {total}**",
        "question_score": "**Vraag {n}: {s}/{m}**",
        "result": "**Beoordeling voltooid** — Totaal: {s}/{m} ({p}%) — **{verdict}**",
        "passed": "GESLAAGD",
        "failed": "Niet geslaagd",
        "correction_offer": "Je hebt nu de mogelijkheid om je antwoord aan te vullen of te herzien.",
        "summary_heading": "**Overzicht per thema**",
        "summary_strengths": "Sterke punten:",
        "summary_weaknesses": "Nog aandacht nodig:",
        "motivational_passed": (
            "Goed gedaan. Dit was geen formaliteit: je hebt de stof doorgewerkt, de vragen beantwoord en "
            "je bent geslaagd.\n\n"
            "Managing performance is een van de meest veeleisende vaardigheden die een HYROX-coach kan "
            "ontwikkelen. Dat je deze module hebt afgerond, betekent dat je bouwt aan een fundament dat "
            "echt verschil maakt — voor je atleten en voor je praktijk.\n\n"
            "Dit is een stap in de goede richting. Niet de laatste — maar wel een betekenisvolle.\n\n"
            "Ga zo door. Je atleten zullen het verschil voelen."
        ),
        "motivational_failed": (
            "Dit is niet het resultaat waarop je had gehoopt, en er is geen reden om het mooier te maken "
            "dan het is. Wat telt, is dit: je hebt het volledige assessment afgelegd en je kennis op het "
            "spel gezet.\n\n"
            "Managing performance en het veilig houden van jonge atleten behoren tot het zwaarste werk dat "
            "een HYROX-coach doet, en weinig mensen hebben het in één keer helemaal goed. De hiaten die dit "
            "assessment aan het licht heeft gebracht, zijn concreet — en elk daarvan kun je wegwerken.\n\n"
            "Neem de hierboven gemarkeerde onderdelen nog eens door, werk ze uit en ga er opnieuw voor. De "
            "coaches die het grootste verschil maken, zijn vaak degenen die het de eerste keer niet haalden "
            "en bleven doorgaan. Je atleten zijn dat waard."
        ),
        "closing_passed": (
            "Je kunt het assessment nu sluiten; je certificaat wordt gegenereerd. Wacht tot je de "
            "bijbehorende melding ontvangt. Je vindt het certificaat daarna in de app en ontvangt het ook "
            "per e-mail."
        ),
        "closing_failed": (
            "Je kunt dit assessment opnieuw maken. Neem van tevoren de hierboven gemarkeerde thema's nog "
            "eens door, zodat je volgende poging voortbouwt op wat je net hebt doorgewerkt. Wanneer je er "
            "klaar voor bent, vind je de optie om het assessment opnieuw te starten in de lemon app. Neem "
            "de tijd die je nodig hebt en kom terug wanneer je je voorbereid voelt."
        ),
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


def format_asked_marker(question_id: int) -> str:
    return f"[[ASKED q={question_id}]]"


def parse_asked_ids(window: str, plan_ids: list[int]) -> set[int]:
    """Pool ids the backend has already presented in this run's window (after the latest
    ``[[PLAN]]``). Filtered to the current plan so stale markers from a prior run cannot
    leak in."""
    out: set[int] = set()
    for m in ASKED_MARKER_RE.finditer(window or ""):
        attrs = _parse_attrs(m.group(1))
        q_raw = attrs.get("q")
        if q_raw is None:
            continue
        try:
            qid = int(q_raw)
        except (TypeError, ValueError):
            continue
        if qid in plan_ids:
            out.add(qid)
    return out


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


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return ""


def _latest_plan_message_index(messages: list[dict[str, Any]]) -> Optional[int]:
    last: Optional[int] = None
    for idx, msg in enumerate(messages or []):
        if isinstance(msg, dict) and msg.get("role") == "assistant" and PLAN_MARKER_RE.search(_message_text(msg)):
            last = idx
    return last


def _assistant_index_that_asked(
    messages: list[dict[str, Any]],
    start_idx: int,
    current_id: Optional[int],
) -> Optional[int]:
    """Index of the assistant message whose ``[[ASKED q=current_id]]`` marker presented the
    current question. The backend writes ``[[ASKED]]`` whenever it renders a question — on a
    standalone ask turn or chained right after the previous question's ``[[SCORE]]`` — so this
    is reliable even when the ask shares a message with a score marker."""
    if current_id is None:
        return None
    for idx in range(max(start_idx, 0), len(messages or [])):
        msg = messages[idx]
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        for m in ASKED_MARKER_RE.finditer(_message_text(msg)):
            attrs = _parse_attrs(m.group(1))
            q_raw = attrs.get("q")
            if q_raw is None:
                continue
            try:
                qid = int(q_raw)
            except (TypeError, ValueError):
                continue
            if qid == current_id:
                return idx
    return None


def _current_question_interaction(
    messages: list[dict[str, Any]],
    plan_message_index: Optional[int],
    current_id: Optional[int],
    asked_ids: set[int],
) -> dict[str, Any]:
    """Infer the current question phase from replayed roles + the backend's
    ``[[ASKED]]``/``[[SCORE]]`` markers.

    "Asked?" is a marker lookup (``current_id in asked_ids``) rather than a message-boundary
    heuristic, so it stays correct now that the next question is presented automatically in
    the same message as the previous question's score. Everything after the asking message is
    the learner working on the current question: user turns are answer/correction attempts and
    any assistant turn after the ask is the one allowed correction offer.
    """
    asked = current_id is not None and current_id in asked_ids
    if not asked:
        return {
            "current_question_asked": False,
            "latest_user_answer_pending": False,
            "answer_attempts_for_current": 0,
            "correction_or_repeat_already_sent": False,
            "must_finalize_current": False,
        }

    start_idx = plan_message_index if plan_message_index is not None else 0
    ask_idx = _assistant_index_that_asked(messages, start_idx, current_id)
    after = (messages or [])[(ask_idx + 1):] if ask_idx is not None else []

    answer_attempt_count = sum(1 for m in after if isinstance(m, dict) and m.get("role") == "user")
    correction_or_repeat_already_sent = any(
        isinstance(m, dict) and m.get("role") == "assistant" for m in after
    )

    latest = messages[-1] if messages else None
    latest_user_text = _message_text(latest) if isinstance(latest, dict) and latest.get("role") == "user" else ""
    latest_user_answer_pending = answer_attempt_count >= 1 and bool(latest_user_text)
    must_finalize = bool(
        latest_user_answer_pending
        and (
            answer_attempt_count >= 2
            or correction_or_repeat_already_sent
            or is_give_up_or_meta(latest_user_text)
        )
    )

    return {
        "current_question_asked": True,
        "latest_user_answer_pending": latest_user_answer_pending,
        "answer_attempts_for_current": answer_attempt_count,
        "correction_or_repeat_already_sent": correction_or_repeat_already_sent,
        "must_finalize_current": must_finalize,
    }


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
        "current_question_asked": False,
        "latest_user_answer_pending": False,
        "answer_attempts_for_current": 0,
        "correction_or_repeat_already_sent": False,
        "must_finalize_current": False,
    }


def derive_turn_state(messages: list[dict[str, Any]], final_content: Optional[str] = None) -> dict[str, Any]:
    """Reconstruct the authoritative assessment state for this turn from replayed history.

    A run's score window is everything after the most recent ``[[PLAN]]`` marker. A new
    session (no PLAN) starts a fresh run; a completed run is terminal in this session
    whether it passed or failed — retaking happens in the Lemon app, which launches a
    fresh session. The learner cannot restart by sending another message here.
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
    asked_ids = parse_asked_ids(window, plan_ids)
    n_scored = len(scores)
    tally = compute_tally(scores)
    plan_message_index = _latest_plan_message_index(messages)

    if n_scored >= QUESTIONS_PER_RUN:
        # A completed run is terminal in this session, pass OR fail. The learner cannot retake
        # the assessment by sending another message here; restarting happens in the Lemon app,
        # which launches a fresh session. (Mirrors the passed case; the closing copy says so.)
        return {
            "plan": plan_ids,
            "plan_is_new": False,
            "scores": scores,
            "n_scored": n_scored,
            "current_id": None,
            "tally": tally,
            "completed_passed": tally["passed"],
            "current_question_asked": False,
            "latest_user_answer_pending": False,
            "answer_attempts_for_current": 0,
            "correction_or_repeat_already_sent": False,
            "must_finalize_current": False,
        }

    interaction = _current_question_interaction(messages, plan_message_index, plan_ids[n_scored], asked_ids)
    return {
        "plan": plan_ids,
        "plan_is_new": False,
        "scores": scores,
        "n_scored": n_scored,
        "current_id": plan_ids[n_scored],
        "tally": tally,
        "completed_passed": False,
        **interaction,
    }


def build_state_injection(state: dict[str, Any], language: Optional[str] = None) -> str:
    """The system-controlled block appended to the prompt each turn. Pins the LLM to a
    single question and forbids it from producing any numbers or owning the plan."""
    total = QUESTIONS_PER_RUN
    current_id = state.get("current_id")

    if current_id is None:
        # Completed run — terminal in this session, pass OR fail. The score, verdict and closing
        # message were already rendered on the completion turn; this turn the learner has sent a
        # further message, so just acknowledge briefly and emit no marker.
        passed = bool(state.get("completed_passed"))
        outcome = "passed" if passed else "did NOT pass"
        return (
            "\n\n## CURRENT TURN STATE (system-controlled — obey exactly)\n"
            f"- All {total} questions are finalised and the learner {outcome}. The assessment is over and "
            "cannot be retaken in this session. Do NOT ask any further question and do NOT emit any marker.\n"
            "- Briefly acknowledge that the assessment is complete; if they want another attempt, tell them "
            "they can restart it from the Lemon app. The system already rendered the final score and verdict.\n"
        )

    n = state.get("n_scored", 0)
    kpc = key_point_count(current_id)
    cap = max_points(current_id)
    cat = category_of(current_id)
    question_text = render_question_text(current_id)
    is_last = (n == total - 1)
    is_first_of_run = (n == 0)

    lines = [
        "\n\n## CURRENT TURN STATE (system-controlled — authoritative; overrides any conflicting instruction)",
        f"- Questions finalised so far this run: {n} of {total}.",
        f"- The ONLY question you may handle this turn is pool question #{current_id} "
        f"(category: {cat}); it has {kpc} required key points and a maximum of {cap} points.",
        f"- Authoritative visible question text for this pool question: {question_text}",
    ]
    if not state.get("current_question_asked"):
        lines.append(
            f"- CURRENT ACTION: ASK question #{current_id} now. Put only [[ASK]] on its own line at the point "
            "where the question should appear. Do NOT write, rephrase, translate, or add any visible question "
            "text yourself; the backend replaces [[ASK]] with the exact authoritative question text above. "
            "Never reveal the pool number, category, point values, or rubric."
        )
    elif state.get("latest_user_answer_pending"):
        attempts = int(state.get("answer_attempts_for_current", 0) or 0)
        lines.extend(
            [
                f"- CURRENT ACTION: GRADE the learner's latest message for question #{current_id}. This question "
                "has already been asked in the conversation. You MUST NOT repeat it, MUST NOT ask it again, and "
                "MUST NOT use [[ASK]] in this response.",
                "- Use all learner attempts for this current question that appear after it was asked; if they "
                "revised, keep the better per-key-point verdict across attempts.",
            ]
        )
        if state.get("must_finalize_current"):
            lines.append(
                "- FINALISE NOW: the learner has already had a correction/repeat turn or has declined/given up/"
                "objected to the repeat. End this response with EXACTLY one [[SCORE]] marker for the current "
                "question. Ask no question of any kind."
            )
        else:
            lines.append(
                "- DECISION: if this first attempt earns FULL marks, finalise now with the [[SCORE]] marker. If it is "
                "NOT full marks, you MUST offer the single correction opportunity and MUST NOT finalise this turn: do "
                "NOT emit a [[SCORE]] marker. Phrase it only as a short statement telling them they may add to or "
                "revise their answer now; do NOT ask a yes/no question, do NOT repeat the original question, and do "
                "NOT use [[ASK]]. The system finalises automatically on the next turn once this one correction is used "
                "or declined."
            )
        lines.append(f"- Learner answer attempts seen for this current question: {attempts}.")
    else:
        lines.append(
            f"- CURRENT ACTION: continue the in-progress handling of question #{current_id}. It has already been "
            "asked, so do NOT repeat the original question and do NOT use [[ASK]] unless the system state later "
            "says the next question has not been asked."
        )
    lines.extend(
        [
            "- When the question is finalised, end your message with EXACTLY one marker on its own line:",
            f'  [[SCORE q={current_id} points="<{kpc} comma-separated values, one 0 or 1 per key point in listed '
            f'order>" max={cap} cat="{cat}"]]',
            "- Award 1 for each key point the learner demonstrated and 0 otherwise (apply the safeguarding "
            "critical-fail rule). The system sums these values — your job is the per-point judgement only.",
            "- Write NO numbers anywhere (no question number, per-question score, running total, percentage, or "
            "pass/fail). Place [[ASK]] ONLY on a message where you actually ask a not-yet-asked question — never "
            "on a feedback, correction-offer, or finalisation/score-only message. Repeating the original question "
            "after any learner answer is invalid; if uncertain, finalise conservatively instead of asking it again. "
            f'The system replaces [[ASK]] with the correct "Question N of {total}" header and exact question text, '
            "shows each question's score when it is graded, and shows the cumulative result only at the end. Never "
            "emit [[PLAN]] or [[RESULT]]; the system owns those.",
        ]
    )
    if not is_last:
        lines.append(
            "- AUTO-NEXT: after you finalise (emit the [[SCORE]] marker), the system AUTOMATICALLY presents the "
            "next question in this SAME message — the learner does not have to ask for it and there is no separate "
            "turn. So on a finalisation message do NOT write the next question and do NOT use [[ASK]]; you may add at "
            "most one short, natural lead-in sentence into the next question (no question text, no numbers)."
        )
    if is_first_of_run:
        lines.append(
            "- This is the first question of the run. The learner has ALREADY been shown a full welcome and the "
            "assessment rules (20 questions, free-text answers, one correction each, 80% overall to pass, a topic "
            'summary at the end) and has just typed "start" to begin. Do NOT write any intro, welcome, greeting, '
            "rules recap, or other preamble — begin immediately with the question. Output only [[ASK]] on its own "
            "line with no other text before it."
        )
    if is_last:
        lines.append(
            "- This is the final planned question: after finalising it, write your brief feedback on this final "
            "answer, then a line containing exactly [[SUMMARY]], then ALWAYS — whether the learner did well or "
            "not — give TAKE-AWAYS by topic for the categories that appeared: in plain language, name 2-4 topics "
            "that felt like strengths and 2-4 that need work, specific to what the learner showed, framed as "
            "guidance, without dumping model answers and without any numbers. Ask nothing further. The system "
            "renders the final score, the verdict, and the closing messages, each as its own section."
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


# Defense in depth against the model writing visible question text. The backend renders every
# question itself; the model is told to write none. The [[ASK]] suffix-discard only guards ask
# turns — on a finalisation/chain turn a model that leaks a (possibly reworded) pool question as a
# stray paragraph would surface it right before the backend's own next question (observed: after
# finalising one question the model emitted a reworded "...four age groups..." question as its own
# paragraph, which then displayed just above the real next question). We strip any model paragraph
# that reproduces a pool question, matched by the single longest contiguous run it shares with a
# pool question (so a light rewording — "What are the four age groups..." vs the pooled "Describe
# the four age groups..." — is still caught, while unrelated feedback, which shares no long run with
# any question, is kept).
_LEAKED_QUESTION_MATCH_THRESHOLD = 0.8
_MIN_QUESTION_MATCH_CHARS = 40
_PARAGRAPH_SPLIT_RE = re.compile(r"\n[ \t]*\n")


def _normalize_for_match(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


_NORMALIZED_POOL_QUESTIONS: list[str] = [_normalize_for_match(q["question"]) for q in QUESTIONS]


def paragraph_reproduces_pool_question(paragraph: str) -> bool:
    """True when ``paragraph`` reproduces one of the pool questions — verbatim or lightly reworded.
    Compares the single longest contiguous run shared with each pool question against that
    question's length, so a leaked question keeps matching when only its opening words are changed,
    while ordinary feedback (which shares no long run with any question) does not match."""
    p = _normalize_for_match(paragraph)
    if not p:
        return False
    for q in _NORMALIZED_POOL_QUESTIONS:
        if len(q) < _MIN_QUESTION_MATCH_CHARS:
            continue
        longest = difflib.SequenceMatcher(None, q, p).find_longest_match(0, len(q), 0, len(p))
        if longest.size / len(q) >= _LEAKED_QUESTION_MATCH_THRESHOLD:
            return True
    return False


def strip_leaked_question_text(text: Optional[str]) -> str:
    """Drop any model-authored paragraph that reproduces a pool question (see
    ``paragraph_reproduces_pool_question``). The backend owns every visible question, so such a
    paragraph is always a leak, never legitimate feedback. Paragraphs containing a control marker
    are preserved untouched so [[SCORE]]/[[ASK]]/[[SUMMARY]] still replay."""
    if not text:
        return text or ""
    kept: list[str] = []
    for paragraph in _PARAGRAPH_SPLIT_RE.split(text):
        if ANY_MARKER_RE.search(paragraph) or not paragraph_reproduces_pool_question(paragraph):
            kept.append(paragraph)
    cleaned = "\n\n".join(kept)
    cleaned = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", cleaned)
    return cleaned.strip()


def render_progress_header(n_scored_after: int, language: Optional[str] = None) -> str:
    L = _locale(language)
    return L["header"].format(n=n_scored_after + 1, total=QUESTIONS_PER_RUN)


def render_question_text(question_id: Optional[int]) -> str:
    if question_id is None:
        return ""
    question = get_question(question_id)
    return str(question.get("question", "")).strip() if question else ""


def render_question_block(n_scored_after: int, question_id: Optional[int], language: Optional[str] = None) -> str:
    question_text = render_question_text(question_id)
    if not question_text:
        return render_progress_header(n_scored_after, language)
    return f"{render_progress_header(n_scored_after, language)}\n{question_text}"


def render_question_score(position: int, awarded: int, maximum: int, language: Optional[str] = None) -> str:
    """The score for a single question, shown once that question is graded (e.g. "Question 1: 4/6")."""
    L = _locale(language)
    return L["question_score"].format(n=position, s=awarded, m=maximum)


def render_final_result(tally: dict[str, Any], language: Optional[str] = None) -> str:
    L = _locale(language)
    verdict = L["passed"] if tally["passed"] else L["failed"]
    return L["result"].format(s=tally["score"], m=tally["max"], p=tally["pct"], verdict=verdict)


def render_summary_fallback(scores: list[dict[str, Any]], language: Optional[str] = None) -> str:
    """Deterministic strengths/needs-work topic summary from the authoritative category
    breakdown — used only when the model fails to emit its [[SUMMARY]] section on the
    final turn, so the learner always gets the promised per-topic summary."""
    L = _locale(language)
    strengths: list[str] = []
    weaknesses: list[str] = []
    for cat, bucket in category_breakdown(scores).items():
        if not bucket["max"]:
            continue
        if 100 * bucket["awarded"] / bucket["max"] >= PASS_THRESHOLD_PERCENT:
            strengths.append(cat)
        else:
            weaknesses.append(cat)
    blocks = [L["summary_heading"]]
    if strengths:
        blocks.append(L["summary_strengths"] + "\n" + "\n".join(f"- {cat}" for cat in strengths))
    if weaknesses:
        blocks.append(L["summary_weaknesses"] + "\n" + "\n".join(f"- {cat}" for cat in weaknesses))
    return "\n\n".join(blocks)


def render_completion_bubbles(
    body: str,
    score_line: str,
    scores: list[dict[str, Any]],
    tally: dict[str, Any],
    language: Optional[str] = None,
) -> str:
    """Assemble the end-of-assessment message as [[BREAK]]-separated display bubbles:

    1. the final question's score + the model's feedback on that answer,
    2. the cumulative result + verdict (backend-rendered),
    3. the strengths/needs-work topic summary — the model's text after its [[SUMMARY]]
       token, or the deterministic fallback when that token is missing (rendered in BOTH
       the pass and the fail case),
    4. the motivational message (pass/fail variant),
    5. the closing message (pass: certificate notice; fail: retake-via-Lemon-app note).

    The frontend renders one chat bubble per section while the stored message keeps the
    full content, so history replay and state re-derivation are unaffected. The model's
    hidden [[SCORE]] marker is re-appended at the very end so it still replays.
    """
    L = _locale(language)

    score_marker = SCORE_MARKER_RE.search(body)
    score_marker_text = score_marker.group(0) if score_marker else ""
    cleaned = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", SCORE_MARKER_RE.sub("", body)).strip()

    feedback, *summary_rest = SUMMARY_TOKEN_RE.split(cleaned, maxsplit=1)
    feedback = feedback.strip()
    summary = SUMMARY_TOKEN_RE.sub("", summary_rest[0]).strip() if summary_rest else ""
    if not summary:
        summary = render_summary_fallback(scores, language)

    passed = bool(tally["passed"])
    bubbles = [
        "\n\n".join(part for part in (score_line, feedback) if part),
        render_final_result(tally, language),
        summary,
        L["motivational_passed"] if passed else L["motivational_failed"],
        L["closing_passed"] if passed else L["closing_failed"],
    ]
    assembled = BUBBLE_BREAK_SEPARATOR.join(bubble for bubble in bubbles if bubble)
    if score_marker_text:
        assembled = f"{assembled}\n\n{score_marker_text}"
    return assembled


def render_assessment_turn(
    content: Optional[str],
    state: dict[str, Any],
    language: Optional[str] = None,
) -> tuple[str, list[dict[str, Any]], dict[str, Any], bool]:
    """Post-process one assistant message:

    * strip any numbers the model wrote (defense in depth),
    * strip any pool question the model leaked as a stray paragraph (verbatim or lightly
      reworded), since the backend renders every visible question itself,
    * replace the model's ``[[ASK]]`` placement token with the authoritative
      "Question N of 20" header and exact pinned question text from ``questions.py``
      (discarding any model-written question text after the token),
    * when a question is finalised this turn, show that single question's score,
    * when a question is finalised and it is not the last, **chain the next pinned
      question into the same message** (header + exact text) so the learner is never
      forced to type "next",
    * at the very end (final question), assemble the [[BREAK]]-separated bubble
      sequence via ``render_completion_bubbles``: final question's score + feedback,
      cumulative total + pass/fail, topic summary (both pass and fail), motivational
      message, and closing message,
    * keep the hidden [[SCORE]] markers so they replay, append the backend-authored
      [[PLAN]] marker on a fresh run, and append a hidden [[ASKED]] marker for whatever
      question the backend presented this turn.

    There is intentionally NO running cumulative total mid-assessment — only the
    per-question score when graded and the final cumulative result.

    Returns ``(content, all_scores, tally, just_completed)``.
    """
    body = strip_rendered_numbers(content)
    # Drop any pool question the model leaked as free text. Runs before the backend inserts its own
    # authoritative question below, so only the model's text is affected — never the rendered one.
    body = strip_leaked_question_text(body)

    new_score = parse_new_score(content, state.get("current_id"))

    # Backend guard against premature finalisation (defence in depth for the hardened
    # state-block instruction). On a genuine first attempt — GRADE_FIRST: a learner answer is
    # pending and finalisation is NOT yet forced — the model may finalise ONLY on full marks;
    # otherwise the single correction must be offered first. If the model emits a below-full-
    # marks [[SCORE]] here anyway, discard that score, strip its marker so a later replay cannot
    # count it, and hold the question open with a correction offer so the learner still gets
    # their one revise/add opportunity. This makes the "scored partial with no chance to revise"
    # case unreachable regardless of whether the model obeys the prompt. (Full-marks first
    # answers and forced finalisations — GRADE_FINAL, e.g. a second attempt or an explicit
    # give-up — are unaffected: those set must_finalize_current and are accepted normally.)
    score_discarded_premature = False
    is_grade_first = bool(
        state.get("latest_user_answer_pending") and not state.get("must_finalize_current")
    )
    if (
        new_score is not None
        and is_grade_first
        and int(new_score.get("awarded", 0) or 0) < int(new_score.get("max", 0) or 0)
    ):
        new_score = None
        body = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", SCORE_MARKER_RE.sub("", body)).strip()
        score_discarded_premature = True

    all_scores = list(state.get("scores", []))
    if new_score is not None:
        all_scores = [s for s in all_scores if s["q"] != new_score["q"]] + [new_score]
    tally = compute_tally(all_scores)
    n_after = len(all_scores)
    just_completed = new_score is not None and n_after >= QUESTIONS_PER_RUN
    plan = state.get("plan") or []

    # The pool question the BACKEND renders (asks) this turn, if any. It is recorded with a
    # hidden [[ASKED]] marker so the next stateless turn knows it was already presented —
    # whether asked standalone or chained right after the previous question's score.
    asked_question_id: Optional[int] = None

    # On ask turns, the model is only trusted to place [[ASK]], not to write the visible
    # question text. If it writes a wrong/rephrased question after [[ASK]], discard that
    # suffix and render the backend-pinned text instead. If it forgets [[ASK]] on a fresh
    # ask turn, still render the pinned question rather than exposing model-authored text.
    should_backend_render_question = (
        new_score is None
        and n_after < QUESTIONS_PER_RUN
        and state.get("current_id") is not None
        and not state.get("current_question_asked")
    )
    if should_backend_render_question:
        asked_question_id = state.get("current_id")
        question_block = render_question_block(n_after, asked_question_id, language)
        ask_match = ASK_TOKEN_RE.search(body)
        if ask_match:
            prefix = body[: ask_match.start()].strip()
            body = "\n\n".join(p for p in (prefix, question_block) if p)
        else:
            body = question_block
    body = ASK_TOKEN_RE.sub("", body)  # remove any stray/extra token

    if just_completed and new_score is not None:
        # End of the run: assemble the [[BREAK]]-separated bubble sequence (final question's
        # score + feedback, cumulative verdict, topic summary, motivational message, closing).
        score_line = render_question_score(n_after, new_score["awarded"], new_score["max"], language)
        assembled = render_completion_bubbles(body, score_line, all_scores, tally, language)
    else:
        parts: list[str] = []
        if new_score is not None:
            # The just-graded question's run position is n_after (it is the latest finalised one).
            parts.append(render_question_score(n_after, new_score["awarded"], new_score["max"], language))
        if body:
            parts.append(body)
        if score_discarded_premature:
            # The model finalised a partial first answer; we discarded that score above. Append an
            # explicit one-correction invitation so the held question reads as a revise prompt even
            # if the model's own feedback did not invite a revision. Position is intentionally held:
            # no score, no chain, no [[ASKED]] — the next turn forces finalisation (must_finalize).
            parts.append(_locale(language)["correction_offer"])

        # Chain: after finalising a question that is not the last, present the next pinned
        # question automatically in this same message. The progress header uses n_after (already
        # incremented by the new score), so it reads as the next question's number.
        if new_score is not None and n_after < len(plan):
            next_id = plan[n_after]
            asked_question_id = next_id
            parts.append(render_question_block(n_after, next_id, language))

        assembled = "\n\n".join(p for p in parts if p)

    trailing: list[str] = []
    if state.get("plan_is_new") and state.get("plan"):
        trailing.append(format_plan_marker(state["plan"]))
    if asked_question_id is not None:
        trailing.append(format_asked_marker(asked_question_id))
    # On ANY completion (pass OR fail), emit the hidden completion marker. The frontend hides it at
    # render and uses it to remove the question input, since the run is terminal in this session
    # either way. Gated on just_completed (true only on the turn the final question is graded), so
    # it fires exactly once per run; carries no [[BREAK]], so the visible bubble structure is
    # unchanged. Unlike the pass-only PROGRESS marker below, this is present for both outcomes.
    if just_completed:
        trailing.append(DONE_MARKER)
    # On a passed completion only, hand the result back to the Lemon app. Hidden marker the
    # frontend turns into lemon://save_progress?value=100. It is gated on just_completed, which is
    # only true on the turn the final question is graded, so this fires exactly once per run.
    if just_completed and tally.get("passed"):
        trailing.append(PROGRESS_MARKER)
    if trailing:
        assembled = (assembled + "\n\n" + "\n".join(trailing)).strip()

    return assembled, all_scores, tally, just_completed


# --- result recording + LMS stub ------------------------------------------------------
def build_result_payload(
    *,
    session_id: Optional[str],
    user_id: Optional[str],
    language: Optional[str],
    tally: dict[str, Any],
    scores: list[dict[str, Any]],
    account_id: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
) -> dict[str, Any]:
    """Build the result payload the LMS will consume (pass→certificate). The Lemon learner
    identity (``account_id``/``first_name``/``last_name``) arrives on the launch URL and is
    recorded so the result is attributable to a specific learner."""
    return {
        "session_id": session_id,
        "user_id": user_id,
        "account_id": account_id,
        "first_name": first_name,
        "last_name": last_name,
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
        account_id = overrides.get("account_id")
        user_id = auth_claims.get("oid") or account_id or overrides.get("user")
        language = overrides.get("language")

        payload = build_result_payload(
            session_id=session_id,
            user_id=user_id,
            language=language,
            tally=tally,
            scores=scores,
            account_id=account_id,
            first_name=overrides.get("first_name"),
            last_name=overrides.get("last_name"),
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
