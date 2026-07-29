"""Deterministic state engine, session log, and LMS-reporting stub for the HYROX Level 2 assessment.

The assessment is **backend-driven and stateless**, and runs **module by module**. On every turn the
backend reconstructs authoritative state from hidden control markers that persist in the replayed
conversation history (the frontend hides them at render but keeps them in the stored message, so they
replay into the next request):

* ``[[PLAN modules=...]]`` — the run anchor. **Backend-authored** on the first turn; its presence marks
  that a run has begun (a fresh session with no PLAN starts over). Encodes the fixed module order.
* ``[[MODULE m=M3 attempt=2]]`` — **backend-authored** when a module attempt's first question is
  presented. The current module + attempt is the latest such marker; everything after it is that
  attempt's window, so a failed attempt's scores never pollute the retake.
* ``[[ASKED q=K]]`` — **backend-authored** record that pool question K was presented this turn.
* ``[[SCORE q=K points="1,1,0,1" max=Y mod="M3"]]`` — emitted by the model when it finalises question
  K. The model supplies only the **per-key-point 0/1 verdict**; the backend computes
  ``awarded = min(sum(points), max_pts)`` from ``questions.py`` (the authoritative rubric), validates the
  array length, and forces ``q`` to the pinned id.
* ``[[MODPASS m=M3]]`` / ``[[MODFAIL m=M3]]`` — **backend-authored** at a module attempt's end. They
  drive the frontend Continue/Retry buttons and the backend's "awaiting continue/retry" state.
* ``[[PROGRESS value=100]]`` + ``[[DONE]]`` — **backend-authored** on the FINAL module's pass only
  (the whole assessment is complete). The frontend turns PROGRESS into ``lemon://save_progress?value=100``
  and uses DONE to remove the input. Because a module is only ever left by passing it, finishing the
  assessment always means passing every module — completion is sent once, after the last module.

The backend owns the per-module question counter, the running module tally, the per-module pass/fail at
an 80% threshold, and the module transitions — it renders all of these into the message itself
(``render_*``) so the model can neither miscount nor mis-add. ``record_assessment_session`` upserts one
session log blob per session on EVERY turn (so abandoned runs are recorded too) and calls the LMS stub
when the final module is passed.

Backend-authored markers the model fakes anyway are STRIPPED from its output before assembly
(``strip_forbidden_model_markers``), and the model's ``[[SCORE]]`` is stored in canonical backend form
(``format_score_marker``) — otherwise a fake ``[[MODPASS]]``/wrong ``q`` attribute persists into replayed
history and corrupts the derived state (see the regex comments above each).
"""

import difflib
import json
import logging
import re
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Optional

from approaches.chatbots.hyrox_assessment.questions import (
    MODULES,
    QUESTIONS,
    TOTAL_MAX_POINTS,
    TOTAL_QUESTIONS,
    get_question,
    is_last_module,
    key_point_count,
    max_points,
    module_index,
    module_of,
    module_questions,
    next_module,
)

logger = logging.getLogger("hyrox_assessment")

PASS_THRESHOLD_PERCENT = 80

# Hidden control markers. Kept permissive (case-insensitive, tolerant of spacing).
PLAN_MARKER_RE = re.compile(r"\[\[\s*PLAN\b([^\]]*)\]\]", re.IGNORECASE)
MODULE_MARKER_RE = re.compile(r"\[\[\s*MODULE\b([^\]]*)\]\]", re.IGNORECASE)
SCORE_MARKER_RE = re.compile(r"\[\[\s*SCORE\b([^\]]*)\]\]", re.IGNORECASE)
ASKED_MARKER_RE = re.compile(r"\[\[\s*ASKED\b([^\]]*)\]\]", re.IGNORECASE)
MODPASS_MARKER_RE = re.compile(r"\[\[\s*MODPASS\b([^\]]*)\]\]", re.IGNORECASE)
MODFAIL_MARKER_RE = re.compile(r"\[\[\s*MODFAIL\b([^\]]*)\]\]", re.IGNORECASE)
# The PINNED first-attempt verdict: backend-authored when the learner's first answer to a question is below
# full marks and the single correction is offered. It records the model's own per-key-point judgement of that
# answer WITHOUT finalising the question (the counter does not advance), so the judgement cannot drift on a
# later turn. Before 2026-07-28 that verdict was simply discarded, and when the learner declined the
# correction the model re-graded the same unchanged answer from scratch — in production it came back at FULL
# marks one turn after stating a key part was missing, awarding points the learner never earned. Now the
# decline path finalises from this marker and the model's fresh verdict is ignored; a genuine revision
# finalises at the per-key-point best of the two (see merge_best_verdicts).
PROV_MARKER_RE = re.compile(r"\[\[\s*PROV\b([^\]]*)\]\]", re.IGNORECASE)
# ASKED before ASK, MODPASS/MODFAIL before MODULE, so the `\b` boundary matches the longer name first.
ANY_MARKER_RE = re.compile(
    r"\[\[\s*(?:PLAN|MODULE|SCORE|PROV|ASKED|ASK|MODPASS|MODFAIL|SUMMARY|BREAK|PROGRESS|DONE)\b[^\]]*\]\]",
    re.IGNORECASE,
)
# Markers only the BACKEND may author. The prompt forbids the model from writing them, but a drifting
# model imitates the module-boundary messages it sees replayed in history — markers included (observed in
# production session logs at roughly 8% of module boundaries). Before 2026-07-17 these fakes were only
# hidden at display and persisted into stored history, where a fake [[MODPASS]] in the FINAL module's
# window stranded the whole run (derive_turn_state read it as "final module passed" and went terminal
# without ever rendering the completion sequence or the LMS [[PROGRESS]] hand-off), and a fake [[MODPASS]]
# beside the real [[MODFAIL]] could advance a learner past a failed module. render_assessment_turn now
# strips them from the model's output before assembly so stored history stays backend-authored-only.
# [[SCORE]]/[[ASK]]/[[SUMMARY]] are the model's own channels and are handled separately.
FORBIDDEN_MODEL_MARKER_RE = re.compile(
    r"\[\[\s*(?:PLAN|MODULE|MODPASS|MODFAIL|PROGRESS|DONE|ASKED|BREAK|PROV)\b[^\]]*\]\]",
    re.IGNORECASE,
)
# Backend-authored, hidden: emitted once on the FINAL module's pass to hand the result back to the
# Lemon app. The frontend hides it at render and fires lemon://save_progress?value=N. Never emitted on a
# module pass that is not the last module, and never on a module fail.
PROGRESS_PASS_VALUE = 100
PROGRESS_MARKER = f"[[PROGRESS value={PROGRESS_PASS_VALUE}]]"
# Backend-authored, hidden: emitted once on final completion (the last module passed). The frontend hides
# it at render and uses it to remove the question input, since the run is then terminal in this session.
DONE_MARKER = "[[DONE]]"
# The model writes [[SUMMARY]] once, on the finalising turn of the FINAL question, between its feedback on
# that answer and its general end-of-assessment take-aways (a few strengths + a few worth revisiting,
# across all modules). render_completion_bubbles splits there so the model's take-aways become the summary
# bubble, falling back to the deterministic render_topic_summary when the model omits it. The
# premature-finalisation guard also cuts it if the model emits it on a partial first answer (before the one
# correction is used), so it can never leak early or stall the correction loop; ANY_MARKER_RE additionally
# display-hides the token from stored sessions.
SUMMARY_TOKEN_RE = re.compile(r"\[\[\s*SUMMARY\s*\]\]", re.IGNORECASE)
DONE_MARKER_RE = re.compile(r"\[\[\s*DONE\s*\]\]", re.IGNORECASE)
# Backend-authored display split point: the frontend renders one chat bubble per [[BREAK]]-separated
# section while storing the full message, so replay is unaffected.
BUBBLE_BREAK_TOKEN = "[[BREAK]]"
BUBBLE_BREAK_SEPARATOR = f"\n\n{BUBBLE_BREAK_TOKEN}\n\n"
# Placement token the model writes when a question should be asked; the backend replaces it with the
# localized "Question N of M" header plus the exact pinned question text from questions.py.
ASK_TOKEN_RE = re.compile(r"\[\[\s*ASK\s*\]\]", re.IGNORECASE)

