<!-- markdownlint-disable MD024 -->
# Project changes log

Reverse chronological. Newest entries at the top.

Maintained by coding agents: at the end of any session that produced file
edits or recorded design decisions, append a new dated entry here before
signing off.

Two categories per date:

- **Decisions** — design choices, scope changes, "things we explicitly chose
  not to do". The *why*, which can't be recovered from a diff.
- **Changes** — file edits, creations, deletions. The *what*.

---

## 2026-06-05

### Decisions

- **Fixed a give-up/meta false-positive that was the *real* cause of "scored
  without a chance to revise" — a different bug from the 2026-06-04 work.** A
  learner's 57-word genuine answer to Q11 was finalised 4/5 with no correction
  offer because it contained the phrase "before the **next** attempt".
  `_GIVE_UP_OR_META_RE` (which detects "skip"/"next"/"I don't know"/"move on"
  /"again"/…) matched the bare word "next" anywhere in the text, so
  `_current_question_interaction` set `must_finalize_current=True`. That single
  misclassification defeated **both** prior safeguards at once: the state block
  emitted "FINALISE NOW" instead of the mandatory-correction branch (Part A), and
  because `is_grade_first = latest_user_answer_pending and not
  must_finalize_current` was now False, the `render_assessment_turn` guard (Part B)
  was bypassed too. So the case was reachable regardless of the 2026-06-04 fix —
  independent of deploy state.
  - **Fix: gate give-up/meta detection on message length.** A genuine give-up/meta
    turn ("next", "skip", "I don't know", "why are you asking?") is short; a
    substantive answer that incidentally contains a trigger word ("…before the next
    attempt", "do it again", "I don't know if X, but…") is long. New
    `is_give_up_or_meta()` returns True only when the message is ≤ `_GIVE_UP_MAX_WORDS`
    (8) **and** matches the pattern; `_current_question_interaction` now calls it
    instead of the raw regex. Erring this way is safe: a genuinely long give-up just
    receives the (declinable) one correction offer first, then finalises on the next
    turn via the existing `answer_attempts>=2 / correction_already_sent` paths.
  - **Known residual (accepted):** a *very short* answer that is itself just a bare
    trigger word (e.g. "run to the next station", ≤8 words containing "next") can
    still be read as a give-up. Rare, low-impact, and such answers score low anyway;
    not worth the added complexity of full-message anchoring for the beta.

### Changes

- `app/backend/approaches/chatbots/hyrox_assessment/results.py`: added
  `_GIVE_UP_MAX_WORDS` + `is_give_up_or_meta()` and switched
  `_current_question_interaction` to use it instead of `_GIVE_UP_OR_META_RE.search`.
- `tests/test_hyrox_assessment.py`: added `test_is_give_up_or_meta_only_matches_short_messages`
  and `test_substantive_first_answer_with_trigger_word_is_not_finalized` (a direct
  regression for the reported "before the next attempt" answer). Full bot suite:
  39 passed; `ty check` clean.

## 2026-06-04

### Decisions

- **`/hyrox-assessment` now ALWAYS offers the one correction when a first answer
  is not full marks.** A learner reported Q4 was scored 3/5 immediately with no
  chance to revise. Root cause: the authoritative `CURRENT TURN STATE` block (P0,
  overrides the static per-question protocol) phrased the first-attempt branch as
  "you **may** offer the single correction opportunity" — so the model was free to
  finalise a partial answer in the same turn. The static prompt's protocol always
  intended "offer **exactly one** correction" when not full marks; the soft "may"
  at the authoritative layer was the deviation. Chosen behaviour: on a first
  attempt, finalise immediately **only** on full marks; otherwise the model MUST
  offer the single correction and MUST NOT emit `[[SCORE]]` that turn. The existing
  state machine already finalises on the next turn (the correction offer sets
  `correction_or_repeat_already_sent → must_finalize_current`), and explicit
  give-ups ("I don't know"/"skip") still finalise immediately via the give-up
  regex — so weak-but-genuine answers get the correction while quitters don't stall.
  (Considered and rejected: a partial-credit threshold to gate the offer, and
  leaving it optional.)

- **Added a deterministic backend guard so premature finalisation is unreachable,
  not just discouraged (defence in depth on top of the instruction change above).**
  The mandatory-correction wording still lives at the prompt layer and trusts the
  model to comply — the same layer that already failed. Consistent with this bot's
  "backend owns enforcement, don't trust the model's arithmetic/compliance"
  philosophy, `render_assessment_turn` now refuses to accept a below-full-marks
  `[[SCORE]]` on a genuine first attempt (GRADE_FIRST: a learner answer is pending
  and `must_finalize_current` is false). When that happens it **discards the score,
  strips the `[[SCORE]]` marker** (so a later stateless replay cannot count it),
  **holds the question open** (no advance, no chained next question, no `[[ASKED]]`
  marker), and **appends a localized correction offer**. Full-marks first answers
  and forced finalisations (GRADE_FINAL — second attempt or explicit give-up) are
  unaffected. This makes the exact "scored 3/5 with no chance to revise" case the
  learner reported impossible regardless of model behaviour; the next turn finalises
  via the existing `must_finalize_current` path. This is a port of a coworker's
  "Part B keystone guard" proposal; "Part A" (explicit per-question phase naming) was
  judged already covered by the existing `derive_turn_state` sub-phase derivation
  plus the wording change, so only the enforcement guard was added.

### Changes

- `app/backend/approaches/chatbots/hyrox_assessment/results.py`:
  - rewrote the first-attempt (non-`must_finalize`) branch of `build_state_injection`
    from a permissive "you may offer" into a mandatory "MUST offer the single
    correction opportunity and MUST NOT finalise this turn / do NOT emit a `[[SCORE]]`".
  - added the premature-finalisation guard in `render_assessment_turn`
    (`is_grade_first` + `awarded < max` → discard score, strip marker, hold position,
    append correction offer) and a `correction_offer` string to the `en`/`de`/`nl`
    locale table.
- `tests/test_hyrox_assessment.py`: strengthened
  `test_build_state_injection_for_answer_pending_forbids_repeating_question` to
  assert the mandatory phrasing, and added three render tests
  (`..._discards_premature_partial_first_score`,
  `..._accepts_full_marks_first_score`,
  `..._accepts_partial_score_when_finalisation_forced`). Full bot suite: 37 passed;
  `ty check` clean.

## 2026-06-03

### Decisions

- **Raised the Free Bot PDF upload size limit from 5 MB to 20 MB.** The existing single-PDF count limit remains unchanged, and the page limit remains disabled for this bot.

### Changes

- Updated backend Free Bot upload enforcement to allow 20 MB total uploaded file size.
- Updated the public-test upload modal client-side validator and EN/DE/NL upload copy from 5 MB to 20 MB.
- Added focused app config coverage for the Free Bot upload manager rules.

## 2026-06-02

### Decisions

- **Auto-advance: `/hyrox-assessment` now presents the next question
  automatically after grading.** Previously a finalisation turn emitted only the
  `[[SCORE]]` + feedback, so the next question appeared only on the *following*
  turn — which forced the learner to send a throwaway message ("next") because
  the bot is stateless and only responds to a user turn. The backend now **chains
  the next pinned question into the same message** as the score (header + exact
  text from `questions.py`), so the learner answers continuously. Everything else
  is unchanged: the chain fires only when a `[[SCORE]]` is finalised this turn and
  the run is not on its last question; a correction-offer turn (no score) does not
  chain, and the 20th question completes instead of chaining. The one-correction
  protocol, counter, no-repeat plan, per-question score, and final tally are
  untouched.
  - **Robust "asked?" tracking via a hidden `[[ASKED q=K]]` marker.** Chaining
    puts the ask in the *same* message as the previous question's `[[SCORE]]`,
    which broke the old message-boundary heuristic for "has this question already
    been asked". The backend now writes a hidden `[[ASKED]]` marker whenever it
    renders a question (standalone or chained), and `derive_turn_state` decides
    ask-vs-grade purely from markers — so the chained question is recognised as
    already presented and is graded, never re-asked. The marker replays in history
    and is hidden by the frontend like the others.

- **`/hyrox-assessment` model updated to `gpt-5.4-mini` / reasoning effort
  `high`** (supersedes the earlier `gpt-5-mini` / `medium` choice; user decision
  for grading quality). `config.py`, the registry metadata, and the config test
  are aligned.

- **Moved `/hyrox-assessment` visible question text fully into the backend.**
  The previous deterministic refactor owned the plan/counter/scoring, but still
  let the LLM write the visible question text after `[[ASK]]` by looking up the
  pinned pool number in the large rubric prompt. In production the model
  displayed Q8 (12-13 standards) while the backend had pinned Q3 (penalty
  system), so the backend correctly graded Q3, advanced, and then displayed the
  actual Q8 next — making Q8 appear repeated. `[[ASK]]` is now only a placement
  token; the backend replaces it with the exact pinned question text from
  `questions.py` and discards any model-written question text.

- **Hardened `/hyrox-assessment` against the repeated-question loop.** The
  deterministic counter was already backend-owned, but the model still had to
  infer from transcript text whether the pinned question had already been asked.
  If it failed that inference, it could emit `[[ASK]]` again instead of
  `[[SCORE]]`; no score marker meant the backend counter correctly stayed on
  the same question, causing the visible repeat. The backend now derives the
  current question phase from replayed roles/markers and injects an explicit
  `ASK` vs `GRADE` vs `FINALISE NOW` action so answered questions are not
  repeated.

- **Refactored `/hyrox-assessment` into a backend-owned deterministic state
  machine.** The first cut was prompt-driven: the LLM chose the 20 questions
  (`[[PLAN]]`), counted "Question N of 20", and computed the running total /
  pass-fail in prose — all of which can hallucinate or mis-add. Because this bot
  issues certificates, ownership of **selection, the counter, aggregation, the
  percentage, and pass/fail moved into the backend** (`results.py`); the LLM now
  only does the irreducibly-model part: ask the one backend-pinned question and
  judge the free-text answer **per key point**.
  - **State is reconstructed from replayed markers each stateless turn.** The
    frontend already replays the raw stored `message.content` (markers hidden at
    render only), so the backend re-derives authoritative state every turn:
    `derive_turn_state` reads the most-recent backend-authored `[[PLAN]]` for the
    fixed 20-of-32 plan and counts `[[SCORE]]` markers after it for the run
    position; `run_until_final_call` injects a "CURRENT TURN STATE" block pinning
    exactly one question; `run_without_streaming` renders the header / running
    total / final verdict itself and strips any numbers the model wrote.
  - **Selection is a balanced random sample of 20/32** (round-robin across the 8
    categories, randomised order), generated once and **persisted in a
    backend-authored `[[PLAN]]` marker** — guaranteeing exactly 20 distinct,
    non-repeating questions independent of LLM behaviour. A failed completed run
    auto-starts a fresh run on the next turn; a passed run is done.
  - **Per-key-point grading:** the model emits `[[SCORE q=K points="1,1,0,1"
    max=Y cat="..."]]` (one 0/1 per key point); the backend computes
    `awarded = min(sum(points), max_pts)` from `questions.py`, validates the
    array length, and forces the pinned `q`. Model-authored `[[PLAN]]`/`[[RESULT]]`
    and any model-written progress numbers are removed.
  - **Model locked to `gpt-5-mini` / reasoning effort `medium`** (user choice;
    medium over low for grading accuracy). **Single** grading pass for the beta
    (no verification pass). Restart is primarily "new session".

- **Built a new `/hyrox-assessment` bot — an interactive knowledge *assessment*,
  not a RAG Q&A bot.** Asks 20 of 32 pooled questions (8 categories), grades
  free-text answers against a stored rubric, gives reduced per-question feedback
  with one correction attempt, and returns binary pass/fail at **80% cumulative**
  plus per-topic take-aways. Realizes the SNAP "nerilio Assessment Function for
  HYROX Youngstars" offer. Modeled on lemon's prompt-driven Tutor Mode.
  - **Q&A pool lives in the system prompt, not the search index.** Grading needs
    the exact rubric for the asked question on every stateless turn; vector
    retrieval can't guarantee that, and selecting/ordering 20-of-32 needs the whole
    pool at once. Stored as a structured data module (`questions.py`) compiled into
    the prompt. The rak CSV-in-index pattern was explicitly rejected as the wrong fit.
  - **Knowledge base is NOT indexed.** The Excel rubric (model answer + required key
    points + accepted alternatives + safeguarding critical-fail) is the self-contained
    grading authority; the course PDF is background only (and is password-protected).
    Retrieval is skipped entirely for this bot.
  - **Scoring via hidden control markers + backend authoritative tally.** The model
    emits `[[PLAN ids=...]]` once, `[[SCORE q=N awarded=X max=Y cat="..."]]` per
    finalized question, and `[[RESULT ...]]` at the end. Markers stay in the message
    so they replay into history (frontend hides them at render, keeping stored content
    raw); the backend re-tallies all `[[SCORE]]` markers itself rather than trusting
    the model's arithmetic. Bot runs **non-streaming** so the full message is parsed
    in one place for the tally + session log.
  - **Session log written now; LMS result reporting stubbed.** `results.py` writes a
    transcript+scores+verdict log to blob on `[[RESULT]]` and calls a documented
    `report_result_to_lms` no-op stub (Lemon owns the real interface).
  - **Branding:** no visible bot name yet (RoxMate kept ready), highlight `#FFED00`,
    Brutal font, Lemon chatbot logo asset reused for the visible bot mark.

### Changes

- Backend `hyrox_assessment/results.py`: `render_assessment_turn` now **auto-chains
  the next pinned question** (header + exact text) right after a `[[SCORE]]`
  finalisation when the run is not on its last question; added the hidden
  `[[ASKED q=K]]` marker (`ASKED_MARKER_RE`, `format_asked_marker`,
  `parse_asked_ids`) and persists it whenever the backend renders a question;
  rewrote `_current_question_interaction` (+ new `_assistant_index_that_asked`,
  removing `_has_plan_score_marker`) to derive the question phase from
  `[[ASKED]]`/`[[SCORE]]` markers instead of message boundaries; `ANY_MARKER_RE`
  and `build_state_injection` (AUTO-NEXT note, only when not the last question)
  updated.
- Backend `hyrox_assessment/sampleprompt.py`: per-question protocol step 4 now
  states the system auto-presents the next question; the model must not write it
  or place `[[ASK]]` on a finalisation message.
- Backend `hyrox_assessment/config.py`: `gpt-5.4-mini` / `reasoning_effort="high"`.
- Frontend `hyrox-assessment/components/Answer/assessmentMarkers.ts`: strips the
  new `[[ASKED ...]]` marker (listed before `ASK` so the `\b` boundary matches the
  whole token).
- Frontend `registry.ts`: hyrox entry → `gpt-5.4-mini` / `high`.
- Tests `tests/test_hyrox_assessment.py`: added `_asked_marker`; updated the
  "answer pending / repeated-question / forbid-repeat" state tests to include the
  `[[ASKED]]` marker the backend now writes; replaced the old "finalisation shows
  score, no header" test with `test_render_assessment_turn_chains_next_question_after_finalization`;
  added the end-to-end auto-advance regression
  `test_chained_next_question_is_recognized_as_asked_not_reasked`; updated the
  config test to `gpt-5.4-mini` / `high`.

- Backend `hyrox_assessment/results.py`: `[[ASK]]` now renders the localized
  progress header plus exact pinned question text from `questions.py`; model
  text after `[[ASK]]` is discarded, and a fresh ask turn without `[[ASK]]`
  still renders the backend-pinned question instead of exposing model-authored
  text.
- Backend `hyrox_assessment/sampleprompt.py`: updated the assessment contract so
  the model never writes, translates, or rephrases visible question text; it only
  places `[[ASK]]` and emits per-key-point `[[SCORE]]` markers.
- Tests `tests/test_hyrox_assessment.py`: added regressions for the observed
  Q3/Q8 mismatch, proving model-authored wrong question text is dropped and the
  backend-pinned question is rendered.

- Frontend `hyrox-assessment`: removed the shared disclaimer banner from
  `Chat.tsx` and removed the now-unused disclaimer locale copy from `en`, `de`,
  and `nl` translations.
- Frontend `hyrox-assessment`: made Brutal the bot-wide font by setting the
  route base font in `index.css` and adding a layout-scoped override for nested
  text, Fluent controls, markdown/code, buttons, and inputs while preserving the
  Fluent icon font.
- Frontend `hyrox-assessment`: narrowed the Brutal override from a universal
  descendant selector to text-bearing elements and excludes Fluent icon glyph
  nodes so their per-icon `FabricMDL2Icons-*` inline font families render copy,
  speech, and menu icons correctly.
- Frontend `hyrox-assessment`: locked UI and bot request language to English by
  removing browser-locale detection from the bot i18n config, registering only
  the English resources/language option, disabling the language-picker wiring,
  and sending `language: "en"` to the backend.

- Backend `hyrox_assessment/results.py`: added current-question interaction
  derivation after the latest plan/score marker, including answer-attempt count,
  correction/repeat detection, skip/give-up/meta detection, and stronger state
  injection that forbids `[[ASK]]` after a learner answer and requires
  finalisation when the loop has already repeated.
- Tests `tests/test_hyrox_assessment.py`: added regressions for answer-pending
  state, repeated-question loop finalisation, and normal transition to the next
  question after a score marker.

- Determinism refactor (backend state machine):
  - `questions.py`: added `QUESTIONS_BY_NUMBER` + accessors `get_question`,
    `key_point_count`, `max_points`, `category_of` (data unchanged).
  - `results.py`: rewritten as the state engine — `select_question_plan`
    (balanced random 20-of-32, deterministic under a seed), `derive_turn_state`
    (plan + score window + counter + tally), per-point `[[SCORE]]` parsing with
    `parse_points`/`normalize_score` (`awarded = min(sum, max_pts)`, length
    validation, forced `q`), localized `render_progress_header`/
    `render_running_total`/`render_final_result`/`render_assessment_turn`,
    `strip_rendered_numbers`, `build_state_injection`, `format_plan_marker`/
    `parse_plan_ids`; `record_assessment_result` now fires on the 20th finalized
    score (no `[[RESULT]]` dependency) from the backend tally.
  - `sampleprompt.py`: rewritten — the model obeys the injected CURRENT TURN
    STATE block, asks only the pinned question, emits the per-key-point `[[SCORE]]`
    marker, and writes no numbers / no `[[PLAN]]`/`[[RESULT]]`.
  - `config.py`: `gpt-5-mini` / `reasoning_effort="medium"`.
  - `approach.py`: `ExtraInfo` gained optional `assessment_state` (threads the
    per-turn state from `run_until_final_call` to `run_without_streaming`).
  - `chatreadretrieveread.py`: hyrox branch derives state + appends the state
    injection to `override_prompt` in `run_until_final_call`; renders the
    authoritative numbers and records on completion in `run_without_streaming`.
  - Frontend `registry.ts`: hyrox entry → `gpt-5-mini` / `medium`
    (`assessmentMarkers.ts` unchanged — strips markers by keyword).
  - `tests/test_hyrox_assessment.py`: rewritten for the engine — plan
    distinctness/balance/determinism, per-point scoring, counter, a simulated
    20-turn run proving exactly-20/no-repeat, fail auto-restart, localized
    rendering, completion trigger (25 tests). `/chat` smoke test retained.
- Display refinement (follow-up):
  - **Removed the running "Score so far" line.** Each question's score is now shown
    once it is graded (`render_question_score`, e.g. "Question 1: 4/6"); the
    cumulative total/percentage is shown only at the very end.
  - **Fixed the question-counter placement bug.** The counter previously advanced on
    the finalisation (feedback-only) message because the backend rendered the header
    on every turn from the score count. Now the model writes an `[[ASK]]` token
    immediately before the question it asks; the backend replaces that token with the
    "Question N of 20" header (N = `n_after`+1), so the header appears right above the
    question and only on a message that actually asks one. `assessmentMarkers.ts` +
    `ASK_TOKEN_RE` updated; `build_state_injection`/`sampleprompt.py` teach the token.
  - **Auto-growing chat input (all chatbot copies).** Enabled Fluent `TextField`
    `autoAdjustHeight` and capped it via the `field` style slot (`maxHeight: 12rem`,
    `overflowY: auto`) across all chatbot `QuestionInput.tsx` copies, so the input grows
    with multi-line/paragraph answers up to a max then scrolls (ChatGPT/Gemini-style).
    The change was originally scoped to `hyrox-assessment`, then propagated to the
    other bot-specific copies.
- Created `hyrox-files/4425-2603 - Lemon Systems - nerilio Assessment - English.pdf`
  from the German source PDF.
- Backend: new `app/backend/approaches/chatbots/hyrox_assessment/` package —
  `questions.py` (32-question pool generated from the xlsx, 167 pts), `sampleprompt.py`
  (assessment flow + grading rules + rendered pool), `config.py` (gpt-5.4-mini, medium,
  override), `results.py` (marker parsing, authoritative tally, session log, LMS stub),
  `__init__.py`.
- Backend: registered `"hyrox-assessment"` in `chatbot_prompt_registry.py`
  (config auto-discovers via the `-`→`_` folder mapping).
- Backend: `chatreadretrieveread.py` — added `_is_hyrox_assessment_chatbot`, a
  skip-retrieval branch (empty `ExtraInfo`), the result-recording hook in
  `run_without_streaming`, and imported `DataPoints`.
- Frontend: new `app/frontend/src/chatbots/hyrox-assessment/` (cloned from lemon),
  rebranded — `index.ts`, `Chat.tsx` (category, non-streaming, agentic off),
  `Answer.tsx` + `assessmentMarkers.ts` (strip markers at render only),
  `Layout.tsx` (+ Brutal `@font-face`), `assets/fonts/` (Brutal), `en/de/nl`
  locale titles + welcome.
- Frontend: `/hyrox-assessment` now reuses Lemon's `lemon-chatbot.png` for the
  navbar logo, answer avatar, and dormant empty-state logo reference.
- Frontend: propagated the auto-growing question input behavior from
  `hyrox-assessment` to all chatbot `QuestionInput.tsx` copies and removed the
  desktop fixed input-container height from FBN so it can grow.
- Frontend: registered in `chatbots/registry.ts` (new `"assessment"` mode),
  `ChatbotDirectory.tsx` label, theme `#FFED00` in `shared/theme/chatbotThemes.ts`.
- Frontend (shared, additive/no-op for other bots): `createBotAnswer.tsx` +
  `ChatbotAnswer.tsx` gained an optional `preprocessAnswerText` display-only transform.
- Tests: `tests/test_hyrox_assessment.py` (pool/config/prompt/marker-parsing/tally/
  pass-fail/record-result) and a `/chat` skip-retrieval smoke test in `tests/test_app.py`.
- Backend routing fix: added `"hyrox-assessment"` to `KNOWN_CHATBOT_NAMES` in
  `app/backend/app.py` — the `/<chatbot_name>` route gates against this set and was
  redirecting `/hyrox-assessment` to `/`. Documented this always-required step in
  `CLAUDE.md` (Adding A Chatbot → Backend, always required for routing).
- Prompt refinement (`sampleprompt.py`): every question is now prefixed with a visible
  localized progress header (`**Question N of 20**` / `Frage N von 20` / `Vraag N van 20`),
  where N = (#scored so far)+1; the internal pool number (1–32)/category/points stay hidden.
  Hardened the no-repeat rule with a fallback (never re-ask a question already visible in the
  conversation even if a marker is missing).

## 2026-05-26

### Decisions

- **Ported `nerilio backend` admin design into `/verwaltung` as React TSX.**
  Faithful design-only port of the sibling PHP project at
  `D:\working student\snap\nerilio backend\` (7 views + monolithic CSS) into a
  new admin surface at `/verwaltung`. Decisions:
  - Nested sub-routes (`/verwaltung/dashboard`, `/customers`, `/users`,
    `/knowledge-bases`, `/configure/:botId?`) — not a single-page tab switcher.
  - Reused existing `useInternalAdminAccess` hook for the auth gate (same gate
    as `/chatbots`, `/manage-prompts`). The ported `login.php` design renders
    as the unlock screen.
  - Empty UI shells: tables show their headers + empty-state rows; modals and
    slide-in detail panels open/close; "submit" handlers just toast. No mock
    data, no AJAX. Backend Python endpoints are explicitly out of scope and
    will be a follow-up.
  - Source CSS (`public/css/style.css`, 593 lines) ported into a single global
    file (`app/frontend/src/pages/verwaltung/verwaltung.css`) with every
    selector prefixed by `.verwaltung-root` to prevent class-name collisions
    with the rest of the app. Chose this over CSS Modules because the source's
    very short class names (`.app`, `.modal`, `.dp`, `.cm`, …) would have
    required renaming every `className` in the TSX; the wrapper scope is
    enough to isolate the new code.
  - Inline SVG icons kept verbatim (stroke weights, viewBoxes, points) in
    `components/icons.tsx` rather than swapped for Fluent UI icons — the
    source's specific look is part of the design.
  - `/verwaltung/portal` is a sibling top-level route (no sidebar, no admin
    gate) — matches the source's customer-user surface.
  - No i18n — admin pages in this repo are not translated; source German
    strings preserved verbatim.
- **Attributed OpenLIT LLM request spans with chatbot metadata instead of editing
  the external OpenLIT dashboard UI.** This repo only sends telemetry to the
  configured `OPENLIT_ENDPOINT`; it does not own the OpenLIT Requests page.
  Per-request custom span attributes (`chatbot.name`,
  `chatbot.effective_name`, and for `/internal`, `chatbot.source_name`) give
  OpenLIT data to filter/group by while keeping dashboard customization outside
  the app code.
- **Swapped canonical agent-instructions file from `AGENTS.md` to `CLAUDE.md`.**
  All repo contracts, change workflows, tests, and deployment notes now live in
  `CLAUDE.md`; `AGENTS.md` is a thin pointer that defers to it. Reason: align
  the canonical playbook with the file Claude loads automatically, while
  keeping `AGENTS.md` available for tools (Codex, others) that look for it.
- **Adopted the thesis-project changes-log pattern.** Added `CHANGES.md` at
  the repo root with reverse-chronological dated entries split into Decisions
  and Changes, plus a "Changes log maintenance" section in `CLAUDE.md` so
  Claude, Codex, and any other agent reads it at session start and appends at
  session end. Mirrors the convention from `D:\study-material\5th\thesis\thesis`.

### Changes

- Created `app/frontend/src/pages/verwaltung/` with the new admin surface:
  - `verwaltung.css` (590+ lines, scoped under `.verwaltung-root`).
  - `VerwaltungLayout.tsx` (auth gate + sidebar + `<Outlet/>`).
  - `index.ts` (barrel exports).
  - `components/Sidebar.tsx`, `components/Toast.tsx` (toast hook),
    `components/icons.tsx` (inline SVG icon set).
  - `pages/LoginPage.tsx` (ported from `views/login.php`; wired to
    `useInternalAdminAccess.login`).
  - `pages/DashboardPage.tsx` (chatbot table + create modal + confirm modal).
  - `pages/CustomersPage.tsx` (table, wide create/edit modal, delete confirm,
    slide-in detail panel with inline new-bot form).
  - `pages/UsersPage.tsx` (table + role/status/customer filters + modal +
    detail panel with bot assignments).
  - `pages/KnowledgeBasesPage.tsx` (table + create modal + delete confirm +
    text-entry modal + detail panel with usage bars, dropzone, file list,
    text list, URL crawl section).
  - `pages/ConfigurePage.tsx` (page-tabs general/qa/tutor/assessment, 12
    collapsible sections in general tab, language pills + per-language tabs,
    color picker, upload zones, mode-driven tab visibility).
  - `pages/PortalPage.tsx` (standalone customer-user bot grid + profile modal).
- Edited `app/frontend/src/index.tsx`: imported the verwaltung exports and
  registered nested routes for `/verwaltung/{dashboard,customers,users,
  knowledge-bases,configure/:botId?}` plus sibling `/verwaltung/portal`.
- Edited `app/backend/app.py`: registered `/verwaltung`, `/verwaltung/`, and
  `/verwaltung/<path:subpath>` to serve the SPA index, and added
  `"verwaltung"` to `NON_CHATBOT_FRONTEND_PREFIXES`. Without these, the
  catch-all chatbot route at `/<chatbot_name>` was redirecting `/verwaltung`
  back to `/` because it wasn't in `KNOWN_CHATBOT_NAMES`.
- Edited `CLAUDE.md`: added `/verwaltung/*` (excluding `/verwaltung/portal`)
  to the "Shared internal admin auth gates" contract.
- Edited `app/backend/app.py`: chat and streaming chat routes now wrap OpenLIT
  instrumented work in request-specific chatbot attributes when
  `OPENLIT_ENDPOINT` is configured. Streaming responses keep the attributes
  active while the async generator is consumed.
- Edited `tests/test_app.py`: added focused tests for OpenLIT chatbot metadata
  on normal chat, `/internal` route/source attribution, and streaming lifetime.
- Deployed the `backend` service to Azure Container Apps with `azd deploy
  backend`; active revision is
  `capps-backend-ylubdsyknmmcc--azd-1779797065` with 100% traffic.
- Ran `graphify update .`, updating `graphify-out/graph.json` and
  `graphify-out/GRAPH_REPORT.md`.
- Edited `CLAUDE.md`: now holds the full agent playbook (graphify rules,
  operating rules, where to start, contracts to preserve, adding data /
  chatbot / azd variable / developer settings, tests, deployment, style).
  Previously a thin pointer to `AGENTS.md`.
- Edited `AGENTS.md`: reduced to a thin pointer that defers to `CLAUDE.md`.
  Previously held the full playbook.
- Created `CHANGES.md`: new project changes log (this file).
- Edited `CLAUDE.md`: added a "Changes log maintenance" section and listed
  `CHANGES.md` in the canonical artifacts so future sessions know to read
  and update it.
