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

## 2026-06-13

### All bots: responsive answer tables (polished horizontal scroll)

#### Decisions

- Markdown tables in chat answers looked fine on desktop but were crammed and shattered letter-by-letter
  ("P l a n", "L i m i t s") on mobile / the narrow embedded widget. Root cause was twofold in the shared
  `SharedAnswer.module.css`: (1) `.answerMarkdown { overflow-wrap: anywhere }` is inherited by every `<td>`/`<th>`,
  letting the browser break words at any character to avoid overflow; (2) the table's mobile `min-width: 22rem`
  (~352px) was barely wider than a phone, so the auto layout squeezed all columns to fit instead of letting the
  existing `.tableScroll` wrapper scroll. The scroll container existed but the styling forced cramming.
- Chose the **polished horizontal-scroll** approach (user pick) over stacked mobile cards: keep the real table
  shape on every device, CSS-only, lowest risk. All bots share one render path
  (`Answer.tsx` → `createBotAnswer` → `ChatbotAnswer.tsx` → `SharedAnswer.module.css`), so the fix is centralized;
  per-bot `components/Answer/Answer.module.css` table rules are legacy/dead on the active path.
- Switched the table-level `min-width` to a **per-cell** `min-width` floor so columns stay readable and wide tables
  grow past the viewport (→ horizontal scroll), while small 2-column tables still fit without forced scrolling.
- Left the per-bot `MarkdownViewer` (citation source preview) tables untouched — different surface, not the reported issue.
- **Second round (the important one).** The per-cell `min-width` made the readable-columns goal work but exposed a
  worse bug: on mobile the whole answer bubble blew *past* the viewport and the table was cut off at the screen edge
  with no way to scroll. Verified the real cause by rendering the live nerilio page in Playwright at 375px and walking
  the table's ancestor chain: the table's intrinsic width (~504px) propagates *up* through the chat layout's
  `min-width: auto` flex chain (`.chatMessageStream` → `.chatContainer` → `.chatRoot` → `.container`, the latter a
  `flex:1` child of `<main>`), forcing the app to ~586px on a 375px screen. `.tableScroll`'s `overflow-x: auto` never
  engaged because an overflow scroll-container in a *block* context does **not** zero its min-content contribution —
  only flex/grid items do. So nothing constrained its width and it never had to scroll.
- Two fixes were possible: (a) `min-width: 0` on every bot's layout flex chain (per-bot edits in ~15 `Chat.module.css`
  files), or (b) `contain: inline-size` on the shared `.tableScroll` so its width is computed *without* looking at its
  contents, stopping the propagation at the source in one place. Chose **(b)** — single shared line, fixes all bots.
  Scoped it to the mobile `@media (max-width: 767px)` only: on desktop, omitting containment lets a wide table grow
  the bubble to fill the available width (no needless scroll), preserving the original desktop look. Empirically
  verified on the live app: mobile page + embed → no page overflow, table scrolls inside the bubble; small 2-col table
  → fits, no scroll; desktop → table fills bubble at full width, no scroll.
- `min-width: 0` on `.answerShell` / `.answerContainer` was added during diagnosis and kept as defensive flex hygiene
  (flex children holding potentially-wide content should be allowed to shrink); `contain: inline-size` is the load-bearing fix.

#### Changes