# Lines the model is told NOT to write (the backend renders them) — stripped as defense in depth so a
# stray model-written header/total can never duplicate or contradict ours.
#
# Every pattern below allows a leading "noise" prefix before the line's real content: a markdown list
# bullet, a heading marker, a blockquote arrow, an emoji, or any run of such symbols. Without it a single
# decorative character defeated the whole-line anchor — "### Module 10 complete — 25/25 (100%). Passed."
# and "✅ **Module 10 complete — …**" both sailed through untouched, which is how a learner came to see a
# model-fabricated "Module 10 complete" bubble while the backend rendered nothing (reported 2026-07-29).
# `*` is excluded from the noise class so the explicit `\*{0,2}` bold handling still applies after it.
_LEAD = r"[ \t]*(?:[^\w\s*][ \t]*)*"
_HEADER_LINE_RE = re.compile(
    rf"^{_LEAD}\*{{0,2}}\s*(?:Question|Frage|Vraag)\s+\d+\s+(?:of|von|van)\s+\d+\s*\*{{0,2}}\s*$",
    re.IGNORECASE | re.MULTILINE,
)
# The per-question score line the backend renders after grading ("**Question 2: 4/4**"). Until 2026-07-28
# this was the ONE backend-rendered line shape with no strip rule — and it is the shape the model sees
# replayed most often — so an imitation of it survived untouched and the backend then prepended its own
# copy, printing "**Question 2: 4/4**" twice in the same bubble (confirmed in four production session
# logs). Anchored to the WHOLE line, so ordinary feedback that mentions a fraction mid-sentence
# ("you covered 2/3 of the factors") is never touched.
_SCORE_FRACTION = r"\d+\s*(?:/|of|out of|von|aus|van|uit)\s*\d+"
_QUESTION_SCORE_LINE_RE = re.compile(
    rf"^{_LEAD}\*{{0,2}}\s*(?:Question|Frage|Vraag)\s*\d+\s*\*{{0,2}}\s*[:–—-]\s*\*{{0,2}}\s*"
    rf"{_SCORE_FRACTION}\s*(?:points?|punkte|punten|pts?)?\s*\*{{0,2}}\s*[.!]?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
# A label-less score line ("**4/4**", "Score: 4 out of 4", "5/5 points"). The model is told to write no
# numbers at all, so a line whose ENTIRE content is a score fraction can only be an imitation of a
# backend-rendered number; a fraction inside a sentence is left alone.
_BARE_SCORE_LINE_RE = re.compile(
    rf"^{_LEAD}\*{{0,2}}\s*(?:score|punktestand|punkte|punten)?\s*:?\s*\*{{0,2}}\s*{_SCORE_FRACTION}"
    rf"\s*(?:points?|punkte|punten|pts?)?\s*\*{{0,2}}\s*[.!]?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_TOTAL_LINE_RE = re.compile(
    rf"^{_LEAD}\*{{0,2}}\s*(?:Score so far|Punktestand|Stand|Gesamtpunkte|Totaal|Total)\b[^\n]*\d+\s*/\s*\d+[^\n]*$",
    re.IGNORECASE | re.MULTILINE,
)
_COMPLETE_LINE_RE = re.compile(
    rf"^{_LEAD}\*{{0,2}}\s*(?:Assessment complete|Module(?:\s+[\d.]+)?\s+complete|Modul(?:\s+[\d.]+)?\s+abgeschlossen"
    r"|Bewertung abgeschlossen|Module(?:\s+[\d.]+)?\s+voltooid|Beoordeling voltooid)\b[^\n]*$",
    re.IGNORECASE | re.MULTILINE,
)
# A model-faked module-result line in the backend's own format ("**Module 7.4 — 13/17 (76%). Passed.**"):
# a line that OPENS with the module word + number and carries a points fraction is always an imitation —
# the backend renders its own result line after stripping, so it can never be caught here. (The optional
# module number in _COMPLETE_LINE_RE covers the fraction-less variant "Module 10 complete — Passed.")
_MODULE_RESULT_LINE_RE = re.compile(
    rf"^{_LEAD}\*{{0,2}}\s*Modul(?:e)?\s+[\d.]+\b[^\n]*?\d+\s*/\s*\d+[^\n]*$",
    re.IGNORECASE | re.MULTILINE,
)
# The bare module heading the backend renders above a module's first question ("**Module 7.1**"). Like the
# score line, it is a backend-owned line the model has no reason to write, so a whole line consisting only
# of it is an imitation; a module mentioned inside a sentence is ordinary prose and is left alone.
_MODULE_HEADING_LINE_RE = re.compile(
    rf"^{_LEAD}\*{{0,2}}\s*Modul(?:e)?\s+[\d.]+\s*\*{{0,2}}\s*[:.]?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

def ending_cut_index(text: Optional[str]) -> Optional[int]:
    """Index of the ``[[SUMMARY]]`` token in ``text`` — the model's contract marker that introduces
    end-of-assessment take-aways — or None if it is absent. Both premature-ending guards use it to cut a
    summary the model volunteered on a turn that is not the true final-module completion.

    Detection keys ONLY on ``[[SUMMARY]]``: it is the one signal that never appears in ordinary per-question
    feedback, so cutting on it has ZERO false positives. An earlier iteration also tried to catch a
    *token-less* ending by Strengths/Worth-revisiting labels and completion phrases, but adversarial review
    proved that shape is indistinguishable from legitimate feedback (e.g. "Strengths: … / one point worth
    improving …", or "your understanding of assessment is complete") and erased real learner feedback —
    a worse failure than the rare leak it prevented, since no keyword rule can separate a summary from
    feedback that merely uses the same words. A contract-violating token-less prose summary is the documented
    residual the prompt covers: the model is told to precede ANY take-aways with ``[[SUMMARY]]`` and to write
    none at all except when finalising the final module's last question."""
    if not text:
        return None
    token = SUMMARY_TOKEN_RE.search(text)
    return token.start() if token else None


def cut_premature_ending(body: Optional[str]) -> str:
    """Remove an end-of-assessment take-aways/summary section the model volunteered on a turn that is NOT
    the genuine final-module completion, while preserving a trailing ``[[SCORE]]`` marker so a legitimately
    finalised score still replays into history.

    The end-of-assessment take-aways may appear ONLY on the finalising turn of the FINAL module's last
    question, where ``render_completion_bubbles`` consumes them. On every other turn — including a
    full-marks or post-correction finalisation of a *non-final* question — a summary the model writes is
    premature and must be cut, or it leaks into the visible per-question feedback (the reported Module-10
    bug, where a full-marks answer on a non-final question dragged the whole ending into its feedback). This
    complements the below-full premature-finalisation guard, which additionally *discards* the score; here
    the score is kept because the answer legitimately finalised — only the ending is early.

    Detection reuses ``ending_cut_index`` — the ``[[SUMMARY]]`` token only — so ordinary per-question
    feedback (which never contains that token) is never truncated.
    """
    if not body:
        return body or ""
    cut = ending_cut_index(body)
    if cut is None:
        return body
    score_marker = SCORE_MARKER_RE.search(body)
    trimmed = body[:cut]
    # The model writes the [[SCORE]] marker last, after any ending; if it sits past the cut point, re-append
    # it so the finalised score is not lost together with the stripped take-aways.
    if score_marker and score_marker.start() >= cut:
        trimmed = f"{trimmed}\n\n{score_marker.group(0)}"
    return re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", trimmed).strip()

# Give-up / meta detection. A give-up or meta turn ("next", "skip", "I don't know", "why are you
# asking?") is one whose WHOLE message is that statement. A substantive answer can incidentally contain
# a trigger word and must NEVER be mistaken for giving up, because that wrongly forces finalisation and
# skips the learner's one correction. So instead of a substring search we anchor a full-message match
# (modulo trivial wrappers), so the trigger word must BE the message, not merely appear in it.
_GIVE_UP_FILLER = (
    r"ok(?:ay)?|well|um+|uh+|hmm+|so|just|please|sorry|thanks|thank you|yeah|yep|hey|hi|hello|"
    r"i guess|maybe|honestly|lets|can we"
)
_GIVE_UP_CORE = (
    r"i dont know(?: it| this| that| the answer| this one| that one)?|"
    r"i do not know(?: it| this| that| the answer| this one| that one)?|"
    r"dont know|do not know|no idea|no clue|not sure|"
    # Short/colloquial "I don't know" forms. "idk" was missing until 2026-07-29, and that single gap is
    # what produced the reported blank bubble: the backend counted it as a real answer attempt, while the
    # model correctly read it as a refusal and — as the prompt instructs for a refusal — wrote nothing at
    # all, so NEITHER side authored the turn. Any spelling the learner actually uses has to be here.
    r"idk|idc|dunno|i dunno|no answer|cant answer|cannot answer|"
    r"(?:i )?(?:have|got) no (?:idea|clue)|(?:i )?havent (?:a|any) (?:idea|clue)|not a clue|beats me|"
    r"skip(?: it| this| this one| the question)?|"
    r"move on|next(?: question| one)?|i pass|ill pass|pass|"
    r"already answered(?: it| this)?|answered (?:it|this)(?: already)?|"
    r"why (?:are|do) you ask(?:ing)?(?: me)?(?: this)?(?: again)?|"
    r"same question(?: again)?|asking again|"
    # Bare refusals / "nothing to add". NOT valid answers: every pool question is open-ended
    # ("What…", "Describe…", "Why…", "Name…") — none is yes/no-shaped, so a whole message of "no" can only
    # be a refusal. A production learner answered "no" and was awarded FULL marks; a refusal must never earn
    # a point, and it must not be mistaken for a revision either.
    r"no|nope|nah|naw|no thanks|no thank you|not really|"
    r"nothing(?: else| more| to add)?|no more|thats all|thats it|im good|im done|done|"
    r"cant remember|dont remember|cannot remember|do not remember|"
    r"nein|nichts(?: mehr)?|keine(?: ergänzung| ergänzungen| angabe)?|fertig|"
    r"nee|niets(?: meer)?|geen|klaar|"
    r"ich weiss(?: es)? nicht|ich weiß(?: es)? nicht|weiss nicht|weiß nicht|keine ahnung|keine idee|"
    r"überspringen|weiter|nächste(?: frage)?|"
    r"ik weet het niet|weet ik niet|weet niet|geen idee|geen flauw idee|overslaan|volgende(?: vraag)?"
)
_GIVE_UP_OR_META_FULL_RE = re.compile(
    rf"^(?:(?:{_GIVE_UP_FILLER})\s+)*(?:{_GIVE_UP_CORE})(?:\s+(?:{_GIVE_UP_FILLER}))*$",
    re.IGNORECASE,
)
_GIVE_UP_MAX_WORDS = 8


def normalize_give_up_text(text: str) -> str:
    """Lowercase, drop apostrophes, and collapse every non-letter/digit run to a single space so the
    anchored match is robust to punctuation and quote style."""
    lowered = text.lower().replace("'", "").replace("’", "").replace("`", "")
    return re.sub(r"[\W_]+", " ", lowered).strip()


def is_give_up_or_meta(text: Optional[str]) -> bool:
    """True only when the WHOLE message is a give-up/meta statement (modulo trivial filler) — never for a
    substantive answer that merely contains a trigger word."""
    if not text or not text.strip():
        return False
    if len(text.split()) > _GIVE_UP_MAX_WORDS:
        return False
    normalized = normalize_give_up_text(text)
    if not normalized:
        return False
    return bool(_GIVE_UP_OR_META_FULL_RE.fullmatch(normalized))


# --- localisation of the rendered numbers/text ----------------------------------------
_LOCALES: dict[str, dict[str, Any]] = {
    "en": {
        "module_word": "Module",
        "header": "**Question {n} of {total}**",
        "question_score": "**Question {n}: {s}/{m}**",
        "module_result_passed": "**{module} complete — {s}/{m} ({p}%). Passed.**",
        "module_result_failed": "**{module} — {s}/{m} ({p}%). Below the 80% needed.**",
        "module_pass_lines": [
            "Well done — you passed this module.",
            "Great work — this module is complete.",
            "Nice job — you successfully passed the module.",
            "Module passed — keep going.",
            "You've successfully completed this module.",
        ],
        "continue_prompt": "Ready to continue to the next module?",
        "module_fail_text": (
            "You did not reach the 80% score required to pass this module. This is a normal part of the "
            "learning process, and you will now complete a full retake of the module assessment.\n\n"
            "To prepare effectively for your next attempt:\n\n"
            "- **Review module learning material:** Go through the module sections related to the topics "
            "in question. Ensure you identify the specific areas that are relevant and answer the question "
            "feeling more confident.\n"
            "- **Review your previous answers:** Look at the responses you wrote before and identify any "
            "parts that clearly contributed to your score. Reuse any text that you know has answered the "
            "question correctly.\n"
            "- **Strengthen each response that you did not answer correctly:** Read the question carefully. "
            "Add any new information, refine explanations, and ensure your answer fully responds to the "
            "question.\n"
            "- **Start your retake:** When you're ready, retake the module!"
        ),
        "complete_result": "**Assessment complete — you've passed every module ({s}/{m}, {p}%).**",
        "summary_heading": "**Summary**",
        "summary_strengths": "**Strengths:**",
        "summary_revisit": "**Worth revisiting:**",
        "correction_offer": "You have one opportunity to add to or revise your answer — go ahead if you'd like.",
        # Backend-owned feedback for the two paths where the model has nothing new to judge, so its own
        # wording cannot be trusted not to contradict the score (a production learner answered "no" and was
        # told "Good answer — you covered the whole-body postural demand well").
        "answer_offer_no_attempt": (
            "You haven't answered this question yet. Take a moment and answer it now if you'd like — this is "
            "your one opportunity before it is scored."
        ),
        "no_answer_zero": "No answer was given for this question, so no points were awarded.",
        "decline_keeps_answer": "Understood — we'll go with your original answer for this question.",
        # Last-resort text so a turn can NEVER render an empty bubble (see ensure_non_empty). Reached when
        # the model wrote nothing — or nothing that survived the strip guards — and the backend had no line
        # of its own to render. It nudges without scoring anything: an answer the model never graded must
        # not be finalised from here.
        "answer_not_assessed": (
            "I wasn't able to assess a response there. Please write your answer to the question in your own "
            "words."
        ),
        "already_complete_note": "This assessment is already complete — there is nothing left to answer.",
        "motivational_passed": (
            "Great job. This wasn't a formality. You worked through the material module by module, you "
            "answered the questions, and you passed every one.\n\n"
            "Mastering performance is one of the most demanding skills a HYROX coach can develop. Completing "
            "this Level 2 assessment means you're building the kind of foundation that makes a real "
            "difference — to your athletes and to your coaching.\n\n"
            "This is a meaningful step. Keep going — your athletes will feel the difference."
        ),
        "closing_passed": (
            "You can now close the assessment, and your certificate will be generated. Please wait until "
            "you receive the corresponding notification. You will then find the certificate in the app and "
            "receive it again via email."
        ),
    },
    "de": {
        "module_word": "Modul",
        "header": "**Frage {n} von {total}**",
        "question_score": "**Frage {n}: {s}/{m}**",
        "module_result_passed": "**{module} abgeschlossen — {s}/{m} ({p}%). Bestanden.**",
        "module_result_failed": "**{module} — {s}/{m} ({p}%). Unter den nötigen 80%.**",
        "module_pass_lines": [
            "Stark gemacht — du hast dieses Modul bestanden.",
            "Gute Arbeit — dieses Modul ist abgeschlossen.",
            "Gut gemacht — du hast das Modul erfolgreich bestanden.",
            "Modul bestanden — weiter so.",
            "Du hast dieses Modul erfolgreich abgeschlossen.",
        ],
        "continue_prompt": "Bereit, mit dem nächsten Modul weiterzumachen?",
        "module_fail_text": (
            "Du hast die zum Bestehen dieses Moduls erforderlichen 80 % nicht erreicht. Das ist ein "
            "normaler Teil des Lernprozesses, und du machst jetzt eine vollständige Wiederholung des "
            "Modul-Assessments.\n\n"
            "So bereitest du dich optimal auf deinen nächsten Versuch vor:\n\n"
            "- **Lernmaterial des Moduls durchgehen:** Geh die Modulabschnitte zu den betreffenden Themen "
            "durch. Finde gezielt die relevanten Bereiche und beantworte die Frage mit mehr Sicherheit.\n"
            "- **Deine bisherigen Antworten durchsehen:** Sieh dir deine vorherigen Antworten an und "
            "erkenne, welche Teile eindeutig zu deiner Punktzahl beigetragen haben. Übernimm Textstellen, "
            "von denen du weißt, dass sie die Frage richtig beantwortet haben.\n"
            "- **Jede nicht korrekt beantwortete Antwort verbessern:** Lies die Frage sorgfältig. Ergänze "
            "neue Informationen, präzisiere deine Erklärungen und stelle sicher, dass deine Antwort die "
            "Frage vollständig beantwortet.\n"
            "- **Wiederholung starten:** Wenn du bereit bist, wiederhole das Modul!"
        ),
        "complete_result": "**Assessment abgeschlossen — du hast jedes Modul bestanden ({s}/{m}, {p}%).**",
        "summary_heading": "**Auswertung**",
        "summary_strengths": "**Stärken:**",
        "summary_revisit": "**Lohnt sich zu wiederholen:**",
        "correction_offer": "Du hast jetzt die Möglichkeit, deine Antwort zu ergänzen oder zu überarbeiten.",
        "answer_offer_no_attempt": (
            "Du hast diese Frage noch nicht beantwortet. Nimm dir einen Moment und beantworte sie jetzt, wenn "
            "du möchtest — das ist deine einzige Gelegenheit, bevor sie bewertet wird."
        ),
        "no_answer_zero": "Zu dieser Frage wurde keine Antwort gegeben, daher gab es keine Punkte.",
        "decline_keeps_answer": "Verstanden — wir bleiben bei deiner ursprünglichen Antwort auf diese Frage.",
        "answer_not_assessed": (
            "Ich konnte dazu keine Antwort auswerten. Bitte schreibe deine Antwort auf die Frage in eigenen "
            "Worten."
        ),
        "already_complete_note": "Dieses Assessment ist bereits abgeschlossen — es ist nichts mehr zu beantworten.",
        "motivational_passed": (
            "Stark gemacht. Das war keine Formalität: Du hast das Material Modul für Modul durchgearbeitet, "
            "die Fragen beantwortet und jedes Modul bestanden.\n\n"
            "Mastering Performance gehört zu den anspruchsvollsten Fähigkeiten, die ein HYROX-Coach entwickeln "
            "kann. Dass du dieses Level-2-Assessment abgeschlossen hast, zeigt, dass du dir ein Fundament "
            "aufbaust, das einen echten Unterschied macht — für deine Athletinnen und Athleten und für deine "
            "Coaching-Praxis.\n\n"
            "Das ist ein bedeutender Schritt. Bleib dran — deine Athletinnen und Athleten werden den "
            "Unterschied spüren."
        ),
        "closing_passed": (
            "Du kannst das Assessment jetzt schließen; dein Zertifikat wird erstellt. Bitte warte, bis du "
            "die entsprechende Benachrichtigung erhältst. Du findest das Zertifikat anschließend in der App "
            "und bekommst es zusätzlich per E-Mail."
        ),
    },
    "nl": {
        "module_word": "Module",
        "header": "**Vraag {n} van {total}**",
        "question_score": "**Vraag {n}: {s}/{m}**",
        "module_result_passed": "**{module} voltooid — {s}/{m} ({p}%). Geslaagd.**",
        "module_result_failed": "**{module} — {s}/{m} ({p}%). Onder de vereiste 80%.**",
        "module_pass_lines": [
            "Goed gedaan — je bent geslaagd voor deze module.",
            "Sterk werk — deze module is voltooid.",
            "Mooi gedaan — je bent geslaagd voor de module.",
            "Module gehaald — ga zo door.",
            "Je hebt deze module succesvol afgerond.",
        ],
        "continue_prompt": "Klaar om verder te gaan met de volgende module?",
        "module_fail_text": (
            "Je hebt de vereiste 80% om voor deze module te slagen niet gehaald. Dit is een normaal "
            "onderdeel van het leerproces, en je maakt nu een volledige herkansing van het "
            "module-assessment.\n\n"
            "Zo bereid je je goed voor op je volgende poging:\n\n"
            "- **Bekijk het lesmateriaal van de module:** Neem de moduleonderdelen door die met de "
            "betreffende onderwerpen te maken hebben. Zorg dat je de specifieke relevante gebieden "
            "herkent en beantwoord de vraag met meer vertrouwen.\n"
            "- **Bekijk je eerdere antwoorden:** Kijk naar de antwoorden die je eerder schreef en bepaal "
            "welke delen duidelijk aan je score hebben bijgedragen. Hergebruik tekst waarvan je weet dat "
            "die de vraag correct heeft beantwoord.\n"
            "- **Versterk elk antwoord dat je niet goed had:** Lees de vraag zorgvuldig. Voeg nieuwe "
            "informatie toe, verfijn je uitleg en zorg dat je antwoord de vraag volledig beantwoordt.\n"
            "- **Start je herkansing:** Wanneer je er klaar voor bent, maak je de module opnieuw!"
        ),
        "complete_result": "**Beoordeling voltooid — je bent voor elke module geslaagd ({s}/{m}, {p}%).**",
        "summary_heading": "**Overzicht**",
        "summary_strengths": "**Sterke punten:**",
        "summary_revisit": "**De moeite waard om te herhalen:**",
        "correction_offer": "Je hebt nu de mogelijkheid om je antwoord aan te vullen of te herzien.",
        "answer_offer_no_attempt": (
            "Je hebt deze vraag nog niet beantwoord. Neem even de tijd en beantwoord hem nu als je wilt — dit "
            "is je enige kans voordat de vraag wordt beoordeeld."
        ),
        "no_answer_zero": "Op deze vraag is geen antwoord gegeven, dus zijn er geen punten toegekend.",
        "decline_keeps_answer": "Begrepen — we houden je oorspronkelijke antwoord voor deze vraag aan.",
        "answer_not_assessed": (
            "Ik kon daar geen antwoord beoordelen. Schrijf je antwoord op de vraag in je eigen woorden."
        ),
        "already_complete_note": "Deze beoordeling is al afgerond — er is niets meer te beantwoorden.",
        "motivational_passed": (
            "Goed gedaan. Dit was geen formaliteit: je hebt de stof module voor module doorgewerkt, de "
            "vragen beantwoord en bent voor elke module geslaagd.\n\n"
            "Mastering performance is een van de meest veeleisende vaardigheden die een HYROX-coach kan "
            "ontwikkelen. Dat je dit Level 2-assessment hebt afgerond, betekent dat je bouwt aan een "
            "fundament dat echt verschil maakt — voor je atleten en voor je praktijk.\n\n"
            "Dit is een betekenisvolle stap. Ga zo door — je atleten zullen het verschil voelen."
        ),
        "closing_passed": (
            "Je kunt het assessment nu sluiten; je certificaat wordt gegenereerd. Wacht tot je de "
            "bijbehorende melding ontvangt. Je vindt het certificaat daarna in de app en ontvangt het ook "
            "per e-mail."
        ),
    },
}


def _locale(language: Optional[str]) -> dict[str, Any]:
    code = (language or "en")[:2].lower()
    return _LOCALES.get(code, _LOCALES["en"])


# --- marker format / parse ------------------------------------------------------------
def format_plan_marker() -> str:
    return "[[PLAN modules=" + ",".join(MODULES) + "]]"


def format_module_marker(module_key: str, attempt: int) -> str:
    return f"[[MODULE m={module_key} attempt={attempt}]]"


def format_asked_marker(question_id: int) -> str:
    return f"[[ASKED q={question_id}]]"


def format_modpass_marker(module_key: str) -> str:
    return f"[[MODPASS m={module_key}]]"


def format_modfail_marker(module_key: str) -> str:
    return f"[[MODFAIL m={module_key}]]"


def format_score_marker(score: dict[str, Any]) -> str:
    """Canonical [[SCORE]] marker text for a normalised score. Stored INSTEAD of the model's own marker
    text: the model may write a wrong ``q`` attribute (e.g. the next question's id), and while the turn
    itself forces the pinned id, a verbatim-stored wrong ``q`` would replay into ``_scores_in_window``
    under the wrong question and permanently desync the module counter (the current question could then
    never be finalised)."""
    pts = ",".join(str(1 if p else 0) for p in score.get("points", []))
    return f'[[SCORE q={score["q"]} points="{pts}" max={score["max"]} mod="{score["mod"]}"]]'


def format_prov_marker(score: dict[str, Any]) -> str:
    """Canonical ``[[PROV]]`` marker: the PINNED per-key-point verdict of the learner's first answer to a
    question, written when the single correction is offered. It does not finalise the question (no ``max``/
    ``mod``, and ``_scores_in_window`` ignores it), it only makes the model's judgement of that answer
    immutable so a later turn cannot silently upgrade it."""
    pts = ",".join(str(1 if p else 0) for p in score.get("points", []))
    return f'[[PROV q={score["q"]} points="{pts}"]]'


def zero_verdict(question_id: Any) -> dict[str, Any]:
    """An all-zero verdict for ``question_id`` — the only defensible score when the learner produced no
    substantive answer at all."""
    return normalize_score(question_id, [0] * (key_point_count(question_id) if isinstance(question_id, int) else 0))


def merge_best_verdicts(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    """Per-key-point best of two verdicts for the same question — the "better of the two attempts" rule,
    computed by the backend instead of trusted to the model. A key point earned in either attempt counts,
    and one earned in the first attempt can never be lost by revising."""
    a = list(first.get("points", []))
    b = list(second.get("points", []))
    width = max(len(a), len(b))
    a += [0] * (width - len(a))
    b += [0] * (width - len(b))
    return normalize_score(first.get("q"), [1 if (a[i] or b[i]) else 0 for i in range(width)])


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
    """Authoritative per-question score from ``questions.py`` — the model's arithmetic is not trusted.
    Validates/clamps the per-point array to the question's key-point count and caps ``awarded`` at
    ``max_pts``. The score carries its module key so the per-module tally can be rebuilt."""
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
        "mod": module_of(qid) if isinstance(qid, int) else "",
    }


def parse_new_score(text: Optional[str], current_id: Optional[int]) -> Optional[dict[str, Any]]:
    """Parse the (single) finalising ``[[SCORE]]`` marker from this turn's output, if any. The question
    id is forced to ``current_id`` (the backend-pinned question)."""
    if not text:
        return None
    match = SCORE_MARKER_RE.search(text)
    if not match:
        return None
    attrs = _parse_attrs(match.group(1))
    qid = current_id if current_id is not None else attrs.get("q")
    return normalize_score(qid, parse_points(attrs.get("points")))


def compute_tally(scores: list[dict[str, Any]]) -> dict[str, Any]:
    """Authoritative cumulative tally from normalised per-question scores (used both per-module and
    overall)."""
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


def module_breakdown(scores: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Per-module awarded/max — the basis for the strengths/weaknesses take-aways and the result log."""
    out: dict[str, dict[str, int]] = {}
    for s in scores:
        mod = str(s.get("mod", "")) or "(unknown)"
        bucket = out.setdefault(mod, {"awarded": 0, "max": 0})
        bucket["awarded"] += int(s.get("awarded", 0) or 0)
        bucket["max"] += int(s.get("max", 0) or 0)
    return out


# --- message + window helpers ---------------------------------------------------------
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


def _latest_module_message_index(messages: list[dict[str, Any]]) -> Optional[int]:
    last: Optional[int] = None
    for idx, msg in enumerate(messages or []):
        if isinstance(msg, dict) and msg.get("role") == "assistant" and MODULE_MARKER_RE.search(_message_text(msg)):
            last = idx
    return last


def parse_asked_ids(window: str, allowed_ids: list[int]) -> set[int]:
    """Pool ids the backend has already presented in ``window`` (an attempt window), filtered to the
    current module's questions so stale markers cannot leak in."""
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
        if qid in allowed_ids:
            out.add(qid)
    return out


def _scores_in_window(window: str, allowed_ids: list[int]) -> list[dict[str, Any]]:
    """Normalised scores for ``allowed_ids`` found in ``window`` (a single module attempt), in the
    module's question order."""
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
        if qid in allowed_ids:
            by_q[qid] = normalize_score(qid, parse_points(attrs.get("points")))
    return [by_q[q] for q in allowed_ids if q in by_q]


def provisional_in_window(window: str, question_id: Optional[int]) -> Optional[dict[str, Any]]:
    """The pinned first-attempt verdict for ``question_id`` in this attempt window, or None. The LAST
    ``[[PROV]]`` for that question wins (the backend only ever writes one per question per attempt)."""
    if question_id is None:
        return None
    found: Optional[dict[str, Any]] = None
    for m in PROV_MARKER_RE.finditer(window or ""):
        attrs = _parse_attrs(m.group(1))
        q_raw = attrs.get("q")
        if q_raw is None:
            continue
        try:
            qid = int(q_raw)
        except (TypeError, ValueError):
            continue
        if qid == question_id:
            found = normalize_score(qid, parse_points(attrs.get("points")))
    return found


def _segment_window(window: str) -> list[dict[str, Any]]:
    """Split a run window into per-module-attempt segments at ``[[MODULE]]`` markers. Each segment is
    ``{"module": key, "attempt": n, "text": <text up to the next MODULE marker>}``."""
    markers = list(MODULE_MARKER_RE.finditer(window))
    segments: list[dict[str, Any]] = []
    for i, m in enumerate(markers):
        attrs = _parse_attrs(m.group(1))
        try:
            attempt = int(attrs.get("attempt", 1))
        except (TypeError, ValueError):
            attempt = 1
        start = m.end()
        end = markers[i + 1].start() if i + 1 < len(markers) else len(window)
        segments.append({"module": attrs.get("m", ""), "attempt": attempt, "text": window[start:end]})
    return segments


def prior_module_results(segments: list[dict[str, Any]], before_module: str) -> list[tuple[str, list[dict[str, Any]]]]:
    """For every module that comes BEFORE ``before_module`` in the fixed order, the scores from its last
    (passing) attempt segment — the basis for the cross-module summary at completion."""
    results: list[tuple[str, list[dict[str, Any]]]] = []
    target_idx = MODULES.index(before_module) if before_module in MODULES else len(MODULES)
    for module in MODULES[:target_idx]:
        last_text: Optional[str] = None
        for seg in segments:
            if seg["module"] == module:
                last_text = seg["text"]
        if last_text is not None:
            results.append((module, _scores_in_window(last_text, module_questions(module))))
    return results


# --- per-question interaction ---------------------------------------------------------
def _assistant_index_that_asked(
    messages: list[dict[str, Any]],
    start_idx: int,
    current_id: Optional[int],
) -> Optional[int]:
    """Index of the assistant message whose ``[[ASKED q=current_id]]`` marker presented the current
    question (reliable even when the ask shares a message with a score marker)."""
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
    module_message_index: Optional[int],
    current_id: Optional[int],
    asked_ids: set[int],
    provisional: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Infer the current question phase from replayed roles + the backend's ``[[ASKED]]``/``[[SCORE]]``/
    ``[[PROV]]`` markers, scoped to the current module attempt (everything after its ``[[MODULE]]`` marker).

    ``substantive_attempts_for_current`` counts only real answer attempts — a refusal ("no", "skip", "I don't
    know") is NOT one, so ``render_assessment_turn`` can hold the score at zero when the learner never
    actually answered. ``must_finalize_current`` means "the single correction has already been offered, so
    this turn ends the question", and the correction is now considered offered when the backend pinned a
    ``[[PROV]]`` verdict for it (falling back to "any assistant message after the ask" for histories written
    before provisional verdicts existed).
    """
    asked = current_id is not None and current_id in asked_ids
    if not asked:
        return {
            "current_question_asked": False,
            "latest_user_answer_pending": False,
            "answer_attempts_for_current": 0,
            "substantive_attempts_for_current": 0,
            "latest_answer_is_decline": False,
            "correction_or_repeat_already_sent": False,
            "must_finalize_current": False,
        }

    start_idx = module_message_index if module_message_index is not None else 0
    ask_idx = _assistant_index_that_asked(messages, start_idx, current_id)
    after = (messages or [])[(ask_idx + 1):] if ask_idx is not None else []

    user_messages = [m for m in after if isinstance(m, dict) and m.get("role") == "user"]
    answer_attempt_count = len(user_messages)
    substantive_attempts = sum(
        1 for m in user_messages if _message_text(m).strip() and not is_give_up_or_meta(_message_text(m))
    )
    assistant_replied_after_ask = any(isinstance(m, dict) and m.get("role") == "assistant" for m in after)
    correction_or_repeat_already_sent = provisional is not None or assistant_replied_after_ask

    latest = messages[-1] if messages else None
    latest_user_text = _message_text(latest) if isinstance(latest, dict) and latest.get("role") == "user" else ""
    latest_user_answer_pending = answer_attempt_count >= 1 and bool(latest_user_text)
    # A give-up no longer forces finalisation on its own: the learner gets the one correction opportunity
    # either way (a bare "no" to a not-yet-answered question used to be graded on the spot — and the model
    # graded it at full marks). Two learner messages in a row with no assistant turn between them still
    # finalise, so nothing can loop.
    must_finalize = bool(
        latest_user_answer_pending and (answer_attempt_count >= 2 or correction_or_repeat_already_sent)
    )
    return {
        "current_question_asked": True,
        "latest_user_answer_pending": latest_user_answer_pending,
        "answer_attempts_for_current": answer_attempt_count,
        "substantive_attempts_for_current": substantive_attempts,
        "latest_answer_is_decline": bool(latest_user_text) and is_give_up_or_meta(latest_user_text),
        "correction_or_repeat_already_sent": correction_or_repeat_already_sent,
        "must_finalize_current": must_finalize,
    }


# --- per-turn state machine -----------------------------------------------------------
def _start_module_state(
    module_key: str,
    attempt: int,
    plan_is_new: bool,
    prior_results: Optional[list[tuple[str, list[dict[str, Any]]]]] = None,
) -> dict[str, Any]:
    """State for a turn that begins a module attempt (run start, advance, or retry): the first question
    of ``module_key`` will be asked. ``prior_results`` carries the modules already finished — without it
    the session log written on this turn reported a run with zero questions finalised and overwrote the
    record of everything that came before it (visible in production logs as interleaved
    "0/52 questions finalised" writes)."""
    mod_qs = module_questions(module_key)
    return {
        "current_module": module_key,
        "attempt": attempt,
        "module_is_new": True,
        "plan_is_new": plan_is_new,
        "assessment_complete": False,
        "module_attempt_complete": False,
        "scores": [],
        "n_in_module": 0,
        "module_questions": mod_qs,
        "current_id": mod_qs[0] if mod_qs else None,
        "is_first_in_module": True,
        "is_last_in_module": len(mod_qs) <= 1,
        "is_final_module": is_last_module(module_key),
        "prior_module_results": list(prior_results or []),
        "provisional": None,
        "current_question_asked": False,
        "latest_user_answer_pending": False,
        "answer_attempts_for_current": 0,
        "substantive_attempts_for_current": 0,
        "latest_answer_is_decline": False,
        "correction_or_repeat_already_sent": False,
        "must_finalize_current": False,
    }


def _completed_state() -> dict[str, Any]:
    return {
        "current_module": None,
        "attempt": 0,
        "module_is_new": False,
        "plan_is_new": False,
        "assessment_complete": True,
        "module_attempt_complete": False,
        "scores": [],
        "n_in_module": 0,
        "module_questions": [],
        "current_id": None,
        "is_first_in_module": False,
        "is_last_in_module": False,
        "is_final_module": False,
        "prior_module_results": [],
        "provisional": None,
        "current_question_asked": False,
        "latest_user_answer_pending": False,
        "answer_attempts_for_current": 0,
        "substantive_attempts_for_current": 0,
        "latest_answer_is_decline": False,
        "correction_or_repeat_already_sent": False,
        "must_finalize_current": False,
    }


def derive_turn_state(messages: list[dict[str, Any]], final_content: Optional[str] = None) -> dict[str, Any]:
    """Reconstruct the authoritative assessment state for this turn from replayed history.

    A fresh session (no ``[[PLAN]]``) starts module 1. Otherwise the run window is everything after the
    latest ``[[PLAN]]``; within it the latest ``[[MODULE]]`` marker pins the current module attempt. A
    ``[[MODPASS]]`` after it means the learner just passed a module and is choosing to continue (advance
    to the next module this turn); a ``[[MODFAIL]]`` means they retry the same module. A ``[[DONE]]``
    means the run is complete and terminal.
    """
    texts = assistant_texts(messages, final_content)
    blob = "\n".join(texts)

    plan_match = None
    for m in PLAN_MARKER_RE.finditer(blob):
        plan_match = m
    if plan_match is None:
        # No run yet — the learner just tapped "Start". Begin the first module.
        return _start_module_state(MODULES[0], attempt=1, plan_is_new=True)

    window = blob[plan_match.end():]
    if DONE_MARKER_RE.search(window):
        return _completed_state()

    segments = _segment_window(window)
    module_markers = list(MODULE_MARKER_RE.finditer(window))
    if not module_markers:
        # PLAN exists but no module started yet (defensive) — begin the first module.
        return _start_module_state(MODULES[0], attempt=1, plan_is_new=False)

    last_module = module_markers[-1]
    last_attrs = _parse_attrs(last_module.group(1))
    cur_mod = last_attrs.get("m", MODULES[0])
    try:
        cur_attempt = int(last_attrs.get("attempt", 1))
    except (TypeError, ValueError):
        cur_attempt = 1
    after_module = window[last_module.end():]

    # A module-boundary event after the current MODULE marker means the learner is acting on the
    # transition this turn: continue to the next module, or retake the current one. The backend appends
    # its single authoritative boundary marker at the very END of the boundary message, so when a legacy
    # history (stored before model-faked markers were stripped) carries a fake beside the real one, the
    # LAST marker in the window is the backend's — act on that, never on an earlier fake. (Observed in
    # production: a fake [[MODPASS]] preceding the real [[MODFAIL]] used to advance a learner past a
    # failed module because MODPASS was checked first.)
    boundary_events = [(m.start(), "pass") for m in MODPASS_MARKER_RE.finditer(after_module)]
    boundary_events += [(m.start(), "fail") for m in MODFAIL_MARKER_RE.finditer(after_module)]
    if boundary_events:
        _, boundary_kind = max(boundary_events)
        if boundary_kind == "fail":
            return _start_module_state(
                cur_mod,
                attempt=cur_attempt + 1,
                plan_is_new=False,
                prior_results=prior_module_results(segments, cur_mod),
            )
        nxt = next_module(cur_mod)
        if nxt is not None:
            return _start_module_state(
                nxt, attempt=1, plan_is_new=False, prior_results=prior_module_results(segments, nxt)
            )
        # A MODPASS for the FINAL module can only be model-faked noise replaying from a legacy session:
        # the backend never writes one there (passing the final module renders the completion sequence
        # with [[DONE]] + [[PROGRESS]] instead). Returning _completed_state() here — as this code did
        # before 2026-07-17 — silently went terminal WITHOUT the completion sequence or the LMS report,
        # permanently stranding the run (the reported "stuck after Module 10 passed" bug). Ignore the
        # fake and fall through to the mid-module derivation so the last question can still be
        # finalised and the genuine completion rendered.
        logger.warning("HYROX: ignoring model-faked [[MODPASS]] for final module %s in replayed history", cur_mod)

    # Mid-module: the current attempt is active.
    mod_qs = module_questions(cur_mod)
    scores = _scores_in_window(after_module, mod_qs)
    asked_ids = parse_asked_ids(after_module, mod_qs)
    n = len(scores)
    current_id = mod_qs[n] if n < len(mod_qs) else None
    # Every question of this attempt is graded but no boundary marker closed it. The boundary is therefore
    # OWED, and this state says so instead of leaving nothing to do: before 2026-07-29 `current_id is None`
    # with the run not complete was a dead end — `render_assessment_turn` returned the model's improvised
    # text and rendered nothing, on that turn and every turn after it. A learner who passed Module 10 that
    # way saw no completion sequence, got no [[DONE]] (so the input stayed live), no [[PROGRESS]] (no LMS
    # completion, no certificate), and no session-log write, and every further message drew an invented
    # "You're done" from a model whose only instruction was to wait. Rendering the boundary from the
    # derived state makes it idempotent: whatever went wrong on the finalising turn, the next learner
    # message converges to the correct module result — or to the genuine end of the assessment.
    module_attempt_complete = current_id is None and n > 0
    if module_attempt_complete:
        logger.warning(
            "HYROX: module %s attempt %s is fully graded with no boundary marker; rendering the owed "
            "%s now",
            cur_mod,
            cur_attempt,
            "completion sequence" if is_last_module(cur_mod) else "module result",
        )
    module_message_index = _latest_module_message_index(messages)
    # The pinned first-attempt verdict for the question now in play, if the correction was already offered.
    provisional = provisional_in_window(after_module, current_id)
    interaction = _current_question_interaction(
        messages, module_message_index, current_id, asked_ids, provisional
    )
    return {
        "current_module": cur_mod,
        "attempt": cur_attempt,
        "module_is_new": False,
        "plan_is_new": False,
        "assessment_complete": False,
        "module_attempt_complete": module_attempt_complete,
        "provisional": provisional,
        "scores": scores,
        "n_in_module": n,
        "module_questions": mod_qs,
        "current_id": current_id,
        "is_first_in_module": n == 0,
        "is_last_in_module": current_id is not None and n == len(mod_qs) - 1,
        "is_final_module": is_last_module(cur_mod),
        "prior_module_results": prior_module_results(segments, cur_mod),
        **interaction,
    }


def build_state_injection(state: dict[str, Any], language: Optional[str] = None) -> str:
    """The system-controlled block appended to the prompt each turn. Pins the LLM to a single question
    within the current module and forbids it from producing any numbers or owning the flow."""
    if state.get("assessment_complete"):
        return (
            "\n\n## CURRENT TURN STATE (system-controlled — obey exactly)\n"
            "- The learner has passed every module and the assessment is complete. It cannot be retaken in "
            "this session. Do NOT ask any question and do NOT emit any marker. Briefly acknowledge that the "
            "assessment is finished; the system already rendered the final result and the certificate notice.\n"
        )

    current_id = state.get("current_id")
    if state.get("module_attempt_complete"):
        # The backend is rendering the owed module result (or the whole end-of-assessment sequence) itself
        # on this turn and discards whatever the model writes, so asking it for anything only invites the
        # fabricated boundary bubble this state exists to repair.
        return (
            "\n\n## CURRENT TURN STATE (system-controlled — obey exactly)\n"
            "- Every question of this module has already been graded. The system writes the entire message "
            "for this turn (the module result, the transition, and — if this was the last module — the whole "
            "end-of-assessment sequence). Do NOT grade anything, do NOT ask a question, do NOT write a "
            "module result, score, percentage, pass/fail, transition, summary, or closing text, and do NOT "
            "emit any marker. Reply with nothing at all.\n"
        )
    if current_id is None:
        return (
            "\n\n## CURRENT TURN STATE (system-controlled — obey exactly)\n"
            "- Wait for the system. Do NOT ask a question and do NOT emit any marker.\n"
        )

    cur_mod = state.get("current_module")
    module_total = len(state.get("module_questions") or [])
    n = state.get("n_in_module", 0)
    kpc = key_point_count(current_id)
    cap = max_points(current_id)
    question_text = render_question_text(current_id)
    is_last_in_module = bool(state.get("is_last_in_module"))
    is_final_module = bool(state.get("is_final_module"))
    module_is_new = bool(state.get("module_is_new"))

    question = get_question(current_id) or {}
    key_points = list(question.get("key_points") or [])
    # A grading turn is one where the learner actually produced something new to judge. The two other
    # answer-pending shapes — a refusal with no answer at all, and a declined correction (whose verdict is
    # already pinned) — are decided entirely by the backend, so the model grades nothing and writes nothing.
    is_grading_turn = bool(
        state.get("latest_user_answer_pending")
        and int(state.get("substantive_attempts_for_current", 0) or 0) > 0
        and not (state.get("latest_answer_is_decline") and state.get("provisional") is not None)
    )

    lines = [
        "\n\n## CURRENT TURN STATE (system-controlled — authoritative; overrides any conflicting instruction)",
        f"- Current module: {cur_mod} (attempt {state.get('attempt', 1)}). Questions finalised in this "
        f"module attempt so far: {n} of {module_total}.",
        f"- The ONLY question you may handle this turn is pool question #{current_id} (module {cur_mod}); it "
        f"has {kpc} required key points and a maximum of {cap} points.",
        f"- Authoritative visible question text for this pool question: {question_text}",
    ]
    # The rubric for the pinned question is restated HERE rather than left to be located among all 52
    # questions in the pool: grading the wrong question's key points is a silent accuracy failure, and the
    # verdict array is positional, so the model must be looking at exactly this list in exactly this order.
    if key_points:
        lines.append(
            f"- Authoritative REQUIRED KEY POINTS for pool question #{current_id} — grade against exactly "
            "these, in this order, one 0/1 verdict per point:"
        )
        lines.extend(f"    {i}. {kp}" for i, kp in enumerate(key_points, 1))
        lines.append(
            "- Award 1 for a key point ONLY if the learner's own words actually demonstrate it (equivalent "
            "wording, examples, or phrasing is fine — the rubric's exact words are not required). If the "
            "learner did not express it, award 0: never infer it, never give the benefit of the doubt, never "
            "credit a point the question itself already states, and never treat an overall impression of a "
            "good answer as evidence for a specific point you cannot point to in their text."
        )
    if not state.get("current_question_asked"):
        lines.append(
            f"- CURRENT ACTION: ASK question #{current_id} now (the first question of this module attempt). "
            "Put only [[ASK]] on its own line at the point where the question should appear. Do NOT write, "
            "rephrase, translate, or add any visible question text yourself; the backend replaces [[ASK]] with "
            "the exact authoritative question text (and the module heading + counter) above. Never reveal the "
            "pool number, module weighting, point values, or rubric."
        )
    elif state.get("latest_user_answer_pending"):
        attempts = int(state.get("answer_attempts_for_current", 0) or 0)
        substantive = int(state.get("substantive_attempts_for_current", 0) or 0)
        declined = bool(state.get("latest_answer_is_decline"))
        provisional = state.get("provisional")
        if substantive == 0:
            # The learner has refused/skipped without ever answering. Nothing is gradeable, and the system
            # writes both the score (zero) and the message, so the model must not invent an assessment of an
            # answer that does not exist ("Good answer — you covered the postural demand well" for "no").
            lines.append(
                f"- CURRENT ACTION: NONE. The learner has not answered question #{current_id} at all — their "
                "message is a refusal or a skip, not an answer. Do NOT grade it, do NOT emit any marker, do NOT "
                "praise or describe an answer, and do NOT claim any key point was covered. The system writes the "
                "entire message for this turn. Reply with nothing at all."
            )
        elif declined and provisional is not None:
            # The learner declined the correction, so no new content exists. The verdict was pinned when the
            # correction was offered and the system finalises from it; a fresh re-grade here is exactly how a
            # production learner went from "one key part is missing" to full marks in one turn.
            lines.append(
                f"- CURRENT ACTION: NONE. The learner has declined to revise their answer to question "
                f"#{current_id}, so there is nothing new to judge. The verdict for this question was already "
                "recorded and the system finalises from that record and writes the entire message for this turn. "
                "Do NOT re-grade, do NOT emit any marker, and do NOT restate or revise your earlier assessment. "
                "Reply with nothing at all."
            )
        else:
            lines.extend(
                [
                    f"- CURRENT ACTION: GRADE the learner's answer to question #{current_id}. This question has "
                    "already been asked; you MUST NOT repeat it, MUST NOT ask it again, and MUST NOT use [[ASK]].",
                    "- Judge only the learner's own answer attempts for this question that appear after it was "
                    "asked. Ignore refusals/skips — they contain no answer and earn nothing.",
                    "- ALWAYS end this response with EXACTLY one [[SCORE]] marker carrying your per-key-point "
                    "verdict, whether the answer is complete or not. You do NOT decide whether the question is "
                    "finished: the system compares your verdict against the maximum and either finalises the "
                    "question or offers the learner their single correction opportunity, and it writes that offer "
                    "itself.",
                    "- So write ONLY brief, encouraging feedback on how complete the answer was (no score, no "
                    "numbers, no missing-key-point reveal) plus the marker. Do NOT tell the learner they may "
                    "revise or add to their answer — the system adds that line when it applies — and do NOT ask a "
                    "question of any kind.",
                    "- Your feedback must match your verdict: if you are awarding less than every key point, do "
                    "not call the answer complete, strong, or fully correct.",
                ]
            )
            if state.get("must_finalize_current"):
                lines.append(
                    "- This answer is the learner's revision after their one correction opportunity, so your "
                    "verdict finalises the question. The system keeps the better per-key-point result across "
                    "their attempts, so a point they already earned cannot be lost here."
                )
        lines.append(
            f"- Learner messages seen for this current question: {attempts} (of which {substantive} contain an "
            f"actual answer attempt)."
        )
    else:
        lines.append(
            f"- CURRENT ACTION: continue the in-progress handling of question #{current_id}. It has already been "
            "asked, so do NOT repeat it and do NOT use [[ASK]]."
        )
    if is_grading_turn:
        lines.extend(
            [
                "- End your message with EXACTLY one marker on its own line, on every turn where you grade:",
                f'  [[SCORE q={current_id} points="<{kpc} comma-separated values, one 0 or 1 per key point in '
                f'listed order>" max={cap} mod="{cur_mod}"]]',
                "- Award 1 for each key point the learner demonstrated and 0 otherwise. The system sums these "
                "values, decides whether the question is finished, and shows every number — your job is the "
                "per-point judgement only.",
            ]
        )
    lines.extend(
        [
            "- Write NO numbers anywhere (no question number, per-question score, module total, percentage, or "
            'pass/fail). In particular NEVER write the per-question score line (e.g. "**Question 2: 4/4**", or a '
            "bare \"4/4\"): the system prints it immediately above your feedback, so writing it yourself shows the "
            "learner the same line twice. Place [[ASK]] ONLY on a message where you actually ask a not-yet-asked "
            "question — never on "
            "a feedback, correction-offer, or finalisation/score-only message. The system renders the module "
            "heading, the \"Question N of M\" header, each question's score, the module result, the module "
            "transition, and the final result. Never emit [[PLAN]], [[MODULE]], [[MODPASS]], [[MODFAIL]], "
            "[[PROGRESS]], or [[DONE]]; the system owns those.",
        ]
    )
    if not (is_last_in_module and is_final_module):
        lines.append(
            "- This turn is NOT the end of the assessment. Do NOT write any end-of-assessment summary, "
            "strengths/worth-revisiting take-aways, closing remarks, or the [[SUMMARY]] token — those belong "
            "ONLY to the finalising turn of the FINAL module's LAST question."
        )
    if not is_last_in_module:
        lines.append(
            "- AUTO-NEXT: when your verdict finishes this question, the system AUTOMATICALLY presents the next "
            "question of this module in the SAME message. So never write the next question and never use "
            "[[ASK]] on a grading message; you may add at most one short, natural lead-in sentence."
        )
    elif is_final_module:
        lines.append(
            "- This is the LAST question of the FINAL module, so the verdict that finishes it completes the whole "
            "assessment. That happens on exactly one turn: the one where you award EVERY key point on the "
            "learner's first answer, or the one where you grade their revision after the single correction (the "
            "CURRENT ACTION above says so). On any other turn write NO summary and NO take-aways. On that one "
            "finalising turn, write in this order: "
            "(1) your brief feedback on this final answer; (2) a line containing exactly [[SUMMARY]]; (3) general "
            "end-of-assessment take-aways spanning ALL modules — in plain language, name 2-4 topics that were "
            "clear strengths and 2-4 worth revisiting, specific to what the learner showed, framed as guidance, "
            "WITHOUT revealing model answers and WITHOUT any numbers, scores, or percentages. Do NOT write a "
            "heading, the score, the module result, pass/fail, motivational, or closing/certificate text, and do "
            "NOT use [[ASK]]. The system renders the module result, the summary heading, the final result, the "
            "motivational message, and the closing/certificate messages, and supplies the take-aways itself if "
            "you omit [[SUMMARY]]."
        )
    else:
        lines.append(
            "- This is the LAST question of this module. After finalising it, write only your brief feedback on "
            "this answer and the [[SCORE]] marker — do NOT use [[ASK]], do NOT write a next question, and do NOT "
            "write any module-pass/continue or retake text. The system evaluates the module against the 80% "
            "threshold and renders the module result and the transition (continue or retake) itself."
        )
    if module_is_new and state.get("plan_is_new"):
        lines.append(
            "- This is the very first question of the assessment. The learner has ALREADY seen the full welcome and "
            "the rules (module-by-module, free-text answers, one revision each, 80% to pass each module, a summary at "
            'the end) and has just tapped "Start". Do NOT write any intro, welcome, greeting, or rules recap — output '
            "only [[ASK]] on its own line."
        )
    elif module_is_new:
        lines.append(
            "- The learner is beginning a module (either continuing after passing the previous one, or retaking this "
            "one). Do NOT write a recap or transition — output only [[ASK]] on its own line; the system has already "
            "rendered the transition text."
        )
    return "\n".join(lines) + "\n"


# --- rendering the authoritative numbers into the message -----------------------------
def strip_rendered_numbers(text: Optional[str]) -> str:
    """Remove every backend-rendered structural line the model wrote (it is told not to; this guarantees
    only the backend's numbers and headings appear): the "Question N of M" header, the per-question score
    line, a bare score fraction, a running total, a module-result line, a completion line, the bare
    module heading, and any of the backend's own fixed prose (module pass/fail transition, continue prompt,
    correction offer, motivational and closing/certificate text). Each pattern is anchored to a whole line,
    so prose that merely contains a number or a module reference is untouched."""
    if not text:
        return text or ""
    cleaned = _HEADER_LINE_RE.sub("", text)
    cleaned = _QUESTION_SCORE_LINE_RE.sub("", cleaned)
    cleaned = _BARE_SCORE_LINE_RE.sub("", cleaned)
    cleaned = _TOTAL_LINE_RE.sub("", cleaned)
    cleaned = _COMPLETE_LINE_RE.sub("", cleaned)
    cleaned = _MODULE_RESULT_LINE_RE.sub("", cleaned)
    cleaned = _MODULE_HEADING_LINE_RE.sub("", cleaned)
    cleaned = _strip_backend_owned_prose(cleaned)
    cleaned = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", cleaned)
    return cleaned.strip()


def _rendered_line_key(line: str) -> str:
    """Normalised comparison key for one rendered line: case-folded with emphasis, whitespace, and
    punctuation removed, so an imitation differing only in bold markers, spacing, or trailing punctuation
    still counts as the same line."""
    return re.sub(r"[^a-z0-9/%]+", "", line.lower())


# Every fixed line the BACKEND authors, across all locales, keyed for whole-line comparison. The shape
# rules above catch a fabricated *number*; these catch a fabricated *sentence*. The model imitates the
# module-boundary bubble it sees replayed (production logs: a faked [[MODPASS]] at ~8% of boundaries,
# three of them at the final module in five days), and until 2026-07-29 nothing removed the prose beside
# the marker — so a learner could be shown "Well done — you passed this module." plus
# "Ready to continue to the next module?" with no Continue button and no completion sequence behind it.
# Only whole lines match (bold/case/punctuation-insensitive), and these are long fixed sentences, so
# ordinary feedback is never touched. The summary strengths/revisit LABELS are deliberately absent: the
# model legitimately authors the take-aways body under the backend's heading.
_BACKEND_OWNED_PROSE_KEYS: Optional[set[str]] = None


def _backend_owned_prose_keys() -> set[str]:
    global _BACKEND_OWNED_PROSE_KEYS
    if _BACKEND_OWNED_PROSE_KEYS is None:
        blocks: list[str] = []
        for locale in _LOCALES.values():
            blocks.extend(locale["module_pass_lines"])
            blocks.extend(
                str(locale[key])
                for key in (
                    "continue_prompt",
                    "module_fail_text",
                    "summary_heading",
                    "correction_offer",
                    "answer_offer_no_attempt",
                    "no_answer_zero",
                    "decline_keeps_answer",
                    "answer_not_assessed",
                    "already_complete_note",
                    "motivational_passed",
                    "closing_passed",
                )
            )
        _BACKEND_OWNED_PROSE_KEYS = {
            key for block in blocks for key in (_rendered_line_key(line) for line in block.splitlines()) if key
        }
    return _BACKEND_OWNED_PROSE_KEYS


def _strip_backend_owned_prose(text: str) -> str:
    """Drop whole lines reproducing the backend's own fixed prose. Marker-bearing lines are never touched."""
    keys = _backend_owned_prose_keys()
    kept: list[str] = []
    dropped: list[str] = []
    for line in text.splitlines():
        if not ANY_MARKER_RE.search(line) and _rendered_line_key(line) in keys:
            dropped.append(line.strip())
            continue
        kept.append(line)
    if not dropped:
        return text
    logger.warning("HYROX: stripped model line(s) imitating backend-owned text: %s", dropped)
    return "\n".join(kept)


def drop_lines_duplicating(body: Optional[str], rendered: list[str]) -> str:
    """Remove from the MODEL's text every line that repeats a line the backend renders into this same
    message.

    This is the structural guarantee behind the shape-based rules in ``strip_rendered_numbers``: the
    backend knows exactly which lines it is about to render, so any copy of one of them in the model's text
    is deleted before assembly — even in a shape no regex anticipated. That makes a visibly duplicated
    backend line (the reported "**Question 2: 4/4**" printed twice) impossible by construction rather than
    by pattern coverage. Lines carrying a control marker are never touched, so ``[[SCORE]]``/``[[SUMMARY]]``
    always survive.
    """
    if not body:
        return body or ""
    targets = {
        key
        for block in rendered
        for key in (_rendered_line_key(line) for line in (block or "").splitlines())
        if key
    }
    if not targets:
        return body
    kept: list[str] = []
    dropped: list[str] = []
    for line in body.splitlines():
        if not ANY_MARKER_RE.search(line) and _rendered_line_key(line) in targets:
            dropped.append(line.strip())
            continue
        kept.append(line)
    if not dropped:
        return body
    logger.warning("HYROX: dropped model line(s) duplicating a backend-rendered line: %s", dropped)
    cleaned = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", "\n".join(kept))
    return cleaned.strip()


def sanitize_history_for_model(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return ``messages`` with the backend's own artefacts removed from each prior ASSISTANT turn — for
    the copy of the history that is sent to the LLM.

    The model imitates what it sees itself having written. Because the backend renders its numbers INTO the
    stored assistant message, every replayed turn showed the model a "**Question N: s/m**" score line, a
    "Question N of M" header, and module-result lines and control markers over its own signature — and it
    eventually copied them (four production sessions printed the per-question score line twice; roughly 8%
    of module boundaries grew a faked ``[[MODPASS]]``). Removing the backend-owned lines and
    backend-only markers from the LLM's view eliminates the imitation stimulus at the source, so the render
    guards downstream act as a safety net instead of the only defence.

    Only the model's copy is sanitized: ``derive_turn_state`` and ``record_assessment_session`` keep the
    full marker-bearing history, so state reconstruction and the stored transcript are unchanged. The model
    needs none of it — ``build_state_injection`` restates the module, the counter, the pinned question, and
    its rubric authoritatively on every turn. The model's own channels (``[[SCORE]]``, ``[[ASK]]``,
    ``[[SUMMARY]]``) are left in place, as is all visible prose.
    """
    sanitized: list[dict[str, Any]] = []
    for message in messages or []:
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(message, dict) or message.get("role") != "assistant" or not isinstance(content, str):
            sanitized.append(message)
            continue
        cleaned = strip_rendered_numbers(FORBIDDEN_MODEL_MARKER_RE.sub("", content))
        # A turn that sanitizes to nothing at all cannot happen in practice (every assistant turn carries
        # question text or feedback); keep the original rather than send an empty assistant message.
        sanitized.append({**message, "content": cleaned} if cleaned and cleaned != content else message)
    return sanitized


def strip_forbidden_model_markers(text: Optional[str]) -> str:
    """Remove control markers only the backend may author ([[PLAN]]/[[MODULE]]/[[MODPASS]]/[[MODFAIL]]/
    [[PROGRESS]]/[[DONE]]/[[ASKED]]/[[BREAK]]) from the MODEL's output before assembly, so a model-faked
    marker can never persist into stored history and corrupt the replayed state (see
    FORBIDDEN_MODEL_MARKER_RE). Applied to the model body only — the backend appends its own authoritative
    markers afterwards."""
    if not text:
        return text or ""
    found = FORBIDDEN_MODEL_MARKER_RE.findall(text)
    if not found:
        return text
    logger.warning("HYROX: stripped %d model-authored control marker(s) from model output: %s", len(found), found)
    cleaned = FORBIDDEN_MODEL_MARKER_RE.sub("", text)
    cleaned = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", cleaned)
    return cleaned.strip()


def ensure_non_empty(assembled: str, fallback: str) -> str:
    """Guarantee the turn has visible text, prepending ``fallback`` when it does not.

    A rendered turn must NEVER be empty. Every hidden marker is display-stripped by the frontend, so an
    assembled message of markers-only — or of nothing at all — reaches the learner as a blank chat bubble
    with no way forward. That happened whenever the model and the backend both concluded the other side
    was writing the turn: the model writes nothing for a message it judges a refusal (as instructed), so a
    refusal the backend did not recognise ("idk", reported 2026-07-29) left neither side authoring
    anything, on that turn and on every retry.

    Markers are preserved — the fallback is prepended, never substituted — so state still replays.
    """
    if strip_markers(assembled).strip():
        return assembled
    logger.warning("HYROX: turn rendered no visible text; substituting the fallback line")
    return ((fallback + "\n\n" + assembled) if assembled.strip() else fallback).strip()


def strip_markers(text: Optional[str]) -> str:
    """Remove all hidden control markers from text (defense in depth; the frontend also hides them)."""
    if not text:
        return text or ""
    cleaned = ANY_MARKER_RE.sub("", text)
    cleaned = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", cleaned)
    return cleaned.strip()


# Defense in depth against the model writing visible question text. The backend renders every question
# itself; the model is told to write none. We strip any model paragraph that reproduces a pool question.
_LEAKED_QUESTION_MATCH_THRESHOLD = 0.8
_MIN_QUESTION_MATCH_CHARS = 40
_PARAGRAPH_SPLIT_RE = re.compile(r"\n[ \t]*\n")


def _normalize_for_match(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


_NORMALIZED_POOL_QUESTIONS: list[str] = [_normalize_for_match(q["question"]) for q in QUESTIONS]


def paragraph_reproduces_pool_question(paragraph: str) -> bool:
    """True when ``paragraph`` reproduces one of the pool questions — verbatim or lightly reworded."""
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
    """Drop any model-authored paragraph that reproduces a pool question. Paragraphs containing a control
    marker are preserved untouched so [[SCORE]]/[[ASK]]/[[SUMMARY]] still replay."""
    if not text:
        return text or ""
    kept: list[str] = []
    for paragraph in _PARAGRAPH_SPLIT_RE.split(text):
        if ANY_MARKER_RE.search(paragraph) or not paragraph_reproduces_pool_question(paragraph):
            kept.append(paragraph)
    cleaned = "\n\n".join(kept)
    cleaned = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", cleaned)
    return cleaned.strip()


def _module_display(module_key: str, language: Optional[str] = None) -> str:
    """'M7.1' -> 'Module 7.1' / 'Modul 7.1' (localized module word)."""
    L = _locale(language)
    return f"{L['module_word']} {module_key.lstrip('M')}" if module_key else ""


def render_progress_header(position: int, module_total: int, language: Optional[str] = None) -> str:
    L = _locale(language)
    return L["header"].format(n=position, total=module_total)


def render_question_text(question_id: Optional[int]) -> str:
    if question_id is None:
        return ""
    question = get_question(question_id)
    return str(question.get("question", "")).strip() if question else ""


def render_question_block(
    position: int,
    module_total: int,
    question_id: Optional[int],
    module_key: str,
    with_module_heading: bool,
    language: Optional[str] = None,
) -> str:
    header = render_progress_header(position, module_total, language)
    if with_module_heading:
        header = f"**{_module_display(module_key, language)}**\n\n{header}"
    question_text = render_question_text(question_id)
    return f"{header}\n{question_text}" if question_text else header


def render_question_score(position: int, awarded: int, maximum: int, language: Optional[str] = None) -> str:
    """The score for a single question, shown once it is graded (e.g. "Question 1: 4/6")."""
    L = _locale(language)
    return L["question_score"].format(n=position, s=awarded, m=maximum)


def render_module_result(module_key: str, tally: dict[str, Any], language: Optional[str] = None) -> str:
    L = _locale(language)
    key = "module_result_passed" if tally["passed"] else "module_result_failed"
    return L[key].format(module=_module_display(module_key, language), s=tally["score"], m=tally["max"], p=tally["pct"])


def render_module_pass_transition(module_key: str, language: Optional[str] = None) -> str:
    """Transitional text shown when a (non-final) module is passed, ending with the continue question."""
    L = _locale(language)
    lines = L["module_pass_lines"]
    from approaches.chatbots.hyrox_assessment.questions import module_index

    idx = module_index(module_key)
    line = lines[idx % len(lines)] if lines else ""
    return f"{line}\n\n{L['continue_prompt']}".strip()


def render_module_fail_transition(language: Optional[str] = None) -> str:
    L = _locale(language)
    # module_fail_text now carries the full fail message, including the closing retake call-to-action as
    # its final bullet, so nothing further is appended here.
    return L["module_fail_text"]


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    """De-duplicate case-insensitively while keeping first-seen order (key-point phrasings repeat across
    a module's questions, e.g. 'Practical coaching example')."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.lower()
        if item and key not in seen:
            seen.add(key)
            out.append(item)
    return out


def module_topic_breakdown(scores: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """The key-point topics the learner earned (strengths) vs missed (worth revisiting) over the given
    ``scores``, read straight from the per-key-point 0/1 verdicts. Topics come from ``questions.py`` (the
    authoritative rubric), de-duplicated and in question/key-point order. Fed one module's scores for a
    per-module view, or every module's scores for the cross-module ``render_topic_summary``."""
    earned: list[str] = []
    missed: list[str] = []
    for s in scores:
        qid = s.get("q")
        if not isinstance(qid, int):
            continue
        question = get_question(qid)
        if not question:
            continue
        key_points = question.get("key_points") or []
        for i, verdict in enumerate(s.get("points", [])):
            if i >= len(key_points):
                break
            topic = str(key_points[i]).strip()
            (earned if verdict else missed).append(topic)
    return _dedupe_preserve_order(earned), _dedupe_preserve_order(missed)


def render_topic_summary(
    module_results: list[tuple[str, list[dict[str, Any]]]], language: Optional[str] = None
) -> str:
    """Deterministic topic-wise take-aways shown at completion, aggregated **across all modules** (not
    per module): one Strengths list of the key-point topics the learner earned and one Worth-revisiting
    list of the topics they missed. It is built entirely from the per-key-point 0/1 verdicts the backend
    already reconstructed, mapped to the ``questions.py`` rubric topics, so it never depends on the model
    and never mis-states a result. A topic the learner missed anywhere is listed only as worth revisiting
    even if earned elsewhere, so the two lists stay disjoint and the guidance stays honest. Naming missed
    key points is allowed at this point: it is end-of-assessment guidance, after every module has been
    passed."""
    L = _locale(language)
    all_scores = [s for _, scores in module_results for s in scores]
    earned, missed = module_topic_breakdown(all_scores)
    missed_keys = {t.lower() for t in missed}
    earned = [t for t in earned if t.lower() not in missed_keys]
    blocks = [L["summary_heading"]]
    if earned:
        blocks.append(L["summary_strengths"] + "\n" + "\n".join(f"- {t}" for t in earned))
    if missed:
        blocks.append(L["summary_revisit"] + "\n" + "\n".join(f"- {t}" for t in missed))
    return "\n\n".join(blocks)


def render_completion_bubbles(
    body: str,
    score_line: str,
    module_results: list[tuple[str, list[dict[str, Any]]]],
    overall_tally: dict[str, Any],
    language: Optional[str] = None,
    score_marker_text: str = "",
) -> str:
    """Assemble the end-of-assessment message as [[BREAK]]-separated display bubbles:

    1. the final question's score + the model's feedback on that answer,
    2. the FINAL module's own result line ("Module N complete — s/m (p%). Passed."), exactly like every
       non-final module (which renders it via render_module_end_bubbles), so the last module is not the only
       one without an explicit per-module completion line,
    3. the cumulative result across all modules (always a pass — a module is only left by passing it),
    4. the general take-aways summary across all modules — the model's text after its [[SUMMARY]] token
       (strengths / worth revisiting), or the deterministic topic-wise fallback when that token is missing,
    5. the motivational message,
    6. the closing message (certificate notice).

    The hidden [[SCORE]] marker (``score_marker_text``, the backend's canonical form — falling back to one
    found in ``body`` for direct callers) is re-appended at the very end so it still replays. The model
    writes the take-aways after [[SUMMARY]]; the backend owns the heading and every number, and if the model
    omits [[SUMMARY]] the learner still gets the deterministic topic-wise summary.
    """
    L = _locale(language)

    if not score_marker_text:
        score_marker = SCORE_MARKER_RE.search(body)
        score_marker_text = score_marker.group(0) if score_marker else ""
    cleaned = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", SCORE_MARKER_RE.sub("", body)).strip()

    feedback, *summary_rest = SUMMARY_TOKEN_RE.split(cleaned, maxsplit=1)
    feedback = feedback.strip()
    model_takeaways = SUMMARY_TOKEN_RE.sub("", summary_rest[0]).strip() if summary_rest else ""

    complete_line = L["complete_result"].format(s=overall_tally["score"], m=overall_tally["max"], p=overall_tally["pct"])
    # The FINAL module gets its own "Module N complete — s/m (p%). Passed." line before the cross-module
    # result, exactly like every non-final module (render_module_end_bubbles). Without it the last module
    # would be the only one with no explicit per-module completion line. module_results[-1] is always the
    # final module attempt — the caller appends (cur_mod, module_scores) last — and it is always a pass
    # (completion requires clearing the last module at the 80% threshold).
    final_module_result = ""
    if module_results:
        final_module_key, final_module_scores = module_results[-1]
        final_module_result = render_module_result(final_module_key, compute_tally(final_module_scores), language)

    # No line the backend renders into this message may also appear in the model's own text — including the
    # summary heading it must never write above its take-aways (see drop_lines_duplicating).
    backend_lines = [
        score_line,
        final_module_result,
        complete_line,
        L["summary_heading"],
        L["motivational_passed"],
        L["closing_passed"],
    ]
    feedback = drop_lines_duplicating(feedback, backend_lines)
    model_takeaways = drop_lines_duplicating(model_takeaways, backend_lines)
    # Backend owns the heading; the model authors only the strengths/worth-revisiting body. When the model
    # omits [[SUMMARY]], fall back to the deterministic topic-wise summary so a summary always appears.
    summary = f"{L['summary_heading']}\n\n{model_takeaways}" if model_takeaways else render_topic_summary(
        module_results, language
    )
    bubbles = [
        "\n\n".join(part for part in (score_line, feedback) if part),
        final_module_result,
        complete_line,
        summary,
        L["motivational_passed"],
        L["closing_passed"],
    ]
    assembled = BUBBLE_BREAK_SEPARATOR.join(bubble for bubble in bubbles if bubble)
    if score_marker_text:
        assembled = f"{assembled}\n\n{score_marker_text}"
    return assembled


def render_module_end_bubbles(
    body: str,
    score_line: str,
    module_key: str,
    module_tally: dict[str, Any],
    language: Optional[str] = None,
    score_marker_text: str = "",
) -> str:
    """Assemble a (non-final) module-boundary message as [[BREAK]]-separated bubbles: the final question's
    score + feedback, then the module result + the pass/fail transition. The hidden [[SCORE]] marker
    (``score_marker_text``, the backend's canonical form — falling back to one found in ``body`` for direct
    callers) is re-appended so it replays."""
    if not score_marker_text:
        score_marker = SCORE_MARKER_RE.search(body)
        score_marker_text = score_marker.group(0) if score_marker else ""
    feedback = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", SCORE_MARKER_RE.sub("", body)).strip()

    if module_tally["passed"]:
        transition = render_module_pass_transition(module_key, language)
    else:
        transition = render_module_fail_transition(language)
    module_result = render_module_result(module_key, module_tally, language)
    # No line the backend renders into this message may also appear in the model's own text — the score
    # line, the module result, and the transition text it is told never to write.
    feedback = drop_lines_duplicating(feedback, [score_line, module_result, transition])

    bubbles = [
        "\n\n".join(part for part in (score_line, feedback) if part),
        "\n\n".join(part for part in (module_result, transition) if part),
    ]
    assembled = BUBBLE_BREAK_SEPARATOR.join(bubble for bubble in bubbles if bubble)
    if score_marker_text:
        assembled = f"{assembled}\n\n{score_marker_text}"
    return assembled


def _render_owed_module_boundary(
    state: dict[str, Any], language: Optional[str] = None
) -> tuple[str, list[dict[str, Any]], dict[str, Any], bool]:
    """Render the module boundary a fully-graded module attempt is owed but never got.

    This is the recovery half of the state-driven boundary: ``derive_turn_state`` detects that every
    question of the current attempt carries a ``[[SCORE]]`` while no ``[[MODPASS]]``/``[[MODFAIL]]``/
    ``[[DONE]]`` closed it, and this produces exactly what the finalising turn should have produced —
    the module result plus its transition, or, for a passed FINAL module, the complete end-of-assessment
    sequence with ``[[DONE]]`` + ``[[PROGRESS]]`` so the LMS hand-off and certificate still happen.

    The model's text for the turn is discarded: it had nothing to grade, it was told to write nothing, and
    anything it did write about a result is invented (this state is reached precisely when a fabricated
    boundary bubble is what the learner is looking at). The per-question score line is omitted too — the
    question it belongs to was already finalised and shown on an earlier turn.
    """
    cur_mod = state["current_module"]
    module_scores = list(state.get("scores") or [])
    module_tally = compute_tally(module_scores)

    if module_tally["passed"] and state.get("is_final_module"):
        all_results = list(state.get("prior_module_results") or []) + [(cur_mod, module_scores)]
        flat_scores = [s for _, scores in all_results for s in scores]
        overall_tally = compute_tally(flat_scores)
        assembled = render_completion_bubbles("", "", all_results, overall_tally, language)
        assembled = (assembled + "\n\n" + "\n".join([DONE_MARKER, PROGRESS_MARKER])).strip()
        return assembled, flat_scores, overall_tally, True

    assembled = render_module_end_bubbles("", "", cur_mod, module_tally, language)
    boundary = format_modpass_marker(cur_mod) if module_tally["passed"] else format_modfail_marker(cur_mod)
    return (assembled + "\n\n" + boundary).strip(), module_scores, module_tally, False


def render_assessment_turn(
    content: Optional[str],
    state: dict[str, Any],
    language: Optional[str] = None,
) -> tuple[str, list[dict[str, Any]], dict[str, Any], bool]:
    """Post-process one assistant message for the module-by-module assessment.

    Returns ``(content, all_scores, tally, just_completed)``. ``just_completed`` is True only on the turn
    the FINAL module is passed (the whole assessment is complete); on that turn ``all_scores``/``tally`` are
    the cross-module totals so the result log/LMS report is built from the full assessment.
    """
    body = strip_rendered_numbers(content)
    body = strip_forbidden_model_markers(body)
    body = strip_leaked_question_text(body)

    if state.get("assessment_complete"):
        # Terminal turn (post-completion chatter): nothing to render, no markers. The model's whole reply
        # can still be stripped away here (it likes to repeat the closing/certificate text, which is
        # backend-owned prose), so fall back rather than show a blank bubble.
        terminal = ensure_non_empty(strip_rendered_numbers(body), _locale(language)["already_complete_note"])
        return terminal, [], compute_tally([]), False

    if state.get("module_attempt_complete"):
        # The boundary this module attempt is owed was never written (see derive_turn_state). Render it now
        # from the scores already in history — the same output the finalising turn should have produced,
        # minus the per-question score line and the model's feedback, both of which the learner already saw.
        return _render_owed_module_boundary(state, language)

    if state.get("current_id") is None:
        # No question in play and no boundary owed (a module with no questions — defensive only).
        idle = ensure_non_empty(strip_rendered_numbers(body), _locale(language)["answer_not_assessed"])
        return idle, [], compute_tally([]), False

    cur_mod = state["current_module"]
    mod_qs = state.get("module_questions") or module_questions(cur_mod)
    module_total = len(mod_qs)

    current_id = state.get("current_id")
    model_verdict = parse_new_score(content, current_id)
    provisional = state.get("provisional") if isinstance(state.get("provisional"), dict) else None
    answer_pending = bool(state.get("latest_user_answer_pending"))
    substantive_attempts = int(state.get("substantive_attempts_for_current", 0) or 0)
    latest_is_decline = bool(state.get("latest_answer_is_decline"))
    correction_already_offered = bool(state.get("correction_or_repeat_already_sent"))

    # --- Resolve the verdict for the current question -------------------------------------------------
    # The BACKEND owns every decision here: what the answer scored, whether that finalises the question or
    # triggers the learner's single correction, and — on the two paths where the model has nothing new to
    # judge — the visible message as well. The model only ever contributes a per-key-point judgement of an
    # actual answer; it no longer decides whether to finalise, and its judgement of a given answer is pinned
    # the first time it is made so it cannot drift upward on a later turn.
    new_score: Optional[dict[str, Any]] = None  # set only when THIS turn finalises the question
    pending_provisional: Optional[dict[str, Any]] = None  # set only when the correction is offered now
    correction_offer_text = ""
    backend_feedback = ""  # replaces the model's body where the model had nothing to judge
    if answer_pending and current_id is not None:
        if substantive_attempts == 0:
            # A refusal or skip is not an answer, so it can never earn a point no matter what the model
            # claims. In production a learner replied "no" and was awarded FULL marks together with the
            # invented praise "you covered the whole-body postural demand well". The learner still gets
            # their one opportunity: the first refusal offers it, a second finalises at zero.
            verdict = zero_verdict(current_id)
            if model_verdict is not None and int(model_verdict.get("awarded", 0) or 0) > 0:
                logger.warning(
                    "HYROX q=%s: model awarded %s point(s) for a non-answer; forcing 0",
                    current_id,
                    model_verdict.get("awarded"),
                )
            backend_feedback = _locale(language)[
                "no_answer_zero" if correction_already_offered else "answer_offer_no_attempt"
            ]
            if correction_already_offered:
                new_score = verdict
            else:
                pending_provisional = verdict
        elif latest_is_decline and provisional is not None:
            # The learner declined to revise, so there is nothing new to grade and the verdict pinned when
            # the correction was offered is final. Re-grading the same unchanged answer here is exactly how a
            # production learner went from "one key part is still missing" to FULL marks in a single turn.
            if model_verdict is not None and model_verdict.get("points") != provisional.get("points"):
                logger.warning(
                    "HYROX q=%s: model re-graded a declined correction as %s vs the pinned %s; keeping the pinned "
                    "verdict",
                    current_id,
                    model_verdict.get("points"),
                    provisional.get("points"),
                )
            new_score = provisional
            backend_feedback = _locale(language)["decline_keeps_answer"]
        elif model_verdict is not None:
            # A real answer was graded. A key point the first attempt already earned can never be lost by
            # revising (the "better of the two attempts" rule, computed here rather than trusted to the model).
            verdict = merge_best_verdicts(provisional, model_verdict) if provisional else model_verdict
            if (
                int(verdict.get("awarded", 0) or 0) >= int(verdict.get("max", 0) or 0)
                or correction_already_offered
            ):
                new_score = verdict
            else:
                # Below full marks with the correction unused: pin this verdict and offer the correction.
                pending_provisional = verdict
                correction_offer_text = _locale(language)["correction_offer"]
        else:
            # The model graded nothing on a turn where it was told to. The question simply stays open; the
            # counter cannot advance on an unscored answer, and nothing is finalised from here — an answer
            # the model never judged must never be scored by guesswork.
            #
            # The model's own text is deliberately NOT replaced on this path: it legitimately lands here
            # when it declines an off-topic question and steers the learner back ("I can only handle the
            # current assessment question"), and that reply must still reach them. When it wrote nothing at
            # all, ensure_non_empty below supplies the fallback line — that is the blank bubble's fix.
            logger.warning("HYROX q=%s: no [[SCORE]] verdict in a grading turn; question stays open", current_id)
    if backend_feedback:
        # The model's own text is discarded on these paths: it had no answer to assess, so anything it wrote
        # about one is invented and would contradict the score the backend just decided.
        body = backend_feedback

    module_scores = list(state.get("scores", []))
    if new_score is not None:
        module_scores = [s for s in module_scores if s["q"] != new_score["q"]] + [new_score]
    n_after = len(module_scores)

    asked_question_id: Optional[int] = None
    module_is_new = bool(state.get("module_is_new"))

    # 1) Ask the module's first question (run start / advance / retry).
    should_backend_render_question = (
        new_score is None and not state.get("current_question_asked") and state.get("current_id") is not None
    )

    just_completed = False
    module_tally = compute_tally(module_scores)

    # Premature-ending guard (finalisation path). The below-full guard above cut any ending on a discarded
    # first answer; this also cuts a summary/take-aways the model volunteered when it *legitimately*
    # finalised a question that is NOT the final-module completion (e.g. a full-marks answer on a non-final
    # question — the reported Module-10 leak). Only the true completion turn keeps the ending, so
    # render_completion_bubbles can consume it.
    is_completion_turn = (
        new_score is not None
        and n_after >= module_total
        and module_tally["passed"]
        and bool(state.get("is_final_module"))
    )
    if not is_completion_turn:
        body = cut_premature_ending(body)

    # The model's own [[SCORE]] text NEVER survives into the stored message. The backend re-appends either
    # its canonical finalised marker or a [[PROV]] pin, according to what it decided above — a verbatim model
    # marker could carry a wrong ``q`` (permanently desyncing the module counter, see format_score_marker) or
    # finalise a question the backend deliberately kept open for the correction.
    if SCORE_MARKER_RE.search(body):
        # Re-strip the rendered numbers afterwards: an imitated score line sharing its line with the marker
        # is not a whole-line match until the marker is gone.
        body = strip_rendered_numbers(SCORE_MARKER_RE.sub("", body))
    canonical_score_marker = format_score_marker(new_score) if new_score is not None else ""

    if should_backend_render_question:
        asked_question_id = state["current_id"]
        question_block = render_question_block(
            position=n_after + 1,
            module_total=module_total,
            question_id=asked_question_id,
            module_key=cur_mod,
            with_module_heading=True,
            language=language,
        )
        body = drop_lines_duplicating(body, [question_block])
        ask_match = ASK_TOKEN_RE.search(body)
        prefix = body[: ask_match.start()].strip() if ask_match else ""
        body = ASK_TOKEN_RE.sub("", body)
        assembled = "\n\n".join(p for p in (prefix, question_block) if p) if prefix else question_block
    else:
        body = ASK_TOKEN_RE.sub("", body)
        if new_score is not None and n_after >= module_total:
            # 2) Module attempt complete — evaluate against the 80% threshold.
            score_line = render_question_score(n_after, new_score["awarded"], new_score["max"], language)
            if module_tally["passed"] and state.get("is_final_module"):
                # Final completion: build the cross-module totals and the end sequence.
                all_results = list(state.get("prior_module_results", [])) + [(cur_mod, module_scores)]
                flat_scores = [s for _, scores in all_results for s in scores]
                overall_tally = compute_tally(flat_scores)
                assembled = render_completion_bubbles(
                    body, score_line, all_results, overall_tally, language, canonical_score_marker
                )
                trailing = [DONE_MARKER, PROGRESS_MARKER]
                assembled = (assembled + "\n\n" + "\n".join(trailing)).strip()
                return assembled, flat_scores, overall_tally, True
            # Non-final module boundary (pass→continue, or fail→retry).
            assembled = render_module_end_bubbles(
                body, score_line, cur_mod, module_tally, language, canonical_score_marker
            )
        else:
            # 3) Mid-module: grade-first feedback, or finalise + auto-chain the next question.
            score_line = (
                render_question_score(n_after, new_score["awarded"], new_score["max"], language)
                if new_score is not None
                else ""
            )
            next_question_block = ""
            if new_score is not None and n_after < module_total:
                next_id = mod_qs[n_after]
                asked_question_id = next_id
                next_question_block = render_question_block(
                    position=n_after + 1,
                    module_total=module_total,
                    question_id=next_id,
                    module_key=cur_mod,
                    with_module_heading=False,
                    language=language,
                )
            # This is the turn that produced the reported duplicate: the backend prepends its score line
            # and the model had copied the same line into its feedback. Drop any copy of a line the backend
            # renders here before assembling, so each appears exactly once.
            body = drop_lines_duplicating(body, [score_line, next_question_block, correction_offer_text])
            parts: list[str] = [p for p in (score_line, body) if p]
            if correction_offer_text:
                parts.append(correction_offer_text)
            if next_question_block:
                parts.append(next_question_block)
            assembled = "\n\n".join(p for p in parts if p)

    # Never ship a blank bubble. Applied before the trailing markers so the fallback is visible text rather
    # than a message that only looks non-empty because a hidden marker was appended to it.
    assembled = ensure_non_empty(assembled, _locale(language)["answer_not_assessed"])

    # Trailing hidden markers (replay into history).
    trailing: list[str] = []
    if state.get("plan_is_new"):
        trailing.append(format_plan_marker())
    if module_is_new:
        trailing.append(format_module_marker(cur_mod, int(state.get("attempt", 1))))
    if asked_question_id is not None:
        trailing.append(format_asked_marker(asked_question_id))
    if pending_provisional is not None:
        # Pin the verdict for the answer the correction was just offered on, so the decline path finalises
        # from this record instead of re-grading (and so a revision can only improve on it).
        trailing.append(format_prov_marker(pending_provisional))
    if new_score is not None and n_after < module_total:
        # Mid-module finalisation: replay the canonical score marker here (module-boundary and completion
        # messages embed it via render_module_end_bubbles / render_completion_bubbles instead).
        trailing.append(canonical_score_marker)
    if new_score is not None and n_after >= module_total:
        # Module boundary (non-final): MODPASS on a pass (frontend shows Continue), MODFAIL on a fail
        # (frontend shows Retry).
        trailing.append(format_modpass_marker(cur_mod) if module_tally["passed"] else format_modfail_marker(cur_mod))
    if trailing:
        assembled = (assembled + "\n\n" + "\n".join(trailing)).strip()

    return assembled, module_scores, module_tally, just_completed


# --- session logging + LMS stub -------------------------------------------------------
#
# EVERY assessment turn upserts ONE blob per session:
#     hyrox-assessment-logs/<account_id>/<session_id>.json
# rewritten in place as the run progresses. Because the whole conversation is replayed to the model on
# each request, the latest write always holds the complete transcript — so a run that is abandoned
# mid-module is still fully on record. (Until 2026-07-28 a log was written only when the FINAL module was
# passed, which left every incomplete run with no server-side trace whatsoever: the transcript lived only
# in the learner's own browser, so an abandoned session was unrecoverable.) Sessions launched outside the
# Lemon LMS carry no account_id and bucket under `anonymous/`.
ASSESSMENT_LOG_PREFIX = "hyrox-assessment-logs"
ANONYMOUS_LOG_BUCKET = "anonymous"
# Blob path segments are built from caller-supplied ids; keep them to characters that need no escaping.
BLOB_SEGMENT_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]")


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
    """Build the result payload the LMS will consume (always a pass at completion → certificate)."""
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
        "module_breakdown": module_breakdown(scores),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }


def report_result_to_lms(payload: dict[str, Any]) -> None:
    """STUB: hand the assessment result to the Lemon LMS. Lemon owns the real interface; until that is
    defined, this logs the payload so the result is observable and the wiring point is unambiguous."""
    logger.info("HYROX assessment result (LMS report stub): %s", json.dumps(payload, ensure_ascii=False))


def session_log_blob_name(session_id: Optional[str], account_id: Any) -> str:
    """``hyrox-assessment-logs/<account_id>/<session_id>.json`` — one blob per session, grouped by learner
    so every session of one account (finished or abandoned) is listable with a single prefix query. The
    name is stable for the life of the session: each turn overwrites it."""

    def segment(value: Any, fallback: str) -> str:
        text = str(value).strip() if value not in (None, "") else ""
        return BLOB_SEGMENT_UNSAFE_RE.sub("_", text) or fallback

    # A missing session_id means both chat-history modes are disabled, so nothing distinguishes two runs
    # by the same learner; they share the `unkeyed` blob rather than being dropped.
    return f"{ASSESSMENT_LOG_PREFIX}/{segment(account_id, ANONYMOUS_LOG_BUCKET)}/{segment(session_id, 'unkeyed')}.json"


def run_scores_so_far(
    state: dict[str, Any], turn_scores: list[dict[str, Any]], completed: bool
) -> list[dict[str, Any]]:
    """Cross-module scores for the whole run as of this turn. ``render_assessment_turn`` returns only the
    CURRENT module attempt's scores on an ordinary turn (the completion turn already flattens across every
    module), so the earlier modules are prepended from the derived state."""
    if completed:
        return list(turn_scores or [])
    prior = list(state.get("prior_module_results") or [])
    return [score for _, module_scores in prior for score in module_scores] + list(turn_scores or [])


def build_session_log_record(
    *,
    state: dict[str, Any],
    run_scores: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    final_content: Optional[str],
    overrides: dict[str, Any],
    auth_claims: dict[str, Any],
    session_id: Optional[str],
    completed: bool,
) -> dict[str, Any]:
    """The full session log for this turn: identity, run status, progress, per-question scores, and the
    entire conversation. Written for in-progress runs too, so ``status`` is what distinguishes them."""
    account_id = overrides.get("account_id")
    now = datetime.now(timezone.utc).isoformat()
    tally = compute_tally(run_scores)
    current_module = state.get("current_module")
    transcript = [
        {"role": m.get("role"), "content": m.get("content")}
        for m in (messages or [])
        if isinstance(m, dict) and isinstance(m.get("content"), str)
    ]
    if isinstance(final_content, str):
        transcript.append({"role": "assistant", "content": final_content})

    return {
        "session_id": session_id,
        "user_id": auth_claims.get("oid") or account_id or overrides.get("user"),
        "account_id": account_id,
        "first_name": overrides.get("first_name"),
        "last_name": overrides.get("last_name"),
        "language": overrides.get("language"),
        "status": "completed" if completed else "in_progress",
        "completed": completed,
        # A module is only ever left by passing it, so finishing the assessment means passing every
        # module; an in-progress run is never reported as passed no matter how well it is scoring.
        "passed": bool(completed and tally["passed"]),
        "updated_at": now,
        "completed_at": now if completed else None,
        # Running totals over the questions finalised SO FAR — on an in-progress run `percent` is
        # accuracy to date, NOT progress through the assessment (that lives under `progress`).
        "score": tally["score"],
        "max": tally["max"],
        "percent": tally["pct"],
        "pass_threshold_percent": PASS_THRESHOLD_PERCENT,
        "progress": {
            "current_module": current_module,
            # 1-based for reading; `module_index` is 0-based and yields -1 for an unknown module.
            "current_module_position": (module_index(current_module) + 1) if current_module else None,
            "current_module_attempt": int(state.get("attempt") or 0),
            "modules_passed": len(MODULES) if completed else len(list(state.get("prior_module_results") or [])),
            "modules_total": len(MODULES),
            "questions_finalised_in_module": len([s for s in run_scores if s.get("mod") == current_module]),
            "questions_in_module": len(state.get("module_questions") or []),
            "questions_finalised_total": len(run_scores),
            "questions_total": TOTAL_QUESTIONS,
            "points_possible_total": TOTAL_MAX_POINTS,
        },
        "module_breakdown": module_breakdown(run_scores),
        "scores": run_scores,
        "transcript": transcript,
    }


async def record_assessment_session(
    *,
    state: Optional[dict[str, Any]],
    scores: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    final_content: Optional[str],
    overrides: dict[str, Any],
    auth_claims: dict[str, Any],
    session_state: Any,
    blob_manager: Any = None,
    completed: bool = False,
) -> Optional[dict[str, Any]]:
    """Upsert this session's log after EVERY assessment turn; on the completion turn also hand the result
    to the LMS. Called by the chat approach on every assessment turn. Best-effort: never raises into the
    chat flow, and returns the record it wrote (or None when it wrote nothing)."""
    try:
        if state is None:
            return None
        # Terminal / no-op turn: post-completion chatter, or a turn with nothing to grade.
        # ``render_assessment_turn`` returns no scores for these, so writing would replace a finished
        # record with an empty one — skip instead. The completed log already holds the whole run. A turn
        # that renders an owed module boundary is NOT one of these: it carries the attempt's real scores.
        if (
            not completed
            and not state.get("module_attempt_complete")
            and (state.get("assessment_complete") or state.get("current_id") is None)
        ):
            return None

        session_id = session_state if isinstance(session_state, str) else None
        run_scores = run_scores_so_far(state, scores, completed)
        record = build_session_log_record(
            state=state,
            run_scores=run_scores,
            messages=messages,
            final_content=final_content,
            overrides=overrides,
            auth_claims=auth_claims,
            session_id=session_id,
            completed=completed,
        )
        await _write_session_log(blob_manager, session_log_blob_name(session_id, record["account_id"]), record)

        if completed:
            tally = compute_tally(run_scores)
            report_result_to_lms(
                build_result_payload(
                    session_id=session_id,
                    user_id=record["user_id"],
                    language=record["language"],
                    tally=tally,
                    scores=run_scores,
                    account_id=record["account_id"],
                    first_name=record["first_name"],
                    last_name=record["last_name"],
                )
            )
            logger.info(
                "HYROX assessment finalised: session=%s passed=%s score=%s/%s (%s%%)",
                session_id,
                tally["passed"],
                tally["score"],
                tally["max"],
                tally["pct"],
            )
        return record
    except Exception:  # logging must never break the chat response
        logger.exception("Failed to record HYROX assessment session")
        return None


async def _write_session_log(blob_manager: Any, blob_name: str, record: dict[str, Any]) -> None:
    """Persist the session log to blob storage when a BlobManager is available. ``upload_blob_data``
    uploads with ``overwrite=True``, so the stable per-session name keeps exactly one blob holding the
    latest state of the run."""
    progress = record.get("progress") or {}
    if blob_manager is None or not hasattr(blob_manager, "upload_blob_data"):
        # Summary only: this runs on every turn, so dumping the whole transcript here would flood the log.
        logger.info(
            "HYROX assessment session log (no blob manager) %s: status=%s module=%s questions=%s/%s",
            blob_name,
            record.get("status"),
            progress.get("current_module"),
            progress.get("questions_finalised_total"),
            progress.get("questions_total"),
        )
        return
    data = BytesIO(json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8"))
    try:
        await blob_manager.upload_blob_data(data, blob_name, content_type="application/json")
        logger.info(
            "HYROX assessment session log written: %s (status=%s, %s/%s questions finalised)",
            blob_name,
            record.get("status"),
            progress.get("questions_finalised_total"),
            progress.get("questions_total"),
        )
    except Exception:
        logger.exception("Failed to upload HYROX assessment session log to blob: %s", blob_name)