- `app/frontend/src/chatbots/shared/answer/SharedAnswer.module.css`:
  - Cells (`.answerMarkdown th, td`): override inherited `overflow-wrap: anywhere` with `overflow-wrap: break-word`,
    `word-break: normal`, and `hyphens: none`; add `min-width: 6.5rem` (6rem on mobile) so columns don't collapse.
  - `.answerTable`: removed `min-width: 28rem` (now per-cell), made background transparent so scroll shadows show through.
  - `.tableScroll`: added thin styled scrollbar (`scrollbar-width`/`-color` + `::-webkit-scrollbar*`), momentum scroll
    (`-webkit-overflow-scrolling: touch`), `overscroll-behavior-x: contain` (swipe won't drag the page inside the widget),
    and self-hiding Lea-Verou CSS scroll shadows that hint there's more to swipe.
  - `.answerShell` / `.answerContainer`: added `min-width: 0` (defensive flex-shrink hygiene).
  - Mobile `@media (max-width: 767px)`: replaced the removed `.answerTable { min-width: 22rem }` with tighter cell padding
    (`0.62rem 0.72rem`) and `min-width: 6rem`; **added `.tableScroll { contain: inline-size }`** — the load-bearing fix
    that keeps wide tables from pushing the page past the viewport while letting the table scroll inside the bubble.

### Nerilio: stop chat view from scrolling horizontally

#### Decisions

- The prior hidden-scrollbar change (`scrollbar-width: none` on `.chatContainer`) exposed a latent issue:
  because `.chatContainer` has `overflow-y: auto`, its `overflow-x` computes from `visible` to `auto`, so
  the chat area was always a *horizontal* scroll container. While the scrollbar was visible/gutter-reserved
  this was contained; once hidden, any edge overflow (e.g. the last column of a wide pricing table) became
  an invisible sideways swipe, making the view exceed mobile width.
- Fixed by clipping the x-axis (`overflow-x: hidden`) rather than reverting the hidden scrollbar — the user
  wants the scrollbar hidden. Answer content is already constrained (`.answerContainer { max-width: 100% }`,
  `overflow-wrap: anywhere`) and wide tables keep their own `.tableScroll`, so clipping hides no real content.

#### Changes

- `app/frontend/src/chatbots/nerilio/pages/chat/Chat.module.css`: added `overflow-x: hidden` to
  `.chatContainer` so it scrolls vertically only and the view never scrolls horizontally at any width.

### Nerilio: smaller mobile header mark and title

#### Decisions

- Scoped the visual refinement to `/nerilio` mobile only. The previous mobile rule made the header title
  larger than desktop, which looked heavy next to the compact navbar controls.
- Scoped hidden scrollbar styling to Nerilio's chat transcript container only. The chat remains scrollable
  when content grows; the visual scrollbar/gutter is hidden to keep the right edge cleaner.

#### Changes

- `app/frontend/src/chatbots/nerilio/pages/layout/Layout.module.css`: in the `max-width: 768px`
  rule, reduced the logo circle to `30px`, tightened the left-section gap, and reduced the title
  size to `1.32rem`.
- Verified with `npm run build` and a Playwright render check at 390x844: title and logo use the
  expected computed sizes and the header does not horizontally overflow.
- `app/frontend/src/chatbots/nerilio/pages/chat/Chat.module.css`: replaced the stable scrollbar gutter
  on `.chatContainer` with hidden-scrollbar CSS (`scrollbar-width: none`, `-ms-overflow-style: none`,
  and `::-webkit-scrollbar { display: none; }`) while keeping `overflow-y: auto`.
- Verified with `npm run build` and a Playwright scroll check at 390x844: `.chatContainer` remains
  scrollable (`scrollTop` changes), reports hidden scrollbar styles, and has `0px` scrollbar gutter.

## 2026-06-12

### All bots: history panel overlays on tablet-portrait widths

#### Decisions

- Treat the chat-history panel breakpoint as a layout-capacity boundary, not a phone-only device
  rule. A 300px side panel at 768px leaves only 468px for the chat surface, which compromises
  answer/table layouts. The drawer now uses the compact overlay + scrim behavior below the existing
  992px wide-layout breakpoint; the side-by-side push remains for wider desktop layouts.

#### Changes

- `app/frontend/src/chatbots/shared/history/useIsCompactViewport.ts`: changed the compact
  `matchMedia` query from `(max-width: 767.98px)` to `(max-width: 991.98px)`.
- Updated all 15 bot `pages/chat/Chat.module.css` files so `.chatRootHistoryOpen` applies the
  300px `margin-left` only at `@media (min-width: 992px)` (internal continues to reuse lemon's
  chat module).
- Verified with `npm run build` in `app/frontend`.
- Verified `/nerilio` with Playwright at 768x1024: history panel open gives `margin-left: 0px`,
  modal overlay present, and no page-level horizontal overflow. Rechecked 1200px desktop:
  `margin-left: 300px`, no modal overlay.
- Follow-up: Fluent UI `Panel` requires `isLightDismiss` for the blocking overlay to close on
  outside click/tap. Added `isLightDismiss={isCompactViewport}` to all 15 history panels so
  tablet/compact overlay mode light-dismisses while desktop side-by-side mode stays non-dismissible
  by outside click. Verified `/nerilio` at 768x1024: clicking the scrim closes both `.ms-Panel`
  and `.ms-Overlay`.

### All bots: mobile history panel gets a scrim; Nerilio header shows full name

#### Decisions

- Follow-up to the overlay fix below. On phones the history panel now renders as a proper modal drawer
  with a dimmed backdrop instead of a borderless overlay. Fluent `Panel` only draws a scrim when
  `isBlocking={true}`, and we want that **only** on phones (desktop/tablet must stay non-blocking so the
  side-by-side push remains interactive), so `isBlocking` is now driven by viewport width rather than a
  hardcoded `false`.
- Added a shared, reactive `useIsCompactViewport` hook (matchMedia `(max-width: 767.98px)`, complement of
  the 768px push breakpoint) under `chatbots/shared/history/` rather than duplicating a resize listener in
  each of the 15 panels. Each `HistoryPanel` imports it and passes `isBlocking={isCompactViewport}`.
- Nerilio header: the title (`headerTitle` = "nerilio") truncated to "ner…" on mobile because the
  `@media (max-width: 768px)` rule capped `.navbarTitle` at `max-width: 50%`, and the base rule
  ellipsis-truncates. The 50% cap created a circular flex constraint that starved the title. Removed the
  cap (kept the 1.7rem mobile size); the short title now sizes to content and shows in full. Scoped to
  nerilio only, as requested — other bots' headers were not touched.

#### Changes

- Added `app/frontend/src/chatbots/shared/history/useIsCompactViewport.ts` (reactive phone-viewport hook).
- In all 15 `components/HistoryPanel/HistoryPanel.tsx` (internal reuses lemon's): imported the hook, added
  `const isCompactViewport = useIsCompactViewport();`, and changed `isBlocking={false}` →
  `isBlocking={isCompactViewport}`.
- `nerilio/pages/layout/Layout.module.css`: removed `max-width: 50%` from the mobile `.navbarTitle` rule.
- Verified with `tsc --noEmit` (exit 0).

### All bots: chat history panel overlays instead of pushing on mobile

#### Decisions

- The chat-history panel (Fluent `Panel`, `customNear`, 300px, `isBlocking={false}`) was paired with a
  hardcoded inline `marginLeft: isHistoryPanelOpen ? "300px" : "0"` on `.chatRoot` that applied at **every**
  viewport width. On desktop/tablet this is the intended side-by-side push; on phones `viewport − 300px`
  drops below the chat's min-content width (input row, message bubbles), forcing horizontal overflow and a
  page-level horizontal scrollbar.
- Fix: move the 300px shift from an always-on inline style into a CSS-module class (`.chatRootHistoryOpen`)
  gated behind `@media (min-width: 768px)`. At ≥768px the push is unchanged (tablet/desktop keep
  side-by-side); below 768px no margin is applied, so the portaled fixed panel simply **overlays** the chat
  (no document-flow shift → no horizontal scroll). 768px chosen so tablets keep their existing side-by-side
  behavior (matches the previous look) while only phones switch to overlay; at 768px the remaining 468px
  comfortably exceeds the chat's min-content. Added `transition: margin-left 0.3s ease` on `.chatRoot` so the
  desktop push animates smoothly.
- Kept the panel non-blocking (no scrim) on mobile; it relies on the Fluent close (X) button and light-dismiss.
  A mobile-only dimmed backdrop would need per-bot JS viewport detection (16 bots) and was deliberately left
  out to keep the fix CSS-only and low-risk; can be added later if desired.

#### Changes

- Replaced `className={styles.chatRoot} style={{ marginLeft: ... }}` with
  `className={`${styles.chatRoot} ${isHistoryPanelOpen ? styles.chatRootHistoryOpen : ""}`}` in every bot's
  `pages/chat/Chat.tsx` (16 files: agindo, demo, fbn, fhg, hyrox-assessment, internal, knoll, lemon, moodle,
  nerilio, public-test, publishone, rak, sartorius, steuertipps, vjoonk4).
- Added `transition: margin-left 0.3s ease` to `.chatRoot` and a `@media (min-width: 768px) { .chatRootHistoryOpen { margin-left: 300px; } }`
  rule to 15 `pages/chat/Chat.module.css` modules (internal reuses lemon's module).
- Verified with `tsc --noEmit` (exit 0).

### Nerilio: fix page scroll after re-enabling the header

#### Decisions

- The nerilio chat `.container` was sized `height: 100vh` (full viewport) while living inside
  `.main`, which is `flex: 1` under the `.layout` column below the `56px` `.header`. With the header
  previously commented out the `100vh` happened to fit; re-enabling the header pushed total content to
  `100vh + 56px`, so the blank page scrolled. Sibling bots (demo, lemon, fbn, rak) use `height: 100%`
  (fill `.main`, i.e. viewport-minus-header) — adopted the same so the layout is correct regardless of
  header height, rather than subtracting a hardcoded `56px`.

- Header title moved from absolute-centered to left, beside the logo. The previous
  `position: absolute; left: 50%; translateX(-50%)` centering was replaced by grouping logo + title
  in a flex `.leftSection`, so the title flows immediately after the logo and ellipsis-truncates
  instead of overlapping the right section.
- Settled `.container` height on `calc(100vh - 56px)` (publishone's value), not `100%`. With the
  header restored, `height: 100%` left the chat input floating directly under the greeting instead of
  pinned to the bottom — the percentage chat-shell chain (`.chatRoot`/`.chatContainer` use
  `height: 100%`) needs `.container` to carry a *definite* height for `.chatMessageStream { flex: 1 }`
  to expand and push the sticky input down. `calc(100vh - 56px)` is definite, anchors the input at the
  bottom like the other bots, and still sums with the 56px header to exactly `100vh` (no page scroll).
- Removed the **Close** item from the header dropdown menu per request. The dropdown now offers only
  New Chat and Recent Chats. Dropped the now-unused `handleCloseChat` handler (which posted
  `chatbot:close` to the widget parent) and the `ChatDismiss24Regular` import; the embeddable widget's
  own launcher close is unaffected.

#### Changes

- `app/frontend/src/chatbots/nerilio/pages/chat/Chat.module.css` — `.container` height set to
  `calc(100vh - 56px)` in both the base rule and the `@media (min-width: 992px)` rule (was `100vh`,
  briefly `100%`).
- `app/frontend/src/chatbots/nerilio/pages/layout/Layout.tsx` — wrapped the logo `Link` and
  `.navbarTitle` in a new `.leftSection` div; removed the Close `<li>`, the `handleCloseChat`
  function, and the `ChatDismiss24Regular` import.
- `app/frontend/src/chatbots/nerilio/pages/layout/Layout.module.css` — added `.leftSection` (flex,
  `gap: 0.75rem`); removed absolute centering from `.navbarTitle` (now left-aligned with ellipsis).

### Persistent chat across navigation — all 15 chatbots + embeddable widget

#### Decisions

- **Persist the *active session* (a per-bot pointer), then restore it on load** — so closing a
  tab/navigating and reopening reappears the last conversation (ChatGPT/Gemini-style) instead of a
  blank chat. A new chat starts *only* via the New Chat control (which clears the pointer). Restoring
  the active pointer — not merely the newest stored session — is what makes New Chat behave correctly:
  after New Chat with nothing sent there is no pointer, so the next load is blank.
- **One design covers every surface.** The restore logic lives in the chat app (`Chat.tsx`), which is
  the same code for direct access (`/<bot>`), the same-site iframe on nerilio.ai, and the third-party
  `widget.js` embed. `chat.nerilio.ai` is a subdomain of `nerilio.ai` → same-site/first-party storage,
  so IndexedDB + the active-session pointer persist across tabs with no partitioning issues. Third-party
  embeds persist per host site (Safari/ITP may not keep third-party storage across full restarts — a
  browser policy, not fixable in code).
- **Scope: all 15 history-capable bots, code-only.** No `.env` changes — persistence activates per bot
  only once its deployment has `USE_CHAT_HISTORY_BROWSER="true"` (today: demo, nerilio, p1/publishone,
  steuertipps). For bots without the flag, `historyProvider` stays `None` and the restore effect no-ops,
  so the change is inert until the flag is flipped (safe to ship to all 15). Gated to the IndexedDB
  provider only; Cosmos/login-based history is out of scope.
- **Auto-open = remember open/closed.** The embeddable widget re-opens on the next page only if it was
  open when the user left (respects an explicit close). Stored in the *host page's* first-party
  localStorage (`chatbot-widget-open:<id>`), so it works on every embedding site. Direct access has no
  launcher, so auto-open is N/A there.
- **nerilio header brought back** to expose New Chat / Recent Chats (it was fully commented out).
  `internal` (a shell with no history provider) and `test` (no chat page) are out of scope.

#### Changes

- **New** `app/frontend/src/chatbots/shared/history/activeSession.ts` — `readActiveSessionId` /
  `writeActiveSessionId` / `clearActiveSessionId`, scoped per bot via `getChatHistoryScope()`, all
  try/catch-guarded (private mode → silent no-op).
- `app/frontend/src/chatbots/<bot>/pages/chat/Chat.tsx` × **15** (agindo, demo, fbn, fhg,
  hyrox-assessment, knoll, lemon, moodle, nerilio, public-test, publishone, rak, sartorius, steuertipps,
  vjoonk4): added a shared `restoreConversation` helper (now also used by the history panel's
  `onChatSelected`), a one-shot restore-on-load `useEffect` (gated on the IndexedDB provider; skips if a
  question is already in flight), `writeActiveSessionId` at both `addItem` save sites, and
  `clearActiveSessionId` in `clearChat`. nerilio hand-edited as the reference; the other 14 applied via a
  one-off idempotent codemod (removed after running).
- `app/frontend/src/widget/widget.ts` — added `chatbot-widget-open:<id>` open-state memory
  (`readStoredOpen`/`writeStoredOpen`), written in `openPanel`/`closePanel`, and auto-open from the
  stored flag in `createWidget` (covers all embedded bots).
- `app/frontend/src/chatbots/nerilio/pages/layout/Layout.tsx` — un-commented the header (New Chat /
  Recent Chats / Close dropdown); fixed `handleCloseChat` to post `chatbot:close` (the message
  `widget.js` actually handles, so Close now dismisses the popup and persists the closed state); fixed
  the menu aria-label to the existing `labels.toggleMenu` key.
- `tests/e2e.py` — added 4 Playwright e2e tests (all pass, 2 viewport params each): nerilio restores
  the last session on reload; New Chat clears and stays blank across reload; the embeddable widget
  auto-opens when previously open and stays closed by default. They mock `/config` (browser history on)
  + `/chat/stream`, and wait on an IndexedDB poll before reload to avoid racing the async save. nerilio
  submits via Enter (its send button is icon-only). Note: pre-existing, unrelated `test_demo_*` e2e
  failures (demo login form never renders) were confirmed to also fail on a clean baseline build.

### Reverted: auto-growing question input on `/nerilio` only

#### Decisions

- **The auto-growing chat input is reverted for the `nerilio` bot only** (other bot copies keep it).
  The `autoAdjustHeight` + `maxHeight: 12rem` / `overflowY: auto` change (originally propagated from
  `hyrox-assessment` to all `QuestionInput.tsx` copies on 2026-05-28) broke nerilio's input styling,
  so its copy is restored to the pre-change state.

#### Changes

- `app/frontend/src/chatbots/nerilio/components/QuestionInput/QuestionInput.tsx` — removed
  `autoAdjustHeight`, re-commented `multiline` / `resizable={false}`, and reverted the `field` style
  slot back to only `fontSize: 16` (dropped `minHeight: 44`, `maxHeight: "12rem"`, `overflowY: "auto"`).
  Working tree now matches the pre-`06e705a6` state for this file.

### Decisions

- **HYROX assessment: question input is removed once the assessment completes — pass OR fail.** The
  run is already terminal in-session for both outcomes (`derive_turn_state` returns `current_id =
  None` after the 20th score; retaking happens in the Lemon app via a fresh session). Leaving the
  input live only produced a wasted LLM round-trip returning a canned "it's over, restart in the
  app" reply, and gating it on pass *only* would strand failed learners typing into a dead
  assessment. Chosen to **hide** the input entirely (not just disable) once complete.
- **Completion is signalled by a new hidden `[[DONE]]` marker on both outcomes — reusing the
  marker channel, not localized text parsing.** The pass-only `[[PROGRESS value=100]]` marker can't
  cover fail, and matching the visible "Assessment complete" line is fragile across `en`/`de`/`nl`.
  `[[DONE]]` is appended in `render_assessment_turn`'s trailing block gated on `just_completed`
  (fires once per run, carries no `[[BREAK]]` so the five-bubble layout is unchanged) and lives in
  the stored message, so it **replays from history** — a reopened completed session stays terminal.
- **HYROX assessment header menu is disabled for the Lemon-hosted flow.** Lemon now owns session
  navigation/client-side management, while this bot focuses on taking the assessment; the old
  header dropdown remains in code behind a local off switch so it can be restored if needed.
- **HYROX assessment: Lemon User ID via launch URL + result hand-over via `lemon://`.** The
  Lemon app opens the bot with the learner on the query string
  (`?account_id=...&first_name=...&last_name=...`); on a **passed** completion the bot hands the
  result back by "calling" `lemon://save_progress?value=100` (a custom scheme the native app
  intercepts). Confirmed with the client: report **only on pass** (≥80%) — nothing on a failed
  completion; also **personalize the greeting** with the first name *and* record id/name with the
  result.
- **Completion signal rides the existing hidden-marker channel, not localized text parsing.** The
  backend already owns `tally["passed"]`/`just_completed`; on a passed completion it appends a
  hidden `[[PROGRESS value=100]]` marker (carries no `[[BREAK]]`, so the five-bubble layout is
  unchanged). The frontend hides it at render and fires the scheme exactly once on the freshly
  received response — never on history replay (replay goes through `onChatSelected`, not
  `makeApiRequest`; an idempotency ref also guards it). A failed run auto-restarts a fresh run, so
  the marker is never emitted there.
- **`lemon://` trigger made robust to both load contexts** (client unsure how the bot is embedded):
  `reportLemonProgress` both `postMessage`s a `chatbot:save-progress` to any embedding host (iframe
  case, same `chatbot:*` convention as the widget bridge) **and** sets `window.location.href` to the
  scheme (direct-webview case — intercepted by the native app, harmless no-op in a plain browser).
- **Identity passed via `context.overrides`, no backend whitelist change.** Overrides flow through
  wholesale (`app.py` `context.get("overrides", {})`); `account_id` stands in as `user_id` for the
  LMS payload/session log when no auth `oid` is present. Account read once from
  `window.location.search` (hash-router query survives in-app nav) and cached to sessionStorage so a
  same-tab reload keeps it.

### Changes

- `app/backend/approaches/chatbots/hyrox_assessment/results.py` — add `DONE_MARKER = "[[DONE]]"`;
  append it in `render_assessment_turn`'s trailing block on `just_completed` (pass and fail); add
  `DONE` to `ANY_MARKER_RE` so `strip_markers` removes it.
- `app/frontend/src/chatbots/hyrox-assessment/components/Answer/assessmentMarkers.ts` — add `DONE`
  to `ASSESSMENT_MARKER_RE`; add `DONE_MARKER_RE` + exported `hasAssessmentDoneMarker(text)`.
- `app/frontend/src/chatbots/hyrox-assessment/pages/chat/Chat.tsx` — derive `assessmentComplete`
  from `answers` via `hasAssessmentDoneMarker`; render the `QuestionInput` only when not complete.
- `tests/test_hyrox_assessment.py` — `test_completion_appends_done_marker_on_pass_and_fail` and
  `test_done_marker_absent_mid_assessment`.
- `tests/e2e.py` — first Playwright coverage for the hyrox-assessment bot:
  `test_hyrox_assessment_hides_input_when_completed` (a `[[DONE]]`-bearing completion removes the
  input, splits the `[[BREAK]]` bubbles, and leaks no `[[...]]` marker into the transcript) and
  `test_hyrox_assessment_keeps_input_mid_assessment` (a graded turn with no `[[DONE]]` keeps the
  input). Mocks the non-streaming `/chat`; requires a fresh `npm run build` to exercise the change.
- `app/frontend/src/chatbots/hyrox-assessment/pages/layout/Layout.tsx` — hide the header
  three-dot menu/dropdown with `showHeaderMenu = false`, leaving the former new-chat/recent-chat
  controls commented out of the rendered UI.
- **New** `app/frontend/src/chatbots/hyrox-assessment/lemonBridge.ts` — `readLemonAccount()`
  (URL→`{accountId,firstName,lastName}`, sessionStorage-cached) and `reportLemonProgress(value)`
  (postMessage + scheme navigation).
- `app/frontend/src/chatbots/hyrox-assessment/api/models.ts` — `ChatAppRequestOverrides` gains
  optional `account_id` / `first_name` / `last_name`.
- `app/frontend/src/chatbots/hyrox-assessment/pages/chat/Chat.tsx` — read the Lemon account at
  mount (ref); prepend `t("greeting", {firstName})` to the welcome bubble when a first name is
  present; send the identity in `context.overrides`; fire `reportLemonProgress` once when a fresh
  response carries the `[[PROGRESS]]` marker (`maybeReportLemonProgress` in both response branches,
  guarded by `progressReportedRef`).
- `app/frontend/src/chatbots/hyrox-assessment/components/Answer/assessmentMarkers.ts` — add
  `PROGRESS` to the strip regex (hidden at render); new `parseProgressValue(text)`.
- `app/frontend/src/chatbots/hyrox-assessment/locales/{en,de,nl}/translation.json` — new `greeting`
  key (`"Hi/Hallo/Hoi {{firstName}}!\n\n"`).
- `app/backend/approaches/chatbots/hyrox_assessment/results.py` — add `PROGRESS` to `ANY_MARKER_RE`,
  define `PROGRESS_MARKER`/`PROGRESS_PASS_VALUE`, append the marker in `render_assessment_turn` only
  when `just_completed and tally["passed"]`; thread `account_id`/`first_name`/`last_name` from
  overrides into `build_result_payload` + `record_assessment_result` (account_id → user_id fallback).
- `tests/test_hyrox_assessment.py` — `test_completion_appends_progress_marker_on_pass`,
  `test_completion_omits_progress_marker_on_fail`, `test_record_assessment_result_records_lemon_identity`.
  Full file: 49 passed.

### Follow-up: fail-case copy + completed run is terminal in-session

#### Decisions

- **A completed assessment is now terminal in this session — pass OR fail.** Previously a failed
  run auto-restarted a brand-new 20-question run on the learner's next message (`fail → restart
  immediately`). Per the client, the learner cannot retake the assessment here; restarting happens
  in the Lemon app, which launches a fresh session. This **supersedes** the earlier same-day note
  that "a failed run auto-restarts" — `derive_turn_state` now returns a terminal completed state for
  a failed run (mirroring the passed case) instead of `_fresh_run_state()`. The `[[PROGRESS]]` pass
  marker still fires exactly once, now purely because it is gated on `just_completed and passed`
  (not because a fail restarts away from that code path).
- **Surfaced + resolved a contradiction:** the input box is only disabled while loading (no
  "assessment finished" gate), so under the old behavior a failed learner typing anything silently
  began a fresh run — directly contradicting the new "restart in the Lemon app" copy. Making the run
  terminal makes the copy true.
- **Fail-case ending is content-only, structurally identical to pass** (same five `[[BREAK]]`
  bubbles). Client-supplied verbatim motivational + closing copy (en), faithfully translated to
  de/nl; the closing bubble points to the Lemon app to retake (no "send a message to restart").
- **Verdict label on fail → "Failed"** (de "Nicht bestanden", nl "Niet geslaagd"), replacing the
  all-caps "NOT PASSED"/"NICHT BESTANDEN"/"NIET GESLAAGD"; the pass label stays "PASSED".

#### Changes

- `app/backend/approaches/chatbots/hyrox_assessment/results.py`:
  - `_LOCALES` (en/de/nl): `failed` verdict relabelled; new `motivational_failed` + `closing_failed`
    copy. `closing_failed` drops the `{threshold}` placeholder and points to the Lemon app.
  - `render_completion_bubbles` — closing bubble no longer `.format(threshold=...)`.
  - `derive_turn_state` — a completed run (≥ `QUESTIONS_PER_RUN` scored) returns a terminal state
    (`current_id=None`, `completed_passed=tally["passed"]`) for both outcomes; no `_fresh_run_state()`
    on fail. Docstring updated.
  - `build_state_injection` — the completed (`current_id is None`) branch now handles pass AND fail:
    tells the model the assessment is over and cannot be retaken in this session, and points repeat
    requests to the Lemon app.
  - Stale comments updated (`[[PROGRESS]]` gating rationale; completion-bubbles docstring).
- `tests/test_hyrox_assessment.py`:
  - `test_failed_completed_run_auto_restarts` → `test_failed_completed_run_is_terminal` (terminal
    state + Lemon-app injection assertions).
  - `test_render_final_result_localized` — assert "Nicht bestanden" (de) and the new en "Failed".
  - `test_completion_renders_failed_ending_with_retry_note` — assert "Failed" verdict, the new
    motivational opener, and "take this assessment again" / "lemon app" closing.
  - Full file: 49 passed; `ty check` clean.
- No frontend change — verdict label and fail copy are entirely backend-rendered, and bubble
  splitting already produces the five-bubble layout.

## 2026-06-11

### Decisions

- **HYROX assessment bot client rebrand ("Managing Performance").** Black header with the
  title in HYROX yellow `#FFED00`, title renamed to "HYROX Assessment", robot icon removed
  from the header, bot avatar in chat switched to the existing `HYROX.svg`, user bubbles
  white-on-black-text, bot bubbles black-on-white-text. Theme seed keeps `primary: #FFED00`
  with `overrides` (navbar + userBubble) — the established knoll-style special-case mechanism.
- **Bot answer bubble colors became theme-able via CSS variables, not a fork.** Shared
  `SharedAnswer.module.css` colors (`background`, text, headings, `strong`/`em`, assistant
  name) are now `var(--chatbot-answer-*, <previous hardcoded value>)`, so every other bot is
  pixel-identical; hyrox sets the vars in its own `Chat.module.css .container` (nerilio
  precedent). The copy/speech icon buttons use `var(--chatbot-answer-action-color, black)`
  instead of inline hardcoded black.
- **End-of-assessment renders as five separate chat bubbles** (client requirement): final
  question's score + feedback → "Assessment complete — Total: X/Y (Z%) — verdict" → topic
  summary → motivational text → closing note. Implemented with a backend-authored hidden
  `[[BREAK]]` marker joined into ONE stored assistant message; the frontend splits at
  `[[BREAK]]` for display only. Stored content stays joined, so history persistence/restore
  and the stateless backend replay/state-derivation are untouched. Mid-run turns are
  unchanged (score + feedback + chained next question stay one bubble).
- **The strengths/weaknesses topic summary is now ALWAYS given — pass and fail** (was:
  optional, fail-only). The model writes it after a new final-turn-only `[[SUMMARY]]` token
  (lets the backend insert the verdict bubble between feedback and summary); if the model
  omits the token, the backend renders a deterministic fallback from the authoritative
  `category_breakdown` (categories ≥80% = strengths, below = needs work, names only).
  Summary is qualitative only (no numbers) — keeps the "model writes no numbers" contract.
- **Pass/fail closing copy is backend-rendered static text** in `results.py` `_LOCALES`
  (en/de/nl): pass = client's verbatim motivational text + certificate notice; fail = drafted
  encouragement + "80% needed, send a message to start a new attempt" (preserves the existing
  fail→auto-restart behavior). Client can tweak wording later in one place.
- **GoLive note:** the question count ("20") lives in `results.py QUESTIONS_PER_RUN`
  (backend-authoritative, now also interpolated into the state-injection strings) and in the
  three `initialAssistantMsg` welcome strings — change both places before GoLive.
- **New backend defense: strip a pool question the model leaks as free text.** Observed in a
  live run: after finalising a question, the model emitted a (lightly reworded) pool question
  ("What are the four age groups…" vs the pooled "Describe the four age groups…") as its own
  paragraph, which then displayed right above the real backend-rendered next question. The
  existing `[[ASK]]` suffix-discard only guards *ask* turns; on a finalisation/chain turn the
  model's body is passed through, so the leak surfaced. Root cause is model non-compliance with
  the "write NO visible question text" contract; fix is display-only (scoring, plan, and counter
  were already correct — the leak carried no marker). Matching uses the single longest contiguous
  run shared with each pool question (≥0.8 of question length) so light rewording is caught while
  ordinary feedback — which shares no long run with any question — is kept; marker-bearing
  paragraphs are preserved untouched so `[[SCORE]]/[[ASK]]/[[SUMMARY]]` still replay. Applied to
  the model body *before* the backend inserts its own question, so the authoritative rendered
  question is never stripped.

### Changes

- `app/frontend/src/chatbots/shared/theme/chatbotThemes.ts`: hyrox-assessment seed gained
  `overrides` (navbar black/yellow, userBubble white/black).
- `app/frontend/src/chatbots/shared/answer/SharedAnswer.module.css`: bubble/text/heading/
  strong/em/assistant-name colors parametrized as `--chatbot-answer-*` vars with the previous
  values as defaults.
- `app/frontend/src/chatbots/shared/answer/ChatbotAnswer.tsx` and
  `app/frontend/src/chatbots/shared/speech/SpeechOutputAzureButton.tsx`: icon color
  `black` → `var(--chatbot-answer-action-color, black)`.
- `app/frontend/src/chatbots/hyrox-assessment/`:
  - `pages/layout/Layout.tsx`: removed the header logo circle (lemon robot) + unused imports.
  - `pages/chat/Chat.module.css`: sets the `--chatbot-answer-*` vars (black bubble, white
    text, yellow assistant name, white action icons).
  - `pages/chat/Chat.tsx`: both render loops split each stored assistant message at
    `[[BREAK]]` via `splitAssessmentBubbles` and render one `<Answer>` per segment
    (follow-ups only on the last segment); lemon logo import swapped to `HYROX.svg`.
  - `components/Answer/Answer.tsx`: avatar `lemon-chatbot.png` → `assets/HYROX.svg`.
  - `components/Answer/assessmentMarkers.ts`: marker regex extended with `SUMMARY|BREAK`;
    new `splitAssessmentBubbles()`; re-exported via `components/Answer/index.ts`.
  - `components/Answer/SpeechOutputBrowser.tsx`, `AnswerLoading.tsx`, `Answer.module.css`:
    action/loader colors + loading/error bubble follow the answer CSS vars.
  - `locales/{en,de,nl}/translation.json`: `pageTitle`/`headerTitle` → "HYROX Assessment";
    new "Managing Performance" welcome message with `Type "Start"` instruction (20 questions,
    one revision per question, 80% to pass, topic summary at the end).
- `app/backend/approaches/chatbots/hyrox_assessment/results.py`: new `SUMMARY_TOKEN_RE`,
  `BUBBLE_BREAK_TOKEN`/`BUBBLE_BREAK_SEPARATOR`, `ANY_MARKER_RE` extended; `_LOCALES` gained
  `summary_*`, `motivational_passed/failed`, `closing_passed/failed` (en/de/nl); new
  `render_summary_fallback()` + `render_completion_bubbles()`; `render_assessment_turn`
  routes the completion turn through the bubble assembly (hidden `[[SCORE]]` re-appended at
  the end so it still replays); `build_state_injection` final-question instruction now
  requires feedback → `[[SUMMARY]]` → always-take-aways, and interpolates
  `QUESTIONS_PER_RUN`/`PASS_THRESHOLD_PERCENT` instead of hardcoded "20"/"80".
- `app/backend/approaches/chatbots/hyrox_assessment/sampleprompt.py`: "THE TOKENS" section
  documents `[[SUMMARY]]`; "Closing" section now mandates take-aways in both pass and fail.
- `tests/test_hyrox_assessment.py`: new `_completion_turn` helper; tests for the 5-bubble
  passed/failed endings, deterministic summary fallback, `strip_markers` covering
  `BREAK`/`SUMMARY`, and the final-question state injection. 44 passed; `ty check` clean;
  frontend `npm run build` green.
- `app/backend/approaches/chatbots/hyrox_assessment/results.py`: `import difflib`; new
  `paragraph_reproduces_pool_question()` + `strip_leaked_question_text()` (with
  `_NORMALIZED_POOL_QUESTIONS`, `_LEAKED_QUESTION_MATCH_THRESHOLD=0.8`, `_MIN_QUESTION_MATCH_CHARS`,
  `_PARAGRAPH_SPLIT_RE`, `_normalize_for_match`); `render_assessment_turn` now runs
  `strip_leaked_question_text` on the model body right after `strip_rendered_numbers`.
- `tests/test_hyrox_assessment.py`: added `test_strip_leaked_question_text_removes_reworded_pool_question`
  and `test_render_assessment_turn_drops_leaked_question_on_finalisation`. 46 passed; `ty check` clean.
- **HYROX answer card icon hover fix.** Fluent UI `IconButton` default hover is near-white
  (`#f3f2f1`), which rendered the white icons invisible on hover over the black answer card.
  - `app/frontend/src/chatbots/hyrox-assessment/pages/chat/Chat.module.css`: added
    `--chatbot-answer-action-hover-background: rgba(255,255,255,0.15)` and
    `--chatbot-answer-action-pressed-background: rgba(255,255,255,0.25)` to `.container`.
  - `app/frontend/src/chatbots/shared/answer/ChatbotAnswer.tsx`: copy `IconButton` now
    passes `styles={{ rootHovered, rootPressed }}` using the CSS variable (fallback `#f3f2f1`/
    `#edebe9` preserves Fluent UI defaults for all other bots).
  - `app/frontend/src/chatbots/shared/speech/SpeechOutputAzureButton.tsx`: same `styles` prop
    on the volume/stop `IconButton` — this is the speech button HYROX actually renders
    (Azure speech), so this is the one that fixes the speaker-icon hover. Also added
    `rootDisabled: { backgroundColor: "transparent" }`: while loading the button is
    `disabled` and shows the circular `Sync` icon, whose Fluent default disabled background
    was rendering light/white on the black card.
  - `app/frontend/src/chatbots/hyrox-assessment/components/Answer/SpeechOutputBrowser.tsx`:
    same `styles` prop on the volume `IconButton` (browser-speech fallback variant).

---

## 2026-06-09

### Decisions

- **Embed-demo page + widget launcher now follow per-bot brand colors instead of a hardcoded
  indigo.** The `/embed-demo` page chrome was recolored to nerilio purple (`#ac44c6`), and its
  default-selected bot changed to `publishone` (via a new `EMBED_DEMO_DEFAULT_CHATBOT` constant —
  the global `DEFAULT_CHATBOT_NAME` used for routing fallbacks stays `nerilio`).
  - **The launcher bubble color is resolved at widget build time from `chatbotThemes.ts`**, not by
    the backend or the demo page. The backend container ships only built `static/`, not the TS
    source, so it cannot read theme colors at runtime; but `widget.js` is itself built from TS by
    `vite.widget.config.ts`, so `widget.ts` now imports the shared `chatbotThemes` map directly.
    This keeps a single source of truth, works for every external embed (not just the demo), and
    has no first-open lag. Type-only React import in `chatbotThemes.ts` is erased and unused theme
    helpers tree-shake out — `widget.js` stays ~8.9 kB. Color precedence:
    `data-primary-color` > the bot's theme `primary` > generic `#4f46e5` fallback.
- **Added a one-snippet embeddable chatbot widget (Google-Analytics/Intercom style).** Website
  owners embed any bot with a single `<script async src=".../widget.js" data-chatbot-id="...">`
  tag; a floating bubble renders itself with no HTML/CSS work and auto-updates.
  - **Rendering = iframe, not a native injected app.** A tiny dependency-free loader injects a
    launcher + an iframe pointing at the *existing* `/<chatbotId>?embed=1` page. Chosen because the
    chat is already a self-contained per-bot route, the iframe fully isolates CSS/JS from the host
    site, and — crucially — chat calls inside the iframe are **same-origin to the backend, so no
    CORS is needed** on customer sites. (A Shadow-DOM React injection was rejected: larger script,
    CSS/JS conflict risk, cross-origin/CORS complexity, and heavy refactoring.)
  - **`chatbotId` = the existing bot route name** (e.g. `lemon`). Simplest possible; no new
    mapping store or admin. Trade-off accepted: internal bot names are visible to customers.
  - **All bots embeddable, per-bot login preserved inside the iframe.** Simple-auth cookies are
    upgraded to `SameSite=None; Secure; Partitioned` (CHIPS) over HTTPS so they survive a
    cross-site iframe. Quart 0.20 `set_cookie` has no `partitioned` param (confirmed via Context7),
    so the attribute is appended to the emitted `Set-Cookie` header. Documented residual limit:
    **MSAL/Entra-gated bots cannot be embedded** (interactive sign-in won't run in a third-party
    iframe), and hardened privacy modes may still block partitioned storage.
  - **Allow-all framing** via `Content-Security-Policy: frame-ancestors *` on the SPA index; chose
    allow-all for now (can be tightened to a customer allowlist later if opaque IDs are added). No
    `X-Frame-Options` is set (and it's stripped defensively).
  - **Snippet generator UI** added to the internal Chatbot Directory cards (copy-paste snippet +
    live iframe preview), for a GA-like onboarding experience.

### Changes

- `app/frontend/src/widget/widget.ts`: imports `chatbotThemes` and resolves the launcher color as
  `data-primary-color || chatbotThemes[chatbotId]?.primary || DEFAULT_PRIMARY_COLOR`. Rebuilt
  `app/backend/static/widget.js`.
- `app/backend/embed_demo.html`: recolored brand vars/gradient/badge/focus-ring to nerilio purple
  (`#ac44c6` / `#8f30a8`).
- `app/backend/app.py`: added `EMBED_DEMO_DEFAULT_CHATBOT = "publishone"`; the `/embed-demo` picker
  now pins that bot first (falls back to `DEFAULT_CHATBOT_NAME` if absent).
- `app/frontend/src/widget/widget.ts` (new): vanilla-TS loader — derives backend origin from its
  own `<script src>`, reads `data-*` config, command-queue stub for `window.chatbot`, Shadow-DOM
  launcher + lazy iframe, origin-checked `postMessage` bridge.
- `app/frontend/vite.widget.config.ts` (new): lib/IIFE build → `app/backend/static/widget.js`
  (`emptyOutDir: false`). `app/frontend/package.json` build script now chains it after the main
  `vite build`.
- `app/frontend/src/chatbots/shared/embed/embedMode.ts` + `EmbedBridge.tsx` (new): `?embed=1`
  detection, ready/close bridge, mobile close button.
- `app/frontend/src/index.tsx`, `ChatbotThemeRoot.tsx`, `index.css`: set `data-embed="1"` on the
  theme root and mount `EmbedBridge` in embed mode.
- `app/frontend/src/pages/EmbedSnippetModal.tsx` (+ `.module.css`) and `ChatbotDirectory.tsx`
  (+ `.module.css`): per-card **Embed** button opening the snippet generator.
- `app/backend/app.py`: new `/widget.js` route (short cache, correct content-type);
  `serve_spa_index` now sends `frame-ancestors *` and strips `X-Frame-Options`; simple-chatbot
  logout passes `secure=` to `clear_session_cookie`.
- `app/backend/core/simplechatbotauth.py`: `set_session_cookie`/`clear_session_cookie` emit
  `SameSite=None; Secure; Partitioned` when secure; added `mark_set_cookie_partitioned` helper.
- Tests: `tests/test_simplechatbotauth.py` (new) for cookie attributes; `tests/test_app.py` adds
  `/widget.js` and SPA-framing tests. All pass.
- Docs: `docs/embedding.md` (new) + link in `docs/README.md`; `CLAUDE.md` Contracts entry.

### Follow-up: embed layout fixes (from live testing)

- **Two embed-only visual bugs fixed.** (1) The in-iframe close button overlapped each bot's
  navbar menu (`...`); (2) content showed more right margin than left.
  - **Removed the floating in-iframe close button entirely** (`EmbedBridge` now only posts
    `chatbot:ready` and renders nothing). The host launcher is the single close control — it
    toggles to an ✕ and now stays visible on **all** screen sizes, so the widget never injects
    chrome that can collide with the bot's own header. On mobile the panel is near-fullscreen but
    leaves an 88px gap at the bottom so the launcher peeks through as the close control (was:
    fullscreen + launcher hidden + floating ✕).
  - **Margin asymmetry was `scrollbar-gutter: stable` (right-only gutter)** reserving ~scrollbar
    width only on the right under the desktop iframe's classic scrollbar (the full-page/mobile
    views use overlay scrollbars, hence no symptom there). Fixed by **hiding the scrollbars in
    embed mode** (`[data-embed="1"] * { scrollbar-width: none; scrollbar-gutter: auto !important }`
    and `[data-embed="1"] ::-webkit-scrollbar { width: 0; height: 0 }`), which collapses the right
    gutter so the right margin shrinks to match the left; content still scrolls via
    wheel/trackpad/touch. Scoped to embed mode only.
    - **First attempt was wrong and reverted:** `scrollbar-gutter: stable both-edges !important`
      on `*` made it symmetric but by *adding* a left gutter (not removing the right), and worse,
      `stable` reserves a gutter on every `overflow:hidden` box — which clipped FluentUI icon
      buttons and made icons disappear. Lesson recorded: never apply `scrollbar-gutter: stable`
      via a universal selector.
  - Removed the now-unused `isFramed` helper from `embedMode.ts`. Verified in a real browser
    (publishone, desktop + 390px mobile) over HTTP cross-origin: icons render and margins are
    symmetric.
- Files: `app/frontend/src/chatbots/shared/embed/EmbedBridge.tsx`, `embedMode.ts`,
  `app/frontend/src/widget/widget.ts`, `app/frontend/src/index.css`. Added `samples/embed-demo.html`
  (a self-contained dummy site for pasting/testing the snippet).

### Follow-up: drag-to-resize the widget panel

- **Made the desktop widget panel resizable.** Added top-edge, inner-side-edge, and corner drag
  handles to the widget panel (`widget.ts`). The panel is anchored to its corner, so handles live
  on the opposite edges and it grows toward the open side; a subtle grip shows on hover. Uses
  Pointer Events with `setPointerCapture` (plus `.resizing iframe { pointer-events: none }`) so the
  drag survives moving over the cross-origin iframe. Size is clamped to
  `[320×380, viewport−40]`, applied via `--cw-width`/`--cw-height` custom properties (so the mobile
  media query's explicit width/height still wins on small screens), and **persisted per chatbot in
  `localStorage` (`chatbot-widget-size:<id>`)** and restored on reopen/reload. Handles are hidden
  on ≤480px (panel is near-fullscreen there). Verified in-browser: 400×640 → 620×800 on drag,
  persisted across reload. Docs updated in `docs/embedding.md`.

### Follow-up: served `/embed-demo` page with a chatbot picker

- **Replaced the static `samples/embed-demo.html` with a served `/embed-demo` endpoint.** New
  backend route (`app/backend/app.py`) renders `app/backend/embed_demo.html`, injecting the
  `<option>` list from `KNOWN_CHATBOT_NAMES` (so it never drifts; `internal` and `public-test` are
  excluded, `nerilio`/default first). The page derives `/widget.js` from its own origin, shows the
  exact copy-paste snippet for the selected bot, and a dropdown switches the chatbot — reloading
  with `?bot=<id>` and auto-opening that bot's popup (programmatic `chatbot.init()`+`open()`).
  Dummy "Northwind Freight" marketing copy removed; page content now describes the embed feature.
  Deleted `samples/embed-demo.html` (and the now-empty `samples/`). Test:
  `tests/test_app.py::test_embed_demo_page_renders_chatbot_options`. Verified in-browser: default
  opens nerilio, picking publishone reloads to `?bot=publishone` and opens `/publishone?embed=1`.

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
- **Upgraded the give-up fix from a length-gated substring search to whole-message
  anchoring ("Option A"), closing the short-answer residual.** The length gate alone
  still misread a *short* answer that merely contained a trigger word (e.g. "run to
  the next station", ≤8 words with "next") as a give-up. Replaced the substring
  `_GIVE_UP_OR_META_RE.search` with `_GIVE_UP_OR_META_FULL_RE.fullmatch` over a
  normalised copy of the message: detection now requires the **whole message** to BE
  a give-up phrase, allowing only trivial leading/trailing filler ("ok", "please",
  "sorry", …). A trigger word embedded in a real answer can no longer match.
  - `normalize_give_up_text()` lowercases, drops apostrophes, and collapses every
    non-letter/digit run to one space, so matching is robust to punctuation/quote
    style and to umlauts/ß ("Next!" → "next", "I don't know." → "i dont know").
  - The ≤8-word gate is kept as a cheap pre-check that also bounds regex backtracking.
  - **Behaviour vs Option B (delete detection):** identical on every real answer;
    they differ only on clean explicit give-ups, where Option A finalises in one turn
    and Option B would offer the (declinable) correction first. Chose A to keep the
    one-turn give-up UX. The phrase list is curated (en/de/nl); an elaborate
    un-enumerated give-up like "I'll pass on this one" safely falls through to the
    one-correction path rather than risk a false positive.

### Changes

- `app/backend/approaches/chatbots/hyrox_assessment/results.py`:
  - (initial) added `_GIVE_UP_MAX_WORDS` + `is_give_up_or_meta()` and switched
    `_current_question_interaction` off the raw substring regex.
  - (Option A) replaced the substring `_GIVE_UP_OR_META_RE` with `_GIVE_UP_FILLER` +
    `_GIVE_UP_CORE` → anchored `_GIVE_UP_OR_META_FULL_RE`, added
    `normalize_give_up_text()`, and made `is_give_up_or_meta()` normalise + `fullmatch`
    (length gate retained).
- `tests/test_hyrox_assessment.py`: `test_is_give_up_or_meta_only_matches_whole_message_give_ups`
  (filler wrappers, punctuation, en/de/nl, plus the "run to the next station" /
  "next station" / "ill pass on this one" anchoring cases) and
  `test_substantive_first_answer_with_trigger_word_is_not_finalized` (regression for
  the reported "before the next attempt" answer). Full bot suite: 39 passed;
  `ty check` clean.

### Decisions (live smoke test for the assessment bot)

- **Added an opt-in live-model test, because this bot's biggest unverified risk is
  real-model compliance with its prompt/marker contract — which mocks can't see.**
  The deterministic engine is already unit-tested; the open question is whether the
  real `gpt-5.4-mini` actually emits well-formed markers, shows one question at a
  time, grades+progresses, and never leaks the rubric. Reuses the production
  `setup_openai_client` (OpenAI v1 `base_url` + passwordless `AzureDeveloperCliCredential`)
  and drives real turns through `run_without_streaming` (the bot skips retrieval, so
  Search/Blob stay unused). Assertions are **invariants** (well-formed `[[SCORE]]`,
  no `MODEL ANSWER`/marker/`points=` leak, ≤1 question header per turn, the run
  reaches ≥ Q2 and produces ≥1 score) — never exact text, which would flake on a
  non-deterministic model. It is a **canary, not a per-commit gate**: gated behind
  `RUN_HYROX_LIVE=1` + `AZURE_OPENAI_SERVICE` + `az login`, and `@pytest.mark.live`,
  so it is skipped in the normal/offline suite. (#1/#3 hardening were rewound earlier
  this day and are intentionally not reflected here.)

### Changes (live smoke test)

- `tests/test_hyrox_live.py` (new): `@pytest.mark.live`, creds-guarded smoke test that
  runs ~4 real turns and asserts the marker/no-leak/one-question/progress invariants.
- `pyproject.toml`: registered the `live` pytest marker. Default run: 39 passed,
  1 skipped (the live test), no marker warnings.

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
