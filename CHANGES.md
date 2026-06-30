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

## 2026-06-30

### HYROX assessment — web-frontend completion signal (`web_frontend=true`)

#### Decisions

- **The completion hand-off now branches on host context.** The client embeds the bot in
  their web frontend (an iframe on their LMS page), which cannot act on the native
  `lemon://save_progress` scheme nor on our structured `{ type: "chatbot:save-progress" }`
  message. They added a launch flag `web_frontend=true` and listen on the parent page for the
  exact literal string `window.parent.postMessage("Content-Typ-13-finished", "*")`. The
  existing completion *plumbing* (`[[PROGRESS value=100]]` marker → `parseProgressValue` →
  one-shot `progressReportedRef` fire) was reused unchanged; only the final emission is
  switched per host.
- **Literal string hardcoded as a documented constant** (`WEB_FRONTEND_DONE_MESSAGE`), not
  URL-param-driven — matches the client's contract; `"Content-Typ-13"` is the host's LMS
  content id. Revisit only if more content types appear.
- **Frontend-only — no backend change.** The result is already recorded server-side by
  `account_id` regardless of host, so the flag purely selects the client-side completion
  channel. `email`/name still ignored (client said so); `language` stays hardcoded `"en"`.
- **Bare-string payload (not a `{ type }` object)** and `'*'` target are intentional: the host
  listener matches the literal string, and we don't control the host origin (payload carries no
  secrets). In web mode the meaningless `lemon://` scheme is deliberately not fired.
- **Operational caveat (not code):** for the host iframe to load, `hyrox-assessment` must have a
  permissive/empty embed whitelist (⇒ `frame-ancestors *`) or the host origin must be
  whitelisted; otherwise the `postMessage` never fires. No `X-Frame-Options` is set.

#### Changes

- `app/frontend/src/chatbots/hyrox-assessment/lemonBridge.ts`: added `webFrontend?: boolean` to
  `LemonAccount`; `readLemonAccount()` reads `web_frontend=true` and includes it in the
  persist/restore gate; added `WEB_FRONTEND_DONE_MESSAGE` constant and `reportWebFrontendCompletion()`.
- `app/frontend/src/chatbots/hyrox-assessment/pages/chat/Chat.tsx`: imported
  `reportWebFrontendCompletion`; `maybeReportLemonProgress` now branches on
  `lemonAccount.webFrontend` (web → string `postMessage`; app → existing `lemon://` path). One-shot
  guard and `clearChat` re-arm cover both paths unchanged.
- `tests/e2e.py`: added `drive_hyrox_completion_in_iframe()` helper plus
  `test_hyrox_assessment_web_frontend_posts_completion_string` and
  `test_hyrox_assessment_app_launch_posts_save_progress`. They run the bot **inside an iframe**
  (required — `reportLemonProgress` only posts when `window.parent !== window`, so a top-level page
  can't exercise the app path) and assert the two completion channels are mutually exclusive:
  `web_frontend=true` ⇒ the literal `Content-Typ-13-finished` string and no `chatbot:save-progress`;
  no flag ⇒ the structured `{ type: "chatbot:save-progress", value: 100 }` and no literal string.
  Verified locally (rebuilt frontend + live server) and via a vite-dev route-mock run.

### Internal bot — restore welcome Tutor/Q&A buttons for tutor source bots

#### Decisions

- **The internal shell's welcome message must carry the same `[[CHOICES kind=mode]]`
  marker that standalone tutor bots append in their own `Chat.tsx`.** Standalone tutor
  bots (lemon, demo, fbn, knoll, moodle, publishone, steuertipps, bensberg) append
  `\n\n[[CHOICES kind=mode]][[/CHOICES]]` to `initialAssistantMsg`; the internal shell
  built its welcome via `getSourceBotWelcome()` without it, so selecting a tutor source
  bot showed the welcome text with no Tutor/Q&A buttons.
- **Tutor vs Q&A source bots are distinguished by the presence of `options.mode.*` i18n
  keys** (rather than importing the registry, which would create a circular import with
  `internal/index.ts`). Only dual-mode tutor bots ship `options.mode.checkKnowledge`;
  Q&A-only bots (agindo, fhg, nerilio, sartorius, vjoonk4) do not and must not get the
  welcome mode buttons. The empty marker body is intentional — the internal shell supplies
  the localized button labels from its own `options.mode.*` i18n.

#### Changes

- `app/frontend/src/chatbots/internal/sourceBots.ts`: `getSourceBotWelcome()` now appends
  the `MODE_CHOICE_MARKER` to `initialAssistantMsg` when `isTutorModeSourceBot()` is true.

### LLM Wiki — a 3rd retrieval mode (Karpathy-style), piloted on the Internal bot

#### Decisions

- **Added a third retrieval mode "LLM Wiki" alongside the existing standard-search
  and agentic-retrieval modes.** Instead of vector search, the model navigates a
  curated set of LLM-authored markdown pages (a master `index.md` + topic pages with
  YAML frontmatter and `[[wikilinks]]`). Goal: better answer quality on complex /
  multi-hop queries, in both Q&A and Tutor modes.
- **It hooks in at the single retrieval branch in `run_until_final_call`** as a new
  `elif overrides.get("use_llm_wiki")` above agentic, returning the same `ExtraInfo`
  shape (sources only, `answer=None`). Everything downstream — the per-bot prompt
  (`render_chatbot_prompt` / blob overrides / `/manage-prompts`), tutor flow, counters,
  lemon-style sanitization — is **unchanged and shared across all three modes**. So the
  prompt is set exactly like the other modes; no separate answer-prompt system.
- **Navigation = bounded agentic loop** (chosen over single-shot for quality): round 1
  selects pages from the index; up to 2 follow-up rounds may pull pages discovered via
  `[[wikilinks]]`, hard-capped at ~8 pages total. Simple queries terminate after round 1.
  The loop runs as cheap internal LLM calls (lowest reasoning effort, like `rewrite_query`).
- **Storage = Azure Blob**, mirroring `ChatbotPromptStore` (new container `chatbot-wikis`,
  `wiki/<category>/index.md` + `pages/<slug>.md`), runtime-regenerable without redeploy.
  Original source files are untouched — the wiki is an additive layer; page frontmatter
  `sources:` carries the original citation handle so citations resolve as usual.
- **Isolation (hard requirement): only the Internal bot gets the mode.** The branch fires
  only when `use_llm_wiki` is truthy (no other bot's frontend sets it), degrades to standard
  search when no wiki exists for the category, and `showLlmWikiOption` is consumed only by
  the Internal UI. All backend edits are additive; no existing retrieval path or shared
  component was modified. Verified there was **no** pre-existing `content/llm_wiki` to seed
  from (an earlier reference to one was a subagent confabulation) — the wiki is built fresh.
- **Pilot corpus = `lemon`** (HYROX Academy Level 1, `content/lemon/HYROX_Level_1.json`,
  84 records), surfaced through the Internal bot via `source_chatbot=lemon`. `USE_LLM_WIKI`
  defaults on in code for the pilot; the azd env var is deferred.
- **Authoring = LLM build script** (`app/backend/build_wiki.py`), reusing the in-repo Azure
  OpenAI client (no new infra). One topic page per source record + a synthesized index.
  Building the wiki + A/B quality testing in the Internal bot is the remaining manual,
  azd-gated step. The Karpathy "lint"/auto-maintenance op and rollout to other bots are
  out of scope for the pilot.

#### Changes

- **New:** `app/backend/core/chatbotwikistore.py` — blob-backed wiki store (mirror of
  `chatbotpromptstore.py`; markdown not JSON), with `normalize_category`/`normalize_slug`
  (path-traversal-safe) and `load_index`/`load_page`/`has_wiki`/`list_page_slugs` +
  `save_*` for the build script.
- **New:** `app/backend/approaches/prompts/wiki_navigate.system.jinja2` — fixed internal
  page-selection/navigation template (NOT the per-bot answer prompt).
- **New:** `app/backend/build_wiki.py` — `python app/backend/build_wiki.py --category lemon
  [--dry-run]`; loads source records, LLM-synthesizes index + pages, uploads via the store.
- **New tests:** `tests/test_chatbotwikistore.py`, `tests/test_wiki_navigation.py` (store
  round-trips + slug safety + the 4 navigation helpers) — 15 tests, all green.
- **Modified `app/backend/approaches/chatreadretrieveread.py`:** added the `use_llm_wiki`
  branch, `run_wiki_approach()`, and module-level helpers (`split_wiki_frontmatter`,
  `wiki_page_citation`, `extract_wiki_links`, `parse_wiki_page_selection`); new optional
  `wiki_store` constructor kwarg.
- **Modified `app/backend/app.py` + `config.py`:** construct/inject `ChatbotWikiStore`,
  `USE_LLM_WIKI` env (default on), `CONFIG_LLM_WIKI_ENABLED`, and `showLlmWikiOption` in
  `/config`. (lemon was already an allowed Internal source bot.)
- **Modified frontend (additive):** `app/frontend/src/api/models.ts` (`use_llm_wiki?`,
  `showLlmWikiOption?`); Internal bot only — `chatbots/internal/components/Settings/Settings.tsx`
  (LLM-Wiki checkbox + `usesManagedRetrieval` gating), `pages/chat/Chat.tsx` (state, config
  read, override, mutual exclusivity with agentic), and `en`/`de`/`nl` locale strings.
- **Checks:** `ty check` clean on all changed backend files; frontend `tsc --noEmit` and
  `npm run build` succeed; backend wiki/registry/prompt-store tests green.

#### Follow-up (same day)

- **Built + uploaded the lemon wiki** (84 pages + index) to `chatbot-wikis/wiki/lemon/` on the
  `agentic-retrieval-nerilio` env (storage `stbfmtryd6z3arm` — the live backend's account), via
  `build_wiki.py --category lemon --reasoning-effort low`. Verified through `ChatbotWikiStore`:
  `has_wiki("lemon")` True, 84 pages. No backend restart needed (store reads blob live).
- **`build_wiki.py` improvements:** added `--limit N` (cheap smoke testing) and `--reasoning-effort`;
  raised `MAX_SOURCE_CHARS` to 24000 (long HYROX lessons were being cut mid-article) and
  `PAGE_RESPONSE_TOKENS` to 8000 (reasoning-model output headroom).
- **Made the wiki fallback visible:** when LLM-Wiki mode is requested but no wiki exists for the
  category, `run_wiki_approach` now inserts a `ThoughtStep` ("LLM Wiki requested but unavailable —
  fell back to standard search") so the thought panel shows what happened instead of looking like
  plain search.
- **Rebuilt the lemon wiki at `medium` effort** after the `low` build was found to lose content on
  5/84 pages: 2 lost real text (input cap 24k < the 95k/36k-char longest lessons) and 3 fell back to
  raw transcript on JSON parse failures. Hardened `build_wiki.py` — input cap 24k→120k chars, output
  8k→16k tokens, and `response_format={"type":"json_object"}` to guarantee valid JSON. The medium
  rebuild overwrote the low build in place (same deterministic slugs): 84/84 pages cleanly
  synthesized, **0 fallbacks**; the worst case ("Essence of Athletic Performance") now built from the
  full source. A/B on a complex multi-hop coaching question had the wiki answer beat agentic (tighter
  diagnosis→prescription synthesis, more faithful specifics, correct source-limit honesty/contact
  fallback vs agentic offering a week-by-week the materials don't contain).
- **Decision — kept pages-only retrieval (Karpathy default), did not add hybrid/raw-at-answer-time.**
  For the messy-transcript lemon corpus, feeding raw chunks back alongside the synthesized pages
  would reinject the noise the wiki removes (and ~2× tokens). The quality lever is build-time
  synthesis effort, not answer-time raw. Raw source stays preserved in `content/lemon/` and linked
  via each page's `sources:` frontmatter. Revisit hybrid only if A/B testing shows synthesis is lossy.

## 2026-06-29

### App folder cleanup & `src/pages/` reorganization

#### Decisions

- **Scope was deliberately limited to zero-/compile-risk cleanup** (user
  decision): delete dead/orphaned files and reorganize the flat
  `app/frontend/src/pages/` folder. **Explicitly chose NOT to touch** the large
  per-bot frontend duplication (~15 bots × ~95 near-duplicate files) or move the
  backend one-off scripts — both are higher-risk and were left for a separate,
  opt-in effort.
- **`src/pages/` now follows one-folder-per-page**, mirroring the existing
  well-organized `pages/verwaltung/` convention, with a `pages/shared/` layer for
  the cross-page internal-admin building blocks. Per-folder `index.ts` barrels
  keep the `index.tsx` route imports stable.

#### Changes

- **Deleted (dead/orphaned, referenced by nothing):**
  - Empty untracked dirs `app/frontend/src/chatbots/helix/`,
    `chatbots/test/`, and the nested copy-paste artifact `chatbots/fbn/chatbots/`.
  - `app/backend/approaches/chatbots/test/` — orphaned `__pycache__/*.pyc` only
    (source already gone; never in `KNOWN_CHATBOT_NAMES`).
  - `git rm app/backend/approaches/chatbots/lemon/sampleprompt-old.py` — legacy
    prompt backup superseded by `sampleprompt.py`, imported nowhere.
- **Reorganized `app/frontend/src/pages/`** (via `git mv`):
  - Page components + their `.module.css` + their API client grouped into
    `ChatbotDirectory/` (incl. `EmbedSnippetModal.tsx` + `embedAdminApi.ts`),
    `ManagePrompts/`, `UploadFiles/`, `FreeUsers/`.
  - Cross-page helpers (`useInternalAdminAccess.ts`, `internalAdminApi.ts`,
    `internalToolsAccess.ts`, `chatbotDisplay.ts`) moved into `pages/shared/`.
  - Added one-line `index.ts` barrels per page folder. `pages/verwaltung/`
    left unchanged.
- **Updated imports:** 3 specifiers in `src/index.tsx`; `../shared/...` paths in
  the 4 page components, `EmbedSnippetModal.tsx`, and
  `verwaltung/VerwaltungLayout.tsx`; bumped `ChatbotDirectory.tsx`'s
  `../chatbots/registry` → `../../chatbots/registry` (moved down one level).
- **Verified:** `npx tsc --noEmit` (exit 0) and full `npm run build`
  (vite + chained widget build, exit 0) both pass; `graphify update .` refreshed
  (10227 nodes). No behavior change.

## 2026-06-26

### HYROX assessment → Level 2 "Managing Performance", module-by-module

#### Decisions

- **Replaced the entire question bank and reworked the assessment mechanics per the client's
  `instructions.txt`.** The bot is no longer the Youngstars "20-of-32 flat run, one cumulative 80%
  pass/fail". It is now the **HYROX Level 2 "Managing Performance"** assessment: 52 questions in 13
  modules (`M1`–`M6`, `M7.1`–`M7.4`, `M8`–`M10`), asked **module by module** in fixed order, **every**
  question of a module asked, each module scored separately at an **80% threshold**, a failed module
  **retaken in full** until passed, and the cross-module strengths/weaknesses summary shown only at the
  very end. Because a module is only left by passing it, finishing always means passing everything —
  there is no whole-assessment "fail" end state (the old fail texts were retired; per-module fail gets
  its own transition).
- **LMS completion is now gated on the final module only.** `[[PROGRESS value=100]]`
  (→ `lemon://save_progress`) + `[[DONE]]` fire once, when the last module is passed — never per module
  (the client's explicit requirement). `record_assessment_result` fires on that turn with cross-module
  totals and a per-module breakdown.
- **Question source = the workbook's master `Module 1` tab (all 52 questions), per the user.** It is the
  only tab with the per-module points column the client references; the 7 per-module tabs conflict on
  selection/wording and are treated as superseded drafts (ignored).
- **The L2 knowledge XML is a reference asset only (user decision).** Grading stays purely on each
  question's in-prompt rubric (Primary answer + Alternative answer + Key Points — a complete
  "must be mentioned" spec; `len(key_points)==max_pts` for every question, so 1 point per key point). The
  2.2 MB XML can't go in-prompt and the bot deliberately uses no retrieval; wiring it in would add
  latency/cost/risk for no grading benefit. Committed at `hyrox-files/HYROX_L2_Assessment_Knowledge.xml`.
- **Marker engine extended, not replaced.** Kept the stateless replayed-marker design and the
  one-revision rule; added `[[MODULE m=.. attempt=..]]`, `[[MODPASS]]`, `[[MODFAIL]]` and re-gated
  `[[PROGRESS]]`/`[[DONE]]`. Integer question ids (1..52) preserve the existing `[[SCORE]]`/`[[ASKED]]`
  machinery; the client `M7.1-Q03`-style ids are stored as display/audit metadata.
- **Operating language stays English** (`Chat.tsx` hardcodes `HYROX_ASSESSMENT_LANGUAGE="en"`); de/nl
  locale strings updated for parity but inactive.

#### Changes

- Added `app/backend/prep_hyrox_assessment_questions.py` (stdlib-only xlsx→`questions.py` generator;
  asserts key-point/points and module-sum integrity) and regenerated
  `app/backend/approaches/chatbots/hyrox_assessment/questions.py` (52 questions, new schema with
  `module`/`qid`/`alternative_answer`, `MODULES` + module helpers).
- Rewrote `results.py` (module-by-module state engine, new markers, per-module + completion rendering,
  module-localized `_LOCALES` incl. the client's transition texts, `module_breakdown`) and
  `sampleprompt.py` (rebranded L2, module-flow instructions, renders the alternative answer, grouped by
  module). `config.py`/`chatreadretrieveread.py` integration unchanged.
- Frontend: `components/Answer/assessmentMarkers.ts` (new markers hidden + `hasModulePassMarker`/
  `hasModuleFailMarker`), `pages/chat/Chat.tsx` (Continue/Retry buttons, input hide at boundaries,
  `isControlMessage` suppresses Start/Continue/Retry user bubbles, removed whole-assessment restart),
  `locales/{en,de,nl}/translation.json` (new welcome text, `continueModule`/`retryModule`, Level 2 title).
- Staged `hyrox-files/HYROX_L2_QuestionBank_Final.xlsx` + `…Knowledge.xml`; removed the obsolete
  `hyrox-files/hyrox_assessment_final_v5.xlsx`.
- Rewrote `tests/test_hyrox_assessment.py` for the module engine (31 tests pass). `tests/test_hyrox_live.py`
  left as-is (opt-in, invariant-based, still compatible).
- Docs: updated `CLAUDE.md` (new HYROX-assessment contract bullet + Adding Data generator entry).
- Verification: `pytest tests/test_hyrox_assessment.py` (31 pass), `ty check` clean on the package +
  generator, `npm run build` clean, frontend `tsc --noEmit` clean, and a route-mocked Playwright pass
  driving the full UI flow (Start → question → module pass + Continue → next module → module fail + Retry
  → completion/certificate; markers hidden, input show/hide correct).

### Embed widget: per-bot launcher icon color; hyrox black bubble + yellow icon

#### Decisions

- **The launcher icon was hardcoded white on every bubble, which is poor contrast on hyrox's yellow
  and on the other light/yellow bots.** `hyrox-assessment`'s brand is black chrome + `#FFED00` accent
  (its theme overrides the navbar to black bg / yellow text), but the embed bubble was a yellow
  background with a white icon. Switched the launcher to mirror the *visible chrome* rather than the
  abstract theme `primary`: **black bubble, yellow icon**.
- **Added a first-class, optional per-bot launcher icon (foreground) color** instead of special-casing
  hyrox in the widget. Backend map `EMBED_LAUNCHER_ICON_COLORS` (parallel to `EMBED_LAUNCHER_COLORS`);
  `/embed/<publicId>/config` now also returns `launcherIconColor` (null => the widget's default white).
  The widget threads it through with the same precedence as the bubble color
  (`data-icon-color` > backend config > white default) and applies it to the launcher's `currentColor`
  icon. Also exposed `data-icon-color` as a host override for symmetry with `data-primary-color`.
- **Dark icons for `sartorius` and `steuertipps`; `lemon` and `agindo` left on white.** The same
  white-on-yellow contrast issue existed across the four yellow bubbles; per the user, sartorius and
  steuertipps now use a black icon (`#000000`, matching their navbar's black foreground), while lemon
  and agindo intentionally keep the default white icon.
- **No iframe side effects.** `EmbedBridge` ignores the `chatbot:host-init` `primaryColor`; the launcher
  color only paints the floating bubble, so changing hyrox's bubble background is isolated to the widget.

#### Changes

- [app/backend/app.py](app/backend/app.py): `EMBED_LAUNCHER_COLORS["hyrox-assessment"]` `#FFED00` →
  `#000000`; added `EMBED_LAUNCHER_ICON_COLORS` (`hyrox-assessment` → `#FFED00`; `sartorius` and
  `steuertipps` → `#000000`); `/embed/<publicId>/config` now returns `launcherIconColor`.
- [app/frontend/src/widget/widget.ts](app/frontend/src/widget/widget.ts): `launcherIconColor` on the
  config + remote-config interfaces, `data-icon-color` attribute, `DEFAULT_ICON_COLOR`, `styleSheet`
  takes an icon color (`.launcher { color: … }`), resolved with `data-icon-color` > backend > white.
- [app/backend/embed_demo.html](app/backend/embed_demo.html): documented `data-icon-color` in the
  optional-settings table.

### Embed widget: sync bensberg launcher color to dark-teal rebrand

#### Decisions

- **The chat-bubble launcher color is a backend-side duplicate of the frontend theme `primary`, and
  bensberg's copy was stale.** `EMBED_LAUNCHER_COLORS` in [app.py:782](app/backend/app.py#L782) mirrors
  the `primary` values in [chatbotThemes.ts](app/frontend/src/chatbots/shared/theme/chatbotThemes.ts)
  and is what `/embed/<publicId>/config` returns to `/widget.js` to paint the floating bubble. The
  bensberg rebrand (commit `57318eb7`, dark-teal `#005155` + mint) updated the frontend theme but not
  this map, so the embed-demo bubble (and every real embed) still showed the old yellow `#fec701`
  (identical to lemon, and lower-contrast under the white chat icon). All 16 other embeddable bots
  already matched.

#### Changes

- [app/backend/app.py](app/backend/app.py): `EMBED_LAUNCHER_COLORS["bensberg"]` `#fec701` → `#005155`
  to match the frontend theme `primary`.

---

## 2026-06-24

### snap bot: enable embedding (assign embed public ID)

#### Decisions

- **`snap` is now embeddable — the prior session's deferral is reversed.** The earlier snap session
  documented (below) that snap was *intentionally* left without an embed public ID. User now wants it
  embeddable (snap.de is exactly the intended host), so assigned one. snap is `prompt_mode="override"`,
  not MSAL-gated, so it embeds like the other public bots.
- **One-line change only — everything else was already wired and is data-driven.** `EMBED_PUBLIC_IDS`
  in [embed_public_ids.py](app/backend/embed_public_ids.py) is the single source of truth: `is_embeddable`
  / `get_public_id` derive from it. The `/embed-demo` picker auto-includes any embeddable bot from
  `KNOWN_CHATBOT_NAMES` ([app.py:762](app/backend/app.py#L762)); the directory's Embed modal fetches
  `publicId` from `/internal-admin/embed-config/<name>` (admin endpoint gated on `is_embeddable`,
  [app.py:1422](app/backend/app.py#L1422)); and the launcher color `"snap": "#ac44c6"` was *already*
  present ([app.py:793](app/backend/app.py#L793)). So no frontend, config, or other backend change was
  needed — adding the ID flips snap on across the picker, the directory Embed button (previously 404'd),
  and the `/widget.js` loader.
- **Public ID generated in the repo's own scheme**, collision-checked against the existing 16 (10-char,
  leading letter, lowercase-alnum): `r54q95959d`. Per the file's contract, existing IDs are never edited
  (changing one breaks embeds already in the wild); this only appends.

#### Changes

- `app/backend/embed_public_ids.py`: added `"snap": "r54q95959d"` to `EMBED_PUBLIC_IDS`.
- Verified (with `app/.venv`): `is_embeddable("snap")` → True, `get_public_id("snap")` → `r54q95959d`,
  `resolve_public_id("r54q95959d")` → `snap`, all 17 IDs unique.
- Deployment: app-code only — takes effect after `azd deploy` (no re-provision, no re-index). Per-bot
  allowed-domains whitelist (blob-backed) is empty by default → widget allowed on any site until an
  admin sets a whitelist via the `/chatbots` Embed modal or `/embed-demo`.

### snap bot: tailor prompt to snap.de content + enable url citations (publishone/fhg-style)

#### Decisions

- **The snap prompt was a near-verbatim nerilio find/replace, not tailored — rewrote it.** The
  original `snap/sampleprompt.py` was nerilio's prompt with `nerilio`→`SNAP` swapped, so it framed
  SNAP as a single **SaaS product** with "plans / which plan should they choose / sessions /
  supported formats" and carried pricing rules ("monthly vs. yearly", **zzgl. MwSt.**). But snap.de
  is **SNAP Innovation** (Hamburg), a content-workflow **consultancy + systems integrator** with an
  11-tool portfolio (Axaio, Callas, Caymland, Dataplan, EasyCatalog, Enfocus, nerilio, PublishOne,
  Twixl, vjoon K4, vjoon Seven), plus Beratung, Betrieb & Support, Use Cases and News — and it has
  **zero** pricing content (verified: 0 hits for MwSt/zzgl/€/EUR/Tarif/"pro Monat" across all 43
  docs). Rewrote Role + Source/Knowledge + answer rules to that actual domain; removed the pricing
  rules; added a rule to **never invent prices** and to route pricing/offer/individual-recommendation
  requests to SNAP's consulting/contact channel ({{SUPPORT_EMAIL}}); added a rule to distinguish
  SNAP's own services from the third-party portfolio tools it integrates, and to attribute use-case
  testimonials to the named customer.
- **Citations were invisible purely because of the prompt — prompt-only fix, no frontend/config/backend
  code change.** snap uses `prompt_mode="override"`, so its `SAMPLE_PROMPT` *fully replaces* the base
  RAG prompt ([chat_answer.system.jinja2](app/backend/approaches/prompts/chat_answer.system.jinja2)
  lines 1–2 render only `{{ override_prompt }}`; the base citation instructions on lines 4–7/17 are
  bypassed). The cloned prompt inherited nerilio's line *"Do **not** include citations…"*, so the
  model never emitted citation markers even though `citation_target="url"` and the indexed snap docs
  carry first-class `title`+`url`. Fix: removed the suppression line and added a **Source Citations**
  block mirroring publishone (square-bracket citations + the `{{POSSIBLE_CITATIONS_PROMPT}}`
  placeholder, which `render_chatbot_prompt` fills with the live URLs **only** in override mode —
  [approach.py:1019](app/backend/approaches/approach.py#L1019)). The shared frontend
  (`ChatbotAnswer.tsx` / `answerParsing.ts`) already renders url-target citations by showing the
  document **title** (`external_results_metadata[i].title`) and opening the live **url** in a new tab
  (`target="_blank"`), identical to publishone/fhg — so **no frontend change**. **No re-indexing
  needed** (snap docs already carry title+url). Kept `prompt_mode="override"` (did not switch to
  `inject`) so the base RAG prompt does not interfere.
- **Fixed a pre-existing red test left by the prior snap session.**
  `tests/test_snapjson.py::test_to_search_document_includes_title_and_url` expected
  `SnapPreparedDocument.to_search_document()`, a method both sibling parsers (`hyroxjson`/`fhgjson`)
  have but snap's clone omitted. Added it verbatim (snap's dataclass fields are identical to
  hyrox's). It is the direct index-upload serializer used by the `prep_*_json.py` CLIs; snap ingests
  via `Section`s (admin upload → `parse_file`), so it is not on snap's active path, but adding it
  greens the test and keeps the parser consistent with its siblings.

#### Changes

- `app/backend/approaches/chatbots/snap/sampleprompt.py`: rewrote `SAMPLE_PROMPT` — Role/Source/answer
  rules tailored to SNAP Innovation; removed the SaaS pricing-plan rules; replaced the
  citation-suppression bullet with a **Source Citations** block incl. `{{POSSIBLE_CITATIONS_PROMPT}}`;
  added a citation-coverage item to the Final Reminder. (`config.py` unchanged — already
  `citation_target="url"`, `prompt_mode="override"`.)
- `app/backend/prepdocslib/snapjson.py`: added `SnapPreparedDocument.to_search_document()` mirroring
  `hyroxjson`/`fhgjson`.
- `app/functions/{document_extractor,figure_processor,moodle_auto_indexer,text_processor}/prepdocslib/snapjson.py`:
  refreshed via `python scripts/copy_prepdocslib.py`.
- `tests/test_chatbot_config_registry.py`: added
  `test_snap_prompt_requests_url_citations_instead_of_suppressing_them` and
  `test_render_snap_prompt_injects_url_citations_and_support_email`.
- Verified: `pytest tests/test_snapjson.py tests/test_chatbot_config_registry.py` → **13 passed**
  (run with `app/.venv`). `graphify update` / `ty check` skipped (tools not installed in this env).
- Deployment: prompt change is app-code only — takes effect after `azd deploy` (no re-provision, no
  re-index).

### snap.de scraper + new `/snap` chatbot (clone of nerilio over snap.de content)

#### Decisions

- **Scrape via the WordPress REST API, not HTML crawling.** snap.de is a small (~43 page) WordPress site (Rank Math SEO); `robots.txt` only blocks `/wp-admin/`. `/wp-json/wp/v2/pages` + `/posts` return clean structured JSON with a first-class `link` (live page URL) and `content.rendered`. Tool pages use the Divi page builder, so `content.rendered` is real prose wrapped in `[et_pb_*]` shortcodes + HTML entities — the scraper strips shortcode tags (keeping their text bodies), HTML tags, and decodes entities.
- **Ship content as a JSON feed, not `.md`/`.html`.** Modeled on the existing FHG/HYROX importers so each record carries first-class `title` + live `url`. The generic file pipeline keys citations off the storage blob URL ([filestrategy.py](app/backend/prepdocslib/filestrategy.py) passes `url=blob_url`), which would point citations at a blob instead of the live page.
- **User uploads `data/snap.json` themselves** via the admin managed-file uploader under category `snap`; we do not index it. The `CategoryUploadStrategy.add_file` path runs `parse_file`, which now routes `snap` JSON through a dedicated parser, so the upload produces first-class live-URL citations.
- **`snap` bot reuses nerilio's UI verbatim** (same components/theme/layout) but is rebranded to "SNAP" in visible text (header, greeting, NoPage/contact) per user choice, since it answers over all of SNAP's products. `citation_target="url"` so citations link to the live snap.de page.
- The shared `NoPage` is hardcoded with nerilio links and re-exported by other bots, so `snap` got a forked SNAP-branded `NoPage` (reusing the shared styles/robot asset) rather than editing shared code.
- `snap` has no embed public ID, so it is intentionally not embeddable yet (the embed-demo picker guards with `is_embeddable`); add one via `python -m embed_public_ids` if embedding is wanted. *(Superseded 2026-06-24 — a public ID was later assigned; see the "enable embedding" entry above.)*
- **Completeness audit + Divi attribute recovery.** A per-page audit (live page vs scraped) confirmed all substantive prose is captured; the real losses were short labels held in Divi shortcode *attributes* (team-member names, section/card titles, hero headlines, CTA labels — delimited by `&#8220;` smart-quote entities, not straight quotes). `clean_html` now `html.unescape`s each opening shortcode and emits a whitelist of text-bearing attrs (`title`/`subhead`/`button_text`/`heading`) at the tag's position, so e.g. a team name precedes its bio. Verified: all 8 ueber-uns names + tool-page CTAs + home hero now present, no CSS/URL leakage. Remaining unrecoverable-by-REST: embedded contact/demo forms (external Caymland JS, not in `content.rendered`). The English Polylang locale is empty (`/en/` → 404) so German-only loses nothing; the `project` CPT is empty.
- **End-to-end snap refresh is a single *manual* script for now; automation deferred.** User wants to eventually re-run on snap.de changes but chose to start with a manual command and run it locally. Discussed the "listen" reality: a website can't be push-notified unless it cooperates — true real-time needs a WordPress webhook (plugin/mu-plugin on `save_post`/`deleted_post`) → an HTTP-triggered Azure Function; otherwise "listen" means scheduled polling. Both unattended options also require running in Azure with a managed identity (the local scripts authenticate via `AzureDeveloperCliCredential`, which only works while azd-logged-in). Deferred all of that; built only the manual local orchestrator.
- **Change detection is possible and worthwhile.** Can't reliably diff against `snap.json` alone (its per-doc `date` is day-granular). Instead `fetch_remote_state` queries the WP REST API for the latest `modified` timestamp + total count of pages/posts (two tiny requests) and stores them in `data/snap.state.json`; comparing across runs catches edits, additions, and (via count) deletions. `refresh_snap.py` skips the whole pipeline when unchanged unless `--force`.
- **Reindex = delete-then-add, and scrape-before-delete.** Chunk IDs are deterministic so re-adding overwrites changed pages, but deleted pages would leave orphan chunks — so the refresh deletes category `snap` first, then re-indexes (brief window with no `/snap` results; acceptable for a manual refresh). The scrape runs *before* the delete and the run aborts if it yields zero docs, so a failed scrape never wipes the index; the state watermark is written only after a successful re-index. Confirmed the local ingestion path is active in the deployment env (`rg-agentic-retrieval-nerilio` has no `USE_CLOUD_INGESTION`/`USE_FEATURE_INT_VECTORIZATION`), and that `FileStrategy.setup()`→`create_index` is non-destructive (creates only if absent; otherwise just adds missing fields), so refreshing `snap` cannot wipe other bots' data in the shared index.
- **`content` stored as GitHub-flavored markdown (user choice, over a plain-text recommendation).** Analysis showed plain text is marginally better *for this pipeline*: `clean_source` ([approach.py](app/backend/approaches/approach.py), `get_sources_content`) flattens `\n`→space before sources reach the LLM, so newline-based structure (headings on their own line, tables, list layout) is lost at answer time; embeddings gain nothing from markup tokens; and the rest of the index is plain text (HTML parser uses `soup.get_text()`). The user chose markdown anyway. Net effect that survives flattening: inline emphasis (`**`/`*`) and — the one real gain — **inline body links**, which the plain-text path dropped. `clean_html` now maps headings→ATX, `strong`/`em`→`**`/`*`, `a`→`[text](url)` (relative hrefs absolutized to `https://www.snap.de/…`, `#`/`javascript:`/`data:` dropped but link text kept), `ul`/`ol`→`-`/`N.`, `table`→GFM pipe table, `img`→`![alt](src)` (decorative empty-alt images dropped), `blockquote`→`>`; `<script>`/`<style>` stripped. Regenerated `data/snap.json` = 43 docs / 99 chunks / ~191k chars; verified no raw HTML, shortcode, entity, CSS, or U+FFFD leakage and all 97 links absolute.

#### Changes

- `scripts/scrape_snap.py` (new): stdlib-only WP REST API scraper → `data/snap.json` (`{feed:"snap.de", documents:[{id,title,url,content,tags,type,date}]}`). `clean_html` converts the Divi/HTML body to GitHub-flavored markdown via `_MarkdownExtractor` (headings/emphasis/links/lists/tables/images), recovering Divi shortcode-attribute text inline; `collapse_whitespace` preserves list indentation.
- `data/snap.json` (new): 43 scraped pages/posts, `content` as markdown (deliverable for admin upload; not indexed here).
- `scripts/scrape_snap.py`: added `fetch_remote_state(base_url)` — cheap WP-REST change-detection watermark (latest `modified` + count for pages/posts).
- `app/backend/refresh_snap.py` (new): single manual end-to-end refresh — change-check (`data/snap.state.json`, `--force`/`--check-only`) → re-scrape → delete category `snap` → re-index via `prepdocs.py`. Reuses `scrape_snap.py`, `delete_category_data.py`, `prepdocs.py` as sub-steps; runs locally under the backend venv with azd creds. `data/snap.state.json` is generated state (in untracked `data/`).
- `CLAUDE.md`: added a snap-refresh playbook line under "Adding Data".
- **Indexed the markdown `data/snap.json` into the live index** (category `snap`, 99 chunks in `gptkbindex-nerilio`, blob `content/snap/snap.json`) at the user's request — ran `delete_category_data.py snap` (found 0 existing) then `prepdocs.py data/snap.json --category snap`. The local azd env (`rg-agentic-retrieval-nerilio`) is missing `AZURE_OPENAI_ENDPOINT`, so the run set it to the derived `https://cog-bfmtryd6z3arm.openai.azure.com` plus `USE_AGENTIC_KNOWLEDGEBASE=false` and `LOADING_MODE_FOR_AZD_ENV_VARS=no-override`. Disabling agentic is deliberate: `prepdocs` `setup()`→`create_knowledgebase()` would `create_or_update_knowledge_base` on the production `gptkbindex-nerilio-agent-upgrade` KB ([searchmanager.py:600](app/backend/prepdocslib/searchmanager.py#L600)); document indexing doesn't need it (the agent reads the index at query time). Wrote `data/snap.state.json` watermark so `refresh_snap.py` reports up-to-date.
- `app/backend/prepdocslib/snapjson.py` (new): `prepare_snap_sections` + `build_snap_sections_if_applicable` (gates on category `snap` + `.json` + `feed:"snap.de"` marker; reuses HYROX chunker).
- `app/backend/prepdocslib/filestrategy.py`: `parse_file` now calls `build_snap_sections_if_applicable` after the HYROX hook.
- `app/backend/approaches/chatbots/snap/` (new): `__init__.py`, `config.py` (gpt-4.1-mini, `citation_target="url"`, `support_email="info@snap.de"`), `sampleprompt.py` (nerilio prompt generalized to SNAP).
- `app/backend/approaches/chatbot_prompt_registry.py`: registered `snap` prompt module.
- `app/backend/app.py`: added `snap` to `KNOWN_CHATBOT_NAMES` and `EMBED_LAUNCHER_COLORS`.
- `app/frontend/src/chatbots/snap/` (new): clone of `nerilio/`; edited `index.ts` (`snapChatbot`/name), `pages/chat/Chat.tsx` (`chatbotCategory="snap"`, speech flags), `pages/layout/Layout.tsx` (`/snap` link), forked `pages/NoPage.tsx` (snap.de links), `components/Answer/AnswerLoading.tsx` (alt), and de/en/nl locales (rebranded to SNAP).
- `app/frontend/src/chatbots/registry.ts` + `shared/theme/chatbotThemes.ts`: registered `snap` (gpt-4.1-mini, qna; theme mirrors nerilio `#ac44c6`).
- `app/functions/*/prepdocslib/`: refreshed via `scripts/copy_prepdocslib.py` (picks up `snapjson.py` + `filestrategy.py`).
- `tests/test_snapjson.py` (new) and `tests/test_chatbot_config_registry.py`: snap parser + config coverage.

### Bensberg bot: rename display name from Lemon®AID to Bensberg

#### Decisions

- Display name "Lemon®AID" was replaced with "Bensberg" per client request.

#### Changes

- `app/frontend/src/chatbots/bensberg/locales/de/translation.json`: updated `pageTitle` and `headerTitle` to `"Bensberg"`.
- `app/frontend/src/chatbots/bensberg/locales/en/translation.json`: updated `pageTitle` and `headerTitle` to `"Bensberg"`.
- `app/frontend/src/chatbots/bensberg/locales/nl/translation.json`: updated `pageTitle` and `headerTitle` to `"Bensberg"`.

## 2026-06-23

### Hide tooltips below the desktop breakpoint (mobile/tablet)

#### Decisions

- Tooltips are a pointer-hover affordance; on touch-first viewports they either never trigger
  or pop awkwardly on tap. Requirement: tooltips visible only on desktop and larger.
- Fixed centrally in CSS rather than per-component. Every styled tooltip in the app is a Fluent
  v9 `<Tooltip>` (via shared `TooltipTarget` or direct usage) that renders into the single
  body-portal class `.fui-Tooltip__content`; no Fluent v8 `TooltipHost` exists. So one media
  query hides them across all bots at once.
- Breakpoint chosen to match the project's existing responsive family: desktop = `min-width: 992px`,
  so tooltips are hidden at `max-width: 991.98px` (tablet and below).
- Hides the visual pill only; the underlying controls keep their own `ariaLabel`, so
  accessibility is unaffected. Click-triggered `HelpCallout` info dialogs are not tooltips and
  remain functional on all viewports. Native `title=` attributes are browser-native (not
  CSS-controllable) and don't render on touch devices, so they were left as-is.

#### Changes

- `app/frontend/src/index.css`: added a `@media (max-width: 991.98px)` rule setting
  `.fui-Tooltip__content.fui-Tooltip__content { display: none !important; }`, grouped with the
  existing global tooltip styling block.

## 2026-06-22

### Tutor bots: collapse duplicate running-counter heading in a single bubble

#### Decisions

- Bug (lemon/Lemon®AID screenshot): when the user partially answers then says "I don't know",
  the Case-5 "reveal answer + move to next question" turn renders the next question's counter
  heading **twice** — once spuriously at the top of the turn (above the previous answer's
  feedback) and once correctly right before the next question. The rendering is faithful; the
  **model emits the heading twice** in the raw content.
- Fixed in the **frontend display layer**, not the prompts: a deterministic strip guarantees the
  duplicate is gone regardless of model behavior, fixes **all tutor bots at once** (single shared
  chokepoint), and stays inherently in sync — matching the existing `stripDuplicateTopicList`
  precedent in the same module. Did not edit the 9 tutor `sampleprompt.py` files (a prompt rule
  only lowers probability, isn't guaranteed, and risks drift across variants).
- Rule: each rendered bubble shows exactly one question, so the real heading is always the **last**
  counter occurrence. Drop any *standalone* heading line that precedes a later counter occurrence;
  the final heading (standalone or inline) is preserved. Locale-agnostic — matches all three forms
  (`Frage N von Total:` / `Question N of Total:` / `Vraag N van Total:`).

#### Changes

- `app/frontend/src/chatbots/shared/answer/optionMarkers.ts`: added `COUNTER_HEADING_RE` /
  `COUNTER_HEADING_LINE_RE` and a `dropDuplicateCounterHeadings()` helper; wired it into
  `stripChoiceMarker()` (after `stripDuplicateTopicList`, before final whitespace cleanup) so it
  applies to the main bubble and every `[[SPLIT]]` segment. Verified the exact screenshot content
  (de + en) collapses correctly while single/inline headings and non-tutor text are untouched;
  `tsc --noEmit` clean.

### Bensberg bot rebrand: dark-teal theme + mint accents + new navbar logo

#### Decisions

- Request: bensberg main color `#005155` (top bar etc.), title text `#96f0eb`, user-input bubble
  `#96f0eb`, and a new small navbar logo (attached `bensberg.png`).
- "Color of the textbubbles (user input)" was ambiguous (fill vs. text). User chose **mint bubble
  fill**, so the bubble background is `#96f0eb` with explicit dark-teal `#005155` text (6.91:1
  contrast, ≥ WCAG AA). Title `#96f0eb` on `#005155` navbar is also 6.91:1.
- The attached `bensberg.png` was actually an **AVIF** image with a `.png` extension (header
  `ftypavif`). Converted it to a real PNG in place (Pillow 12 native AVIF decode) so it bundles
  reliably and matches its extension, rather than renaming to `.avif`.
- Only the small navbar logo was swapped (was the lemon logo). The large empty-state mark in
  `Chat.tsx` stays the generic `assets/applogo.svg` per the repo's generic-app-mark contract.
- Follow-up: the assistant-bubble avatar was still the lemon logo because bensberg reused lemon's
  shared `Answer` (`createBotAnswer(lemonChatbotLogo, …)`). Gave bensberg its **own** `Answer` built
  with `bensberg.png` rather than editing lemon's (shared by lemon + other bots). `AnswerError` /
  `AnswerLoading` stay imported from lemon (they carry no bot logo).
- Follow-up: header logo is now shown **without** the white avatar circle. The logo PNG's background
  is exactly `#005155` (== navbar), so rendering it bare blends into the bar (only the mint monogram
  shows). Done bot-locally via inline sizing on the `<img>` so lemon's shared `Layout.module.css`
  (`logoCircle`) is untouched.

#### Changes

- `app/frontend/src/chatbots/shared/theme/chatbotThemes.ts`: bensberg seed `primary` `#fec701` →
  `#005155`; added `overrides.navbar.text = #96f0eb` and `overrides.userBubble = { background:
  #96f0eb, text: #005155 }`.
- `app/frontend/src/chatbots/bensberg/pages/layout/Layout.tsx`: navbar logo import changed from
  `../../../lemon/assets/lemon-chatbot.png` to `../../assets/bensberg.png`; removed the
  `styles.logoCircle` wrapper so the logo renders bare (inline `height:36` on the `<img>`).
- `app/frontend/src/chatbots/bensberg/components/Answer/Answer.tsx`: **new** — bensberg-specific
  `Answer` = `createBotAnswer(bensbergLogo, …)`, reusing lemon's Speech components.
- `app/frontend/src/chatbots/bensberg/pages/chat/Chat.tsx`: import `Answer` from the new bensberg
  module; keep `AnswerError`/`AnswerLoading` from lemon.
- `app/frontend/src/chatbots/bensberg/assets/bensberg.png`: new asset; AVIF-in-`.png` converted to a
  real 300×300 PNG.

## 2026-06-21

### Strengthened locale-language enforcement on the weak single-line Q&A bots

#### Decisions

- Request: ensure every bot always continues the conversation in the UI locale language and does
  not drift. Audited all bots' `{{language_locale}}` handling (substituted to a language NAME —
  "German"/"English"/"Dutch" — from `overrides.get("language")`, the per-request frontend locale, in
  `render_chatbot_prompt`; a bot's `config.py` `language_locale` statically overrides it, as
  publishone does with `"English"`).
- Findings (3 tiers): publishone is hard-locked (no switch even on request; also statically pinned).
  The 7 tutor bots + compact knoll already carry a 3-clause block (always respond / no automatic
  mirroring, change only on explicit request / scope). The 7 Q&A bots (agindo, sartorius, rak,
  nerilio, free, fhg, vjoonk4) had only a single line "Always respond in {{language_locale}}." with
  no anti-mirroring/persistence clause — the real drift risk when a user writes in another language
  mid-conversation. hyrox_assessment intentionally scopes language to model feedback only (visible
  question text is backend-rendered), so it was left as-is.
- Policy (user-chosen): **honor explicit in-chat switch requests** (do not hard-lock). So the 7 weak
  bots were raised to the tutor-bot standard, and the tutor bots / knoll / publishone / hyrox were
  left untouched (already compliant / intentionally different).

#### Changes

- `app/backend/approaches/chatbots/{agindo,sartorius,nerilio,free,fhg,vjoonk4}/sampleprompt.py`:
  expanded the single "Always respond in {{language_locale}}." line into two bullets — "Always respond
  in {{language_locale}}, regardless of the language the user writes in." + "All responses stay in
  {{language_locale}} for the entire conversation — never automatically mirror or switch to the user's
  language. Change the language only on the user's explicit request." The existing German du/Sie
  formality bullet was preserved.
- `app/backend/approaches/chatbots/rak/sampleprompt.py`: same upgrade, folding the now-redundant
  "Maintain {{language_locale}} throughout all responses." line into the new pair (formal-Sie line kept).
- Verified all 7 files `py_compile` cleanly.

### Tutor question counter heading now localizes ("Frage N von Total" → "Question N of Total"/"Vraag N van Total")

#### Decisions

- Symptom: in an English (or Dutch) tutor session the per-question counter heading still rendered in
  German — e.g. "Frage 1 von 3:" above an otherwise-English question (see PublishOne screenshot).
- Root cause: the heading was hardcoded as the literal German string `Frage {{N}} von {{Total}}:`
  throughout each tutor `sampleprompt.py`. Only `{{N}}`/`{{Total}}` are model-filled; the word
  "Frage" was fixed German text. The string is repeated ~10× as a MANDATORY heading and reinforced
  as "the only non-term text that may be bold", so the model treated it as a fixed literal to emit
  verbatim — overriding the weaker global "respond in `{{language_locale}}`, translate all templates"
  rule. Unlike the topic-selection question (which ships explicit en/de/nl variants), the counter had
  no English/Dutch variant to copy, so German always won.
- Chosen fix (user-approved): make the heading explicitly trilingual and active-language in the three
  *governing* rules per bot — the bold-allowance rule, the 🟠 P1 DETERMINISTIC QUESTION COUNT master
  rule, and the "Always head the question…" / "follows directly after the heading" rules. Each now
  lists German "Frage {{N}} von {{Total}}:", English "Question {{N}} of {{Total}}:", Dutch
  "Vraag {{N}} van {{Total}}:" and states the heading must render in `{{language_locale}}`, including
  inside the German example/confirmation/transition templates.
- Deliberately NOT changed: the German example templates themselves (confirmation structure,
  Question Transitions) — they remain governed by the existing "translate to current language state"
  notes, and the strengthened master rule removes the conflicting "fixed German literal" signal that
  was causing the bug. Descriptive references to the heading by its German name (difficulty self-check,
  Question Counter Rules) were left as-is.

#### Changes

- `app/backend/approaches/chatbots/{lemon,bensberg,internal,fbn,moodle,demo,publishone,steuertipps}/sampleprompt.py`:
  localized the counter heading in the bold-allowance rule, the DETERMINISTIC QUESTION COUNT master
  bullet, and the "Always head the question…"/"follows after heading" bullets (3 edits each).
- `app/backend/approaches/chatbots/knoll/sampleprompt.py`: same fix adapted to its compact wording
  (bold-allowance sentence, the count master bullet, and the single "Always head…" line).
- Verified all 9 files still `py_compile` cleanly and no Dutch "von" typo slipped in.

### Tutor prompts no longer render whole question/feedback sentences in bold

#### Decisions

- Symptom: in tutor bots, entire sentences rendered bold — e.g. the topic-selection question
  ("Understood — let's start your knowledge test. Which topic should I ask you about?") and the
  level-rating question ("…How would you rate your knowledge on this topic?"). This violates the
  bots' own P3 Emphasis Rules ("do not bold entire phrases; bold only terminology").
- Root cause: the response templates in each tutor `sampleprompt.py` were written wrapped in
  `**"…"**`. Those `**` were meant as *authoring delimiters* (marking the exact string to emit),
  but the model can't distinguish prompt-authoring markdown from output markdown, so it reproduced
  the `**` verbatim and bolded the whole sentence — and generalized the pattern even to the
  topic-selection question, whose template was never `**`-wrapped.
- Chosen fix (user-approved): (a) strip the `**` wrapping from every standalone whole-sentence
  response template (confirmation structure, Cases B/C/D, Case 1 affirmation, Case 3
  encouragement, all answer-reveal templates, the Performance Summary intro, and the end-of-test
  re-offer question), and (b) add a HARD RULE to the "🟢 P3 — Formatting in Tutor Mode" section:
  bold marks individual technical/legal terms only, never a full sentence; the `**…**` around
  template strings are authoring delimiters; only the short counter heading
  `Frage {{N}} von {{Total}}:` stays bold.
- Deliberately KEPT bold: the `**English:**`/`**German:**`/`**Dutch:**` template labels, the
  `**"Frage {{N}} von {{Total}}:"**` running counter heading (short label, explicitly a "visible
  counter"), and the `**"Hidden Source" Policy …:**` heading.
- Non-tutor (Q&A-only) bots (agindo, fhg, rak, sartorius, vjoonk4, nerilio, free) were checked and
  have **no** whole-sentence `**"…"**` wrapping, so they were not touched.

#### Changes

- Stripped 15 whole-sentence `**"…"**` wraps and inserted the new HARD RULE in each of the 8
  standard tutor prompts: `app/backend/approaches/chatbots/{bensberg,demo,fbn,internal,lemon,moodle,publishone,steuertipps}/sampleprompt.py`.
- `knoll/sampleprompt.py` (compact): its level/count templates were already plain quotes (0 wraps
  stripped); added the compact form of the new rule to its formatting section.

### Tutor topic-selection now offers up to 10 distinct random topics

#### Decisions

- Symptom: in tutor mode, "test my knowledge" / "which topics?" sometimes showed only 1–2
  topic buttons. Root cause: the model builds the `[[CHOICES kind=topic]]` button list purely
  from the **retrieved text sources** it sees that turn, and default retrieval is `top=3`
  (`run_search_approach`, `overrides.get("top", 3)`); 3 chunks usually cluster into 1–2 modules,
  so the model has nothing else to list. The prompt wording was also inconsistent ("the available
  topic/module names" with no count vs. "5 random topics").
- Chosen fix (user decision, after weighing alternatives): **raise retrieval breadth + tighten the
  prompt** — bump `top` 5→10 for tutor bots and instruct the prompt to surface **up to 10 distinct**
  topics from the sources (all of them if fewer than 10 exist), re-randomized each time. Explicitly
  rejected: (a) injecting a precomputed topic catalog into the prompt; (b) a live facet on the
  module name — the friendly name lives in `title`, which is **not facetable** in the current index
  schema (only `category`/`sourcepage`/`sourcefile`/`user` are), so a real facet would need a schema
  change + full reindex of every bot's data.
- Known limitation (accepted): `top` only affects the **classic search** path. The agentic-retrieval
  path has no doc-count knob (the knowledge agent decides), so for bots that default to agentic —
  **lemon** and **bensberg** (`setUseAgenticRetrieval(config.showAgenticRetrievalOption)`) — the
  top=10 change is a no-op in their default mode; only the prompt change applies there. The other
  seven tutor bots (demo, fbn, knoll, moodle, publishone, steuertipps, internal) default agentic-off
  and get the full benefit. The catalog-injection approach remains the only fully-reliable option if
  lemon/bensberg agentic mode needs guaranteed ≥10 topics later.
- The lever for `top` is the frontend `retrieveCount` default (each tutor `Chat.tsx` always sends
  `top: retrieveCount`, overriding the backend default of 3), so the change is made there.

#### Changes

- `app/backend/approaches/chatbots/{lemon,bensberg,internal,demo,fbn,moodle,steuertipps,publishone,knoll}/sampleprompt.py`:
  topic-selection wording changed from "the available topic/module names from the learning unit" →
  "up to 10 distinct topic/module names, selected at random from the topics present in the provided
  materials (… all of them if fewer than 10 … never invent/repeat/split … re-randomize each time)";
  "choose from 5 random topics" → "up to 10 distinct random topics"; "5 random/relevant module names"
  → "up to 10 distinct random/relevant module names". Kept in lockstep across all tutor prompt variants.
- `app/frontend/src/chatbots/{lemon,bensberg,internal,demo,fbn,moodle,steuertipps,publishone,knoll}/pages/chat/Chat.tsx`:
  `retrieveCount` default `useState<number>(5)` → `useState<number>(10)` (sent as `top`).

### Tutor question difficulty now actually scales with the selected knowledge level

#### Decisions

- Root cause of "even at Level 5 the questions feel like Level 1": the level was collected
  once (via the `kind=level` buttons, lives only in chat history — there is no injected
  `{{Level}}` variable) and the only guidance was a buried 🟡 P2 paragraph with abstract
  adjectives ("very basic" vs "most challenging") and **no reinforcement at the moment a
  question is generated**. Unlike the question *count* (a 🟠 P1 rule that forces a visible
  `Frage {{N}} von {{Total}}:` header on every question), the *level* had no teeth, so the
  model defaulted to easy recall/definition questions regardless of the chosen level.
- Fix is purely prompt engineering (the only available lever — confirmed `render_chatbot_prompt`
  only code-substitutes `SUPPORT_EMAIL`, `POSSIBLE_CITATIONS_PROMPT`, `language_locale`; every
  other `{{…}}` incl. `{{Level}}` is model-filled). Strategy: (1) elevate the section from 🟡 P2
  to 🟠 P1; (2) replace abstract adjectives with a concrete Bloom-style cognitive rubric per level
  (L1 remember → L2 understand → L3 apply → L4 analyze → L5 evaluate/synthesize) with question
  stems; (3) add a "same material, different question" contrast example (L1/L3/L5 of one concept)
  as the strongest anchor; (4) add a **mandatory per-question self-check** ("could a user one full
  level lower answer this just as easily?") tied to the moment of sending each `Frage {{N}}`;
  (5) hard-ban bare definition/recall questions at Level 4–5.
- Kept the level **internal** (no visible "Level X" tag on questions) — only the cognitive demand
  changes, preserving the existing `Frage {{N}} von {{Total}}:` visible-counter contract.
- Applied identically across all 9 tutor variants to honour the "keep tutor prompts in lockstep"
  contract. knoll got a compact version matching its terse style. Left `lemon/sampleprompt-old.py`
  (inactive backup) untouched.

#### Changes

- `app/backend/approaches/chatbots/{lemon,bensberg,internal,demo,fbn,moodle,steuertipps,publishone}/sampleprompt.py`
  — replaced the identical 🟡 P2 "Question Difficulty Must Match Knowledge Level" section with a
  strengthened 🟠 P1 "Question Difficulty MUST Match Knowledge Level (enforced on EVERY question)"
  section (cognitive rubric + contrast example + self-check + hard prohibitions).
- `app/backend/approaches/chatbots/knoll/sampleprompt.py` — strengthened the compact one-line
  "difficulty must match level" note into a compact per-level rubric + self-check.
- `CLAUDE.md` — extended the tutor-mode contract bullet to document the level-difficulty rubric and
  to note `{{Level}}` etc. are model-filled placeholders; added it to the "keep in sync" list.

### Tooltip hover delay removed across all bots

#### Decisions

- Made icon tooltips appear/disappear instantly on hover. Fluent v9 `Tooltip` defaults to a ~250ms
  `showDelay` and `hideDelay`; set both to `0`. Applied at the shared layer wherever possible so the
  fix covers every bot in one place rather than per-bot duplication.

#### Changes

- `app/frontend/src/chatbots/shared/tooltip/TooltipTarget.tsx` — added `showDelay={0} hideDelay={0}`
  to the shared `Tooltip` wrapper. This covers all answer-toolbar icon buttons (copy, Azure speech)
  plus every bot's `HelpCallout` info icon and `MarkdownViewer` save icon, which route through it.
- `app/frontend/src/chatbots/shared/speech/SpeechInputButton.tsx` and
  `app/frontend/src/chatbots/shared/scroll/ScrollToBottomButton.tsx` — added the same props to their
  direct `Tooltip` usages (voice mic start/stop, scroll-to-bottom button).
- `app/frontend/src/chatbots/<bot>/components/QuestionInput/QuestionInput.tsx` for `agindo`, `demo`,
  `fbn`, `fhg`, `free`, `hyrox-assessment`, `knoll`, `lemon`, `moodle`, `publishone`, `rak`,
  `sartorius`, `steuertipps`, `vjoonk4` — added the same props to the send/stop button `Tooltip`s.
  `nerilio` skipped: its send/stop tooltips are commented out (renders plain buttons).

### Bensberg visible bot name aligned with Lemon

#### Decisions

- Renamed only Bensberg's user-facing browser/header title to `Lemon®AID`, matching Lemon's visible
  bot name. Kept the `/bensberg` route, `bensberg` retrieval category, backend package name, and
  storage/auth identifiers unchanged because those are routing and data contracts, not display labels.

#### Changes

- `app/frontend/src/chatbots/bensberg/locales/{de,en,nl}/translation.json` — changed `pageTitle` and
  `headerTitle` from `Bensberg` to `Lemon®AID`.

### Loading + error bubble padding unified across all bots

#### Decisions

- Follow-up to the nerilio loading-bubble fix: only nerilio's `AnswerLoading` uses the SHARED
  `.answerContainer` (so it picked up the 2026-06-20 `0.6em 1em` padding). The other 14 bots'
  `AnswerLoading.tsx` use their LOCAL `components/Answer/Answer.module.css` `.answerContainer`, which
  was still `padding: 1em` — so their loading pills were more padded than nerilio's, and more padded
  than their own (shared) answer bubble. The same local `.answerContainer` also backs every bot's
  `AnswerError.tsx` (all 15). Reduced the local `.answerContainer` padding `1em` → `0.6em 1em` in all
  15 per-bot Answer.module.css files so loading bubbles (14 others) match nerilio's loading padding,
  and error bubbles (all 15, including nerilio's) match the answer bubble too. Done as a verified
  one-occurrence-per-file literal replace.
- Did NOT add nerilio's loading `min-height`/centering to the other bots: they have no `min-height`
  and symmetric padding, so their dots already sit centered (nerilio's top-stuck-dots bug was caused
  by its `min-height: 3.5rem` + column flex, which the others never had). Their loading pills are now
  the same PADDING as nerilio's but slightly shorter (dots + padding, ~35px) vs nerilio's (sized to a
  one-line answer, ~47px). Left as-is unless full height parity is requested.

#### Changes

- `app/frontend/src/chatbots/{agindo,demo,fbn,fhg,free,hyrox-assessment,knoll,lemon,moodle,nerilio,
  publishone,rak,sartorius,steuertipps,vjoonk4}/components/Answer/Answer.module.css` —
  `.answerContainer` padding `1em` → `0.6em 1em` (affects each bot's loading and error bubble).

### nerilio loading bubble centering + bubble border-radius audit

#### Decisions

- The nerilio "assistant is typing" bubble (`AnswerLoading.tsx`, which reuses the shared
  `.answerContainer` plus the local `.loadingAnswerContainer`) had its three dots stuck to the TOP of
  the bubble and the bubble was oversized. Root cause: `.loadingAnswerContainer` set `display:flex` +
  `align-items:center` but the card is a Fluent `Stack` (flex-direction: column), so `align-items`
  only centered horizontally — there was no `justify-content`, so the dots sat at the column's
  main-axis start (top). `min-height: 3.5rem` (56px) also made it much taller than a one-line answer,
  which the 2026-06-20 answer-padding reduction (1em → 0.6em vertical) made more obvious. Fixed by
  centering on BOTH axes (direction-agnostic for the single child) and sizing the bubble to one line
  of answer text + the card's 0.6em padding so it matches a single-line answer.
- Audited user-vs-assistant bubble border-radius across all bots per request. Found them already
  consistent WITHIN each bot: nerilio uses 1.2em for both (its user bubble is 1.2em and it overrides
  `--chatbot-answer-card-radius` to 1.2em, base + mobile); the other 14 bots with a user bubble use
  1.5em for both (user bubble 1.5em + the shared `--chatbot-answer-card-radius` default of 1.5em).
  bensberg/internal have no own user bubble (shells). Initially made no change since each bot was
  already internally consistent, but on follow-up request normalized nerilio (the lone outlier at
  1.2em) UP to 1.5em so the radius is now uniform across ALL bots, not just within each. Noted but
  did not act on a subtle em-anchor difference (user bubble em is relative to its fixed 15px font;
  the assistant card em is relative to the responsive html root 12–16px), which diverges a few px
  only on small screens.

#### Changes

- `app/frontend/src/chatbots/nerilio/components/Answer/Answer.module.css` — `.loadingAnswerContainer`:
  added `justify-content: center`; replaced `min-height: 3.5rem` with
  `min-height: calc(var(--chatbot-answer-font-size, 15px) * 1.72 + 1.2em)` (one line of answer text +
  the 0.6em top/bottom card padding).
- `app/frontend/src/chatbots/nerilio/components/UserChatMessage/UserChatMessage.module.css` —
  `.message` border-radius `1.2em` → `1.5em`.
- `app/frontend/src/chatbots/nerilio/pages/chat/Chat.module.css` — `--chatbot-answer-card-radius` and
  `--chatbot-answer-card-radius-mobile` `1.2em` → `1.5em` (assistant card now matches the all-bot
  1.5em default).

## 2026-06-20

### Chat bubble + composer padding tightening (nerilio request)

#### Decisions

- A single-line assistant answer rendered taller than a single-line user message. Root cause: the
  shared answer card (`SharedAnswer.module.css` `.answerContainer`) used `padding: 1em` (1em vertical)
  while every bot's user bubble (`UserChatMessage.module.css` `.message`) uses `padding: 0.6em 1em`
  (0.6em vertical). The assistant card is the SHARED component used by all 17 bots (every bot's
  `components/Answer/Answer.tsx` calls `createBotAnswer`), and all 17 user bubbles are already
  `0.6em 1em`, so the mismatch was universal, not nerilio-specific. Chose to fix it in the shared CSS
  (assistant → `0.6em 1em`) for all bots rather than add a nerilio-only override variable — consistent
  with the recent "applied to all bots" UI refresh and a smaller change. Also updated the
  `@media (max-width: 767px)` override (which re-set `padding: 1em`) to `0.6em 1em` so phones stay
  consistent.
- nerilio input composer read as bulky. Established the ~65px height was driven by the 50×50px circular
  send button, NOT the container padding (`0.4rem` ≈ 6px, already slim — trimming padding alone saves
  only ~3px since the button is the tallest flex child). Chose a modest tighten: send button 50→44px
  (still meets the iOS 44px touch-target minimum) and container padding `0.4rem`→`0.3rem`, bringing the
  bubble to ~54px on desktop/~53px on phones. Scoped to nerilio only (per-bot `QuestionInput.module.css`)
  since the request was nerilio-specific; other bots have their own composer copies and were left
  unchanged.

#### Changes

- `app/frontend/src/chatbots/shared/answer/SharedAnswer.module.css` — `.answerContainer` padding
  `1em` → `0.6em 1em` (base rule + the `max-width: 767px` override).
- `app/frontend/src/chatbots/nerilio/components/QuestionInput/QuestionInput.module.css` —
  `.questionInputContainer` padding `0.4rem` → `0.3rem`; `.sendButton` width/height/min-width
  `50px` → `44px`.

### "Scroll to latest message" floating button (ChatGPT-style, all bots)

#### Decisions

- Added a ChatGPT-style down-arrow button that appears when the user has scrolled up away from the
  bottom of the conversation and jumps back to the latest message on click. Requested for every bot.
- Built it as ONE fully self-contained shared component
  (`app/frontend/src/chatbots/shared/scroll/ScrollToBottomButton.tsx` + its own CSS module) rather
  than touching each bot's `Chat.module.css`. The per-bot `Chat.module.css` files diverge (several
  distinct md5 groups), but the relevant layout invariants are uniform across all 17 bots:
  `.chatContainer` is the `overflow-y:auto` scroll container and `.chatInput` is the
  `position: sticky; bottom: 0` composer with `--composer-overlap: 1.5rem`. The button is rendered as
  an absolutely-positioned child of `.chatInput` (sticky → it is the containing block), so it stays
  centered above the composer and follows it without any per-bot CSS. Net per-bot edits are only in
  `Chat.tsx`: import, a `chatContainerRef`, `ref` on `.chatContainer`, and the button inside `.chatInput`.
- Visibility is driven by the component itself: a scroll listener + `ResizeObserver` + `MutationObserver`
  on the scroll container (rAF-coalesced) reveal it only when `scrollHeight - scrollTop - clientHeight`
  exceeds a 240px threshold, so it never shows on the short welcome screen and auto-hides at the bottom.
- Design is theme-neutral on purpose (white circle, subtle border, soft shadow, thin dark arrow) so the
  single component reads as consistent across every bot's light theme. Uses an inline SVG arrow (no new
  icon dependency; matches the existing inline-SVG pattern in `pages/verwaltung/components/icons.tsx`).
- For `hyrox-assessment` the composer (`.chatInput`) is conditionally mounted only during an active
  run, so the button is naturally scoped to that state — the pre-start and completed-summary screens
  (which use `footerAction`, not `.chatInput`) intentionally have no scroll button.
- Scope decision: the `aria-label`/tooltip is a single English default ("Scroll to latest message")
  rather than localized per bot — localizing would mean editing ~51 i18n files for an accessibility
  label; left as a follow-up if desired.

- Tooltip styling: the button's hint uses the same Fluent v9 `Tooltip` (`relationship="label"`) →
  shared `.fui-Tooltip__content` dark pill as the other icon-button tooltips, instead of a native
  `title=`. Because the trigger is a real DOM `<button>` (not a v8 `IconButton` that forwards `ref`
  to a class instance), the Tooltip anchors directly — no `TooltipTarget` `<span>` wrapper needed,
  which also keeps the button's absolute positioning intact.

#### Changes

- Added `app/frontend/src/chatbots/shared/scroll/ScrollToBottomButton.tsx` and
  `app/frontend/src/chatbots/shared/scroll/ScrollToBottomButton.module.css`.
- Wired the button into all 17 bots' `pages/chat/Chat.tsx` (agindo, bensberg, demo, fbn, fhg, free,
  hyrox-assessment, internal, knoll, lemon, moodle, nerilio, publishone, rak, sartorius, steuertipps,
  vjoonk4): import, `chatContainerRef`, `ref` on `.chatContainer`, and `<ScrollToBottomButton>` as the
  first child of `.chatInput`.
- Validation: `npm run build` (tsc + vite + chained widget build) passed. Visually verified on `lemon`
  via the running Vite dev server + Playwright — button shows when scrolled up (34px circle, 10px gap
  above the composer, centered) and hits opacity 0 at the bottom.

### Dark-pill tooltips for the answer-toolbar / panel icon buttons (all bots)

#### Decisions

- The earlier "global tooltip restyle" only reached Fluent UI **v9** `<Tooltip>` instances (the
  composer send/stop button and the mic `SpeechInputButton`). The Copy and Speak buttons in the
  answer toolbar — plus the HelpCallout info, MarkdownViewer save, and internal thought-process
  buttons — are Fluent **v8** `IconButton`s that expose their hint via the native `title=` attribute.
  Native `title` tooltips are browser-rendered and cannot be styled by CSS, so the global
  `.fui-Tooltip__content` dark pill never applied to them — they showed as the plain native boxes the
  user reported.
- Could not simply wrap a v8 `IconButton` in a v9 `<Tooltip>`: v9 Tooltip anchors by injecting a DOM
  `ref` into its single child, but v8 `styled()` forwards `ref` to the **BaseButton class instance**
  (verified in `@fluentui/utilities/lib/styled.js` and `BaseButton.js` — the DOM ref is only reachable
  via the v8-specific `elementRef`/`_buttonElement`). A class-instance ref breaks Floating UI
  positioning.
- Fix: a tiny shared `TooltipTarget` wrapper renders `<Tooltip relationship="label"><span …>{child}</span></Tooltip>`.
  The host `<span>` is a real DOM element, so the Tooltip anchors correctly; hovering the inner
  IconButton still fires the span's `onPointerEnter` (pointerenter fires for an element when entering
  via a descendant). The native `title` is dropped from each button; the existing `ariaLabel` keeps the
  accessible name, so a11y is unchanged. This reuses the SAME `.fui-Tooltip__content` dark pill — no new
  tooltip system, full visual consistency with the send/mic buttons.
- Scope (user-chosen): all icon-button tooltips — Copy, Speak (Azure + browser), info, thought-process,
  save. Intentionally **excluded** the inline citation/footer source-link `title=` hovers (plain
  `<a>`/`<button>` showing a reference/URL) — different semantics, long strings read poorly in a pill.
- The `MarkdownViewer` save button carried `float: right` via `styles.downloadButton`; moved that class
  onto the wrapper span (float is ignored on a flex item) so right-alignment is preserved. steuertipps
  uses a `viewerToolbar` (flex-end) instead and was handled separately. The hyrox speech button has an
  extra `styles` block and was edited individually. Per-bot `SpeechOutputBrowser`/`HelpCallout`/
  `MarkdownViewer` copies were verified byte-identical (md5) before propagating the canonical edit.

#### Changes

- Added `app/frontend/src/chatbots/shared/tooltip/TooltipTarget.tsx` (the shared span+v9-Tooltip wrapper).
- Wrapped the icon button and removed the native `title` in: shared `ChatbotAnswer.tsx` (Copy), shared
  `SpeechOutputAzureButton.tsx` (Azure speak), all 15 per-bot `components/Answer/SpeechOutputBrowser.tsx`
  (browser speak), all 15 `components/HelpCallout/HelpCallout.tsx` (info), all 15
  `components/MarkdownViewer/MarkdownViewer.tsx` (save), and `internal/components/Answer/Answer.tsx`
  (thought-process). Citation/footer link `title`s left as-is.
- Validation: `npm run build` (tsc + vite) passed, including the chained widget build. Visually verified
  via Vite dev + Playwright (lemon welcome card): hovering Copy / Speak (browser) / Speak (Azure) shows
  `.fui-Tooltip__content` with `background rgb(31,39,51)`, white text, 8px radius, positioned above the
  button — matching the established dark pill, toolbar layout intact.

### Beautiful global tooltip restyle (all bots)

#### Decisions

- Every bot's tooltips are Fluent UI v9 `<Tooltip relationship="label">`, whose surface is the
  stable class `.fui-Tooltip__content`. Fluent's default (near-white box, 4px radius, faint
  drop-shadow) reads as plain floating text on the light page — the reported "plain/ugly" look.
- Restyled all tooltips from a single global rule in `index.css` rather than editing the dozens of
  per-bot `QuestionInput`/speech/answer files, because the tooltip renders in a portal at `<body>`
  (outside `ChatbotThemeRoot`, so per-bot `--chatbot-*` vars don't reach it) and the surface class
  is shared by every usage.
- Chose a neutral **dark slate pill** (bg `#1f2733`, white text, 8px radius, layered drop-shadow,
  120ms opacity fade-in) over a light or per-bot-accent variant (user-selected). Neutral dark is the
  premium standard on light UIs (GitHub/Linear/Vercel), stays consistent across all 17 bots'
  differing accent colors, and sidesteps plumbing an accent into the portal.
- Selector is the doubled class `.fui-Tooltip__content.fui-Tooltip__content` (specificity 0,2,0) so
  it beats Fluent's runtime-injected Griffel atomic classes (0,1,0) regardless of insertion order —
  no `!important`. Verified with a standalone Playwright screenshot that placed the atomic rules
  *after* the override (worst case) and confirmed the override still won.
- Used `filter: drop-shadow` (not `box-shadow`) so the elevation wraps the arrow shape; the arrow
  recolors automatically via its `background-color: inherit`. Animated opacity only (never transform —
  the positioning manager owns the element's inline transform) and disabled it under
  `prefers-reduced-motion`.

#### Changes

- `app/frontend/src/index.css`: added the global `.fui-Tooltip__content` dark-pill override, a
  `chatbotTooltipIn` opacity keyframe, and a `prefers-reduced-motion` guard.

### Chat composers: fill rounded-corner gap with chat content

#### Decisions

- The visible gap beside the sticky composer was caused by the chat footer's opaque page-colour
  background showing through the composer's rounded top corners after the soft fade was disabled.
- Kept the fade disabled and fixed the root layout instead: the composer footer now overlaps the
  message stream by the composer-radius band, and only that top band is transparent so scrolled chat
  content shows behind the rounded corners while the lower footer still masks with the page colour.
- Added matching bottom padding to the message stream so the overlap does not consume the final
  assistant bubble's resting margin when the chat is scrolled fully to the latest message.
- Applied the same treatment to every chatbot with its own `pages/chat/Chat.module.css`. Bensberg and
  Internal do not have separate chat layout CSS here and inherit existing shared bot surfaces.

#### Changes

- All 15 `app/frontend/src/chatbots/*/pages/chat/Chat.module.css` files: added a
  `--composer-overlap` band, negative top margin, and transparent-to-page-colour footer background
  gradient for sticky composers; added bottom stream padding for the resting gap; removed the
  soft-fade pseudo-element block. HYROX's sticky `.footerAction` restart footer uses the same overlap
  treatment.
- Validation: `npm run build` in `app/frontend` passed; `git diff --check` passed; `graphify update .`
  was attempted and timed out after 3 minutes, and the leftover graphify process was stopped.

### "Andere Option" button: solid border to match the other choice buttons

#### Decisions

- The "Andere Option" button rendered with a dashed border (deliberately, to read as "type your
  own"), which looked inconsistent next to the solid-bordered choice buttons. Per the user's request,
  switched it to the same solid border so all buttons in the option group match visually.
- Investigated (no change) whether the tutor end-of-flow's three stacked bubbles
  (final-answer feedback / Performance Summary / re-offer) appear simultaneously or one by one: they
  are a single streamed assistant message split on `[[SPLIT]]` markers, and `splitBubbleSegments`
  re-runs on every streamed chunk while a partial `[[SPLIT` does not split until its closing `]]`
  arrives — so each bubble already pops in sequentially as the model generates it (only a non-streamed
  delivery would render all three at once).

#### Changes

- `app/frontend/src/chatbots/shared/answer/AnswerOptions.module.css`: removed `border-style: dashed`
  from `.optionOther` so it inherits the base `.option` solid border; updated the comment.

### User bubble preserved line breaks and spacing (all bots)

#### Decisions

- The user message bubble rendered every input as one run-on line: newlines collapsed to spaces and
  runs of spaces collapsed to one. Root cause was purely presentational — `UserChatMessage` renders
  the raw string into a `<div>` (`{message}`), and the `.message` rule had no `white-space`, so the
  browser default `white-space: normal` collapsed all whitespace. The input pipeline was never at
  fault: `QuestionInput` sends `question` verbatim (only `.trim()` gates the disabled state) and the
  multiline textarea keeps `\n`, so the newlines were always present in the DOM.
- Fix: set `white-space: pre-wrap` (preserve newlines and spacing, still wrap) plus
  `overflow-wrap: break-word` (so a long unbroken token still wraps inside the bubble) on the final
  `.message` override block. Chose `pre-wrap` over `pre-line` to honor multiple spaces too, matching
  the user's report about spaces being dropped.

#### Changes

- All 15 `chatbots/*/components/UserChatMessage/UserChatMessage.module.css` (agindo, demo, fbn, fhg,
  free, hyrox-assessment, knoll, lemon, moodle, nerilio, publishone, rak, sartorius, steuertipps,
  vjoonk4): added `white-space: pre-wrap` and `overflow-wrap: break-word` to the `.message` override.
  Covers bensberg and internal as well, which both reuse `lemon`'s `UserChatMessage`.

### Fix "Other option" highlight flickering off during loading/streaming

#### Decisions

- When a user picked "Andere Option" and sent a free-typed answer, the option's black highlight
  disappeared while the response loaded and only returned once content arrived. Root cause: the
  highlight for the free-text path relied on `AnswerOptions`' local `optimisticOtherSelected` state,
  but the `answers`↔`streamedAnswers` render switch (streaming) remounts the component and drops that
  state, while no durable `selectedValue` exists for the free-text path until the answer is added.
- Fix mirrors the normal option-click path: record the free-typed value in Chat-level
  `pendingOptionSelection` at send time so `getOptionSelectedValue` returns it through the whole
  loading/streaming window, keeping the "Other" highlight stable (independent of remount).

#### Changes

- All 9 tutor `pages/chat/Chat.tsx`: in `makeApiRequest`, when `freeTextOptionAnswerIndex` is set
  (a free-typed "Other" answer), set `pendingOptionSelection` to that answer index + the typed value
  before clearing `freeTextOptionAnswerIndex`.
- `CLAUDE.md`: documented the `pendingOptionSelection` persistence for the "Other" highlight.

### Tutor summary trigger: fire on the final ANSWER, not on asking the last question

#### Decisions

- The previous "auto-continue" wording made the model summarize too eagerly: it asked
  "Frage {{Total}} von {{Total}}" and appended the Performance Summary in the SAME turn, before the
  user answered the final question (the summary even claimed all answers were correct). Clarified
  across all 9 tutor prompts that the trigger is the user's **answer** to the final question, not the
  act of asking it: asking `Frage {{Total}}` still stops and waits like any other question, and the
  summary (with its `[[SPLIT]]` bubbles) only appears in the next turn that evaluates that final
  answer. Added explicit "never summarize in a turn that asks a question / never invent the final
  answer" guards.

#### Changes

- All 9 tutor `sampleprompt.py`: rewrote the terminal-stop / counter rule and the Performance Summary
  WHEN note to gate the summary on the final answer being given.
- `CLAUDE.md`: clarified the summary-emitting turn is the one evaluating the final answer, not the one
  asking the last question.

### Tutor summary follow-ups: auto-continue, stacked bubbles, Q&A label fix

#### Decisions

- The end-of-test ending must arrive in the SAME turn that evaluates the final answer — the model was
  stopping after the final-question feedback and only producing the summary after the user typed
  something. Strengthened the 🟠 P1 terminal-stop rule (and the summary intro) so the final response
  is one turn with THREE `[[SPLIT]]`-separated bubbles: final feedback, Performance Summary, closing
  Tutor/Q&A prompt. (Earlier today this was two bubbles; the final-answer feedback is now its own
  bubble too, matching the requested feedback→summary→closing sequence.)
- Split bubbles were tiling side-by-side because `.chatMessageGpt` is a flex *row*. Fixed in shared
  CSS by wrapping the bubbles in a `.answerBubbleGroup` column; the single-bubble case uses
  `display:contents` so every non-split message keeps its exact previous layout.
- The mode button "Ask a question"/"Fragen stellen" was ambiguous and the model read it as a tutor
  request, so clicking it started Tutor mode. Relabeled the Q&A mode option to "I have a question" /
  "Ich habe eine Frage" / "Ik heb een vraag" (the sent value equals the label), which is unambiguous
  Q&A intent and is also the user-requested wording.

#### Changes

- `app/frontend/src/chatbots/shared/answer/SharedAnswer.module.css`: add `.answerBubbleGroup`
  (column) and `.answerBubbleGroupSingle` (`display:contents`).
- `app/frontend/src/chatbots/shared/answer/ChatbotAnswer.tsx`: wrap the rendered bubbles in the
  group/single wrapper (no other structural change; supports 2+ `[[SPLIT]]` segments).
- All 9 tutor bots' `locales/{en,de,nl}/translation.json`: `options.mode.askQuestions` →
  "I have a question" / "Ich habe eine Frage" / "Ik heb een vraag".
- All 9 tutor `sampleprompt.py`: terminal-stop / counter rule now mandates same-turn, three-bubble
  ending; Performance Summary intro adds a SAME-TURN note; the `[[SPLIT]]` marker-section doc updated
  to describe two `[[SPLIT]]`s (feedback → summary → closing).
- `CLAUDE.md`: tutor marker contract updated for the three-bubble same-turn close, the
  `.answerBubbleGroup` layout, and the Q&A label change.

### Tutor option buttons: no "Other" on level/count + two-bubble summary close

#### Decisions

- The knowledge-level (1–5) and question-count (3/5/10) option groups are fixed sets, so they must
  never render an "Andere Option"/"Other option" button. Rather than relying on the model to omit
  `allowOther`, the frontend now force-disables `allowOther` for `kind=level`/`kind=count` in
  `parseChoiceMarker` — authoritative regardless of what the LLM emits.
- The Performance Summary close should read as two separate assistant bubbles (summary, then the
  "another topic or Q&A?" prompt with Tutor/Q&A buttons), mirroring the welcome message. Chosen a
  display-only hidden `[[SPLIT]]` bubble-separator marker handled entirely inside shared
  `ChatbotAnswer` (no per-bot `Chat.tsx` or history/state changes): the split is purely visual, the
  stored message stays single so history replay is unchanged, and the trailing `[[CHOICES …]]` marker
  keeps driving the existing option-click/suppression logic untouched.
- The end-of-test re-offer is now `kind=mode` (was `generic`), so its buttons match the welcome's
  Tutor/Q&A choice. The abort-confirm yes/no stays `kind=generic`.

#### Changes

- `app/frontend/src/chatbots/shared/answer/optionMarkers.ts`: force `allowOther=false` for
  `level`/`count`; add `[[SPLIT]]` regexes, `splitBubbleSegments()`, and SPLIT stripping in
  `stripChoiceMarker()`; update module header doc.
- `app/frontend/src/chatbots/shared/answer/index.ts`: export `splitBubbleSegments`.
- `app/frontend/src/chatbots/shared/answer/ChatbotAnswer.tsx`: render the first bubble segment in the
  main card and any extra `[[SPLIT]]` segments as additional assistant cards below, placing the
  option group on the LAST bubble (non-split path byte-identical to before).
- All 9 tutor `sampleprompt.py` (bensberg, demo, fbn, internal, lemon, moodle, publishone,
  steuertipps, knoll): Performance Summary now emits `[[SPLIT]]` + closing question +
  `[[CHOICES kind=mode]]`; INTERACTIVE OPTION MARKERS section documents `[[SPLIT]]`, marks
  `level`/`count` as never taking `allowOther`, moves the end-of-test re-offer to `kind=mode`.
- `CLAUDE.md`: updated the tutor interactive-marker contract for the `[[SPLIT]]` marker, the forced
  `allowOther` off for level/count, and the two-bubble summary close.

### Follow-up: keep composer enabled during answer loading

#### Decisions

- Answer loading by itself should not disable or grey the composer. Closed-choice prompts still block
  typing while idle, but once an option click has started a request the composer returns to its normal
  enabled surface while the stop control is shown.

#### Changes

- All 9 tutor `pages/chat/Chat.tsx`: changed the composer disabled condition from
  `isLoading || optionPromptBlocksInput` to `optionPromptBlocksInput && !isLoading` (with the internal
  source-bot guard preserved).
- `tests/e2e.py`: updated the Bensberg regression to assert the composer is enabled and white during a
  pending answer request.
- Validation: `npm run build` in `app/frontend` passed; `.venv\Scripts\python.exe -m pytest
  tests/e2e.py::test_bensberg_option_prompt_disables_input_and_dedupes_topics` passed after rerunning
  against the rebuilt bundle; `git diff --check` passed. `graphify update .` was attempted and timed
  out again after 3 minutes; no leftover graphify/test-server process remained.

### Follow-up: keep option selection visible during loading

#### Decisions

- The selected option is now stored at the chat-page level while a request is pending. Local optimistic
  state inside the option component is still useful for the first click frame, but the page-level pending
  value is what keeps the selected styling stable when the parent locks/re-renders during loading.
- A disabled composer should use the disabled surface whenever the input is disabled, including during
  answer generation/streaming, so the text area and action-button side read as one grey bubble.

#### Changes

- All 9 tutor `pages/chat/Chat.tsx`: added `pendingOptionSelection`, feed it into
  `optionSelectedValue`, route option clicks through `handleOptionSelected`, and clear pending selection
  on free-text override, clear/reset, and history restore.
- Tutor `QuestionInput.tsx` copies used by Bensberg/Lemon, Demo, FBN, Knoll, Moodle, PublishOne, and
  Steuertipps now apply the disabled surface class for any disabled state, not only non-loading prompts.
- `tests/e2e.py`: expanded the Bensberg regression so the second option click leaves the mocked request
  pending and asserts both the selected option and the full grey composer while the loading bubble is
  visible.
- Validation: `npm run build` in `app/frontend` passed; `git diff --check` passed;
  `.venv\Scripts\python.exe -m pytest
  tests/e2e.py::test_bensberg_option_prompt_disables_input_and_dedupes_topics` passed. `graphify
  update .` was attempted and timed out again after 3 minutes; no leftover graphify/test-server
  processes remained after cleanup.

### Follow-up: topic prompt text, disabled composer surface, and immediate option feedback

#### Decisions

- Topic-selection prompts should keep the actual question text visible above the buttons. The frontend
  duplicate-topic cleanup now strips only visible topic-list prose/bullets, not question lines ending in
  a question mark.
- Option buttons now show selected feedback optimistically on click, before the backend stream returns,
  so users get immediate visual confirmation.
- When an option prompt disables free typing, the whole composer surface is greyed as one disabled
  bubble instead of leaving the send-button side on a white background.

#### Changes

- `optionMarkers.ts`: narrowed duplicate topic-list intro stripping and preserved visible
  topic-selection questions.
- `AnswerOptions.tsx`: added marker-keyed optimistic selected/other state for immediate
  `aria-pressed` and selected styling.
- Tutor `sampleprompt.py` files: made the topic-selection question template explicit in English,
  German, and Dutch, while keeping dynamic topic labels only in the `kind=topic` marker body.
- Tutor `QuestionInput` CSS/TSX copies used by Bensberg/Lemon, Demo, FBN, Knoll, Moodle,
  PublishOne, and Steuertipps: added the disabled composer surface styling.
- `tests/e2e.py`: extended the Bensberg option regression to assert the restored topic question,
  no duplicate visible topic list, disabled composer, and immediate selected button state.
- Validation: `npm run build` in `app/frontend` passed; `python -m py_compile` passed on the 9 tutor
  prompts; `.venv\Scripts\python.exe -m pytest
  tests/e2e.py::test_bensberg_option_prompt_disables_input_and_dedupes_topics` passed. `graphify
  update .` was attempted again and timed out after 3 minutes; leftover graphify/test-server
  processes were stopped.

### Follow-up: interactive option prompt UX fixes

#### Decisions

- The chat composer is now treated as unavailable while the latest assistant message is waiting for an
  interactive option choice. It unlocks only when the user explicitly clicks "Other option", because
  free typing is the exception path for these closed-choice prompts.
- Topic-choice prompts now use the option buttons as the single visible topic list. The model is still
  allowed to put dynamic topic labels in the hidden `kind=topic` marker body, but prompt rules now tell
  it not to duplicate those same labels as visible bullets/plain text. The frontend also strips duplicate
  visible topic bullet lists defensively when a topic marker is present.

#### Changes

- All 9 tutor `pages/chat/Chat.tsx`: derive whether the latest assistant message has an active
  `[[CHOICES ...]]` marker, disable the composer while it is active, and reset the free-text override on
  send/clear/restore. "Other option" now flips that override before focusing the textarea.
- Tutor `QuestionInput.tsx` copies used by lemon/bensberg/internal, demo, fbn, knoll, moodle,
  publishone, and steuertipps now pass the existing `disabled` prop through to the actual Fluent
  `TextField`, not only to the send button.
- English tutor option i18n changed `"Check my knowledge"` to `"Test my knowledge"` across all 9 tutor
  bots.
- All 9 tutor `sampleprompt.py`: topic selection after choosing Tutor Mode must include available
  topics in a `kind=topic` marker in the same message, and topic names must not be duplicated in visible
  text.
- Added a focused Playwright regression in `tests/e2e.py` for Bensberg option locking and topic-list
  deduplication.
- Validation: `npm run build` in `app/frontend` passed; `python -m py_compile` passed on all 9 tutor
  prompts; `.venv\Scripts\python.exe -m pytest
  tests/e2e.py::test_bensberg_option_prompt_disables_input_and_dedupes_topics` passed. `graphify update
  .` was attempted twice (2-minute and 5-minute timeouts) but did not complete on this corpus; leftover
  graphify/python processes from those attempts were stopped.

### Interactive option buttons for tutor-mode bots

#### Decisions

- Closed-choice prompts in the tutor flow (Tutor-vs-Q&A mode, topic, knowledge level 1–5, question
  count 3/5/10, and in-flow yes/no choices) now render as **buttons / radio-cards** instead of free
  text. They are driven by a hidden marker the model appends at the end of a message —
  `[[CHOICES kind=mode|topic|level|count|generic allowOther=0|1]]Label | Label[[/CHOICES]]` — the same
  proven pattern as the HYROX assessment markers (`assessmentMarkers.ts`). The marker is stripped from
  the displayed text but kept in the stored content so it replays into history. Chosen over a
  frontend-only heuristic because the **topic list is dynamic** (depends on the learning unit) and must
  come from the model.
- **Core UX fix (the point of the change):** clicking an option still sends the choice to the backend
  so history and the model see it, but the user **bubble is suppressed** for predefined selections;
  instead the selection is shown **locked inside the assistant's option group** (derived from
  `answers[i+1][0]`, so it survives history restore). This replaces the rejected HYROX behavior where
  the clicked label re-appeared as a fake user message. Free-typed "Andere Option" answers don't match
  a predefined value, so they still render as a normal user bubble.
- `mode`/`level`/`count` labels (and the level descriptions) are **frontend-owned via i18n**
  (`options.*` keys in de/en/nl) so they are always localized and consistent; `topic`/`generic` labels
  come from the marker body (dynamic). The welcome mode marker is appended in code
  (`t("initialAssistantMsg") + "\n\n[[CHOICES kind=mode]][[/CHOICES]]"`) rather than editing 24 welcome
  strings; the synthetic welcome pair is stripped before any backend call, so the marker never reaches
  the model.
- Selected state is **neutral/monochrome** (dark border + check icon for buttons / filled radio for
  cards + faint tint) by design — a saturated brand color would be low-contrast on the yellow/orange
  bots. Themeable via `--chatbot-option-*` CSS vars. "Andere Option" focuses the always-visible chat
  input through a ref on the input wrapper, so the 7 forked `QuestionInput` copies were left untouched.
- Scope (per user direction): applied to **all tutor bots** — bensberg, lemon, demo, fbn, knoll,
  moodle, publishone, steuertipps, internal — plus a fix so the HYROX assessment Start/Restart buttons
  no longer render the literal "Start" as a user bubble.
- Verification: the repo has **no JS unit-test runner** (no Vitest/Jest), so `optionMarkers` was
  validated by `tsc`, a full `npm run build` (incl. widget), an esbuild sanity run (16/16 assertions),
  and a Playwright route-mock screenshot pass of the `AnswerOptions` variants. Vitest was deliberately
  not introduced (out of repo convention).

#### Changes

- New shared module `app/frontend/src/chatbots/shared/answer/optionMarkers.ts` (parse / strip /
  resolve / `matchesChoiceValue` / `isOptionSelectionTurn` / `buildOptionTexts`) and
  `AnswerOptions.tsx` + `AnswerOptions.module.css`; both exported from `shared/answer/index.ts`.
- `shared/answer/ChatbotAnswer.tsx`: always strips the `[[CHOICES …]]` marker for display, parses it,
  renders `<AnswerOptions>`; added props `optionTexts`, `optionSelectedValue`, `optionsLocked`,
  `onOptionSelected`, `onOptionOther`. `createBotAnswer.tsx` supplies `optionTexts` from the bot's
  i18n and forwards the rest; `fbn` and `internal` custom Answer wrappers forward the same.
- All 9 tutor `pages/chat/Chat.tsx`: suppress option-driven user bubbles, pass selected value +
  locked + handlers to `Answer`, added `chatInputRef`/`focusInput` for "Andere Option", and appended
  the welcome mode marker.
- Added an `options` i18n block to all 9 tutor bots × `de`/`en`/`nl` (27 translation files).
- `hyrox-assessment/pages/chat/Chat.tsx`: suppress the "Start" user bubble (maps + loading/error).
- All 9 tutor `sampleprompt.py` (lemon/bensberg/internal, demo/fbn/moodle/steuertipps/publishone,
  knoll): added a "🟠 P1 — INTERACTIVE OPTION MARKERS" section defining the grammar and exactly when
  to emit each kind.

---

## 2026-06-19

### Cleaner chat UI refresh, applied to all bots

#### Decisions

- Refreshed the chat surface for a flatter, cleaner look, then rolled it out to **every** bot:
  response cards drop their drop-shadow for a subtle `1px` hairline border; user bubbles go fully
  flat (no shadow, outline, or border); the gap above the composer is removed and the conversation
  column is centered at `max-width: 48rem` (composer + message stream kept in lockstep so messages
  stay aligned and nothing peeks beside the sticky input). The shared disclaimer banner was narrowed
  to the same `48rem` so it aligns with the column instead of spanning wider.
- The main response card is centralized in `shared/answer/SharedAnswer.module.css`, so its base rule
  was edited directly (one change covers all bots). The per-bot user bubble, loading/error answer
  card, and chat layout are **forked copies** (15 bots each, with drift), so rather than edit drifted
  rules in place, a small, drift-proof override block was **appended** to each copy (later source
  order + equal specificity wins; no dependence on existing values). Bensberg has no own copies — it
  reuses lemon's files + SharedAnswer, so it is covered transitively (same for internal).
- The answer card border color is themeable via `--chatbot-answer-card-border-color` (default
  `#e6e6e6`). hyrox-assessment (black answer card) sets it to `rgba(255,255,255,0.16)` so the border
  reads as a refined edge instead of a stark light ring, and its sticky `.footerAction` (Restart
  button) is narrowed to `48rem` in lockstep with the composer.
- An earlier first pass scoped these to Bensberg only via `:global([data-chatbot-theme="bensberg"])`
  on the shared rules; that scoping was reverted once the request expanded to all bots.
- Verified visually (vite dev + Playwright route-mocks, no Azure) across theme/layout variants:
  bensberg, lemon, publishone (dark user bubble), hyrox-assessment (dark answer card), nerilio
  (avatar-outside, purple). Production `npm run build` (tsc + vite + widget) passes.

#### Changes

- `app/frontend/src/chatbots/shared/answer/SharedAnswer.module.css`: base `.answerContainer` now uses
  `box-shadow: none` + `border: 1px solid var(--chatbot-answer-card-border-color, #e6e6e6)`.
- `app/frontend/src/chatbots/shared/disclaimer/ChatbotDisclaimerBanner.module.css`: `.wrapper`
  max-width and `.banner` width narrowed `64.25rem` → `48rem`.
- Appended a `/* cleaner-ui-refresh */` override block to all 15 per-bot copies of
  `components/UserChatMessage/UserChatMessage.module.css` (flat `.message`),
  `components/Answer/Answer.module.css` (flat `.answerContainer` for loading/error), and
  `pages/chat/Chat.module.css` (`.chatMessageStream`/`.chatInput` at `48rem`, `padding-top: 0`).
- `app/frontend/src/chatbots/hyrox-assessment/pages/chat/Chat.module.css`: added
  `--chatbot-answer-card-border-color` override and `.footerAction { max-width: 48rem }`.

#### Follow-up: composer matched to the flat look

- The sticky composer was the last element still wearing a heavy floating drop-shadow, so it stood
  out against the now-flat cards. Appended the same `/* cleaner-ui-refresh */` override to all 15
  per-bot `components/QuestionInput/QuestionInput.module.css` copies: `.questionInputContainer` now
  `box-shadow: none` + `border: 1px solid #e6e6e6` (kept pure white, and the plain `#e6e6e6` — not the
  themeable answer-card var — since the composer is white on every bot, including dark-card hyrox).
  Each bot keeps its own border-radius (e.g. nerilio's 2.5rem pill). Verified via computed styles +
  screenshots; `npm run build` passes.

#### Follow-up: hyrox inverted user bubble + smooth scroll fade

- **hyrox-assessment is inverted** (black assistant card, white user bubble), so the hairline
  `1px solid #e6e6e6` border that the light assistant cards get elsewhere belongs on hyrox's *user*
  bubble instead. Changed hyrox's `components/UserChatMessage/UserChatMessage.module.css` cleaner-ui
  override from `border: none` to `border: 1px solid #e6e6e6` (still no shadow/outline) so the white
  user bubble is defined against the light page. Verified via computed style + the Start-flow user
  bubble screenshot.
- **Smooth scroll blend:** with the gap removed, content scrolling up behind the sticky composer hit
  the composer's rounded white edge abruptly (most visible on hyrox's dark card). Rather than restore
  a gap, added a soft fade mask — a `.chatInput::before` (and hyrox `.footerAction::before`) absolute
  strip, `2rem` tall, `linear-gradient(to top, #f2f2f2, transparent)`, anchored to the sticky
  (positioned) composer. Content dissolves into the page colour before reaching the rounded edge; it's
  invisible at rest (same colour), so the connected look is preserved. Appended to all 15 per-bot
  `pages/chat/Chat.module.css`. Verified scrolled on lemon, publishone (light cards) and
  hyrox-assessment (dark card); `npm run build` passes.

#### Follow-up: tighter user-bubble padding + unified polished navbar dropdown

- **User-bubble padding:** `1em` all-round made short one-line messages read as a chunky blob.
  Changed the base `.message` padding to `0.6em 1em` (less vertical, same horizontal) across all 15
  per-bot `components/UserChatMessage/UserChatMessage.module.css` so one-liners read as a balanced
  pill. Picked `0.6em` after comparing 0.55/0.6/0.7 on screen (0.55 a hair tight, 0.7 a hair tall).
- **Navbar dropdown:** the demo bot's dropdown was the most polished, so unified every other bot to
  it — appended a `/* polished-dropdown */` override to each `pages/layout/Layout.module.css`:
  `.menuButton` pill hover (`border-radius: 999px`), `.dropdownMenu` rounded floating panel
  (`margin-top: 0.5rem; border-radius: 18px; padding: 0.45rem; min-width: 220px`), and `.dropdownItem`
  rounded, roomier, bolder (`gap: 0.65rem; padding: 0.75rem 0.9rem; border-radius: 14px;
  font-weight: 600`). demo is the reference (skipped); bensberg + internal import lemon's layout so
  editing lemon covers them. Verified the open menu on lemon, nerilio (chevron trigger), and
  publishone (dark navbar); `npm run build` passes.

### Tutor mode: re-offer-on-"what topics?" fix didn't hold — anchor to observable history

#### Decisions

- The earlier same-day fix still failed in testing: after choosing Tutor mode and being asked for a
  topic, asking "Welche Themen gibt es?" again produced the topic list **plus** the "Tutor or Q&A?"
  re-offer. Root cause of the miss: the guard keyed off an abstract "INITIAL state" vs. "already entered
  Tutor Mode" that the model has to infer — but Tutor Mode has **no explicit entry message** (unlike
  Q&A's mandatory "Du befindest dich jetzt im Q&A-Modus"), so during topic-asking the model still
  classifies itself as "initial" and re-fires the Material Overview handler (whose example list contains
  the verbatim "Welche Themen sind verfügbar?").
- New approach: anchor the Material-Overview-vs-Topic-Selection decision to an **observable chat-history
  event** instead of an inferred state — the instant the user expresses any wish to be tested, Tutor Mode
  is already chosen (even before topic/level/count, even while the bot is still asking for a topic). The
  re-offer template may therefore only run on the user's first turn. Reinforced at the exact failure
  point (the topic-asking step) so the rule is restated where the model actually decides.
- Prompt-only, scoped to the same nine tutor prompts. No model/config/backend changes. The first-turn
  Material Overview template (which legitimately ends by offering Tutor/Q&A) was left intact; only its
  firing condition was tightened.

#### Changes

- `app/backend/approaches/chatbots/{lemon,bensberg,internal,demo,fbn,moodle,steuertipps,publishone}/sampleprompt.py`:
  rewrote the Material Overview context guard and the Topic Recognition "available topics" bullet to use
  the observable-history anchor, and added a step-5 note at the Topic Selection "no topic yet" branch.
- `app/backend/approaches/chatbots/knoll/sampleprompt.py`: equivalent three edits in its compact style.
- Validation: `py_compile` clean on all nine; new guard/anchor strings present once per file. One-off
  script used then deleted.

### Add framer-motion to frontend for Framer Motion skills

#### Decisions

- Installed `framer-motion` in `app/frontend` at the user's request, to back the globally-installed
  Framer Motion Claude Code skills. Skills/MCP generate code but never manage repo dependencies, so the
  runtime package must physically exist in the project for animation imports to resolve.
- Chose the `framer-motion` package over the rebranded `motion` package so imports match what the
  installed skills emit (`import { motion } from "framer-motion"`). Same library, legacy package name.
- Noted but accepted: the frontend already ships `@react-spring/web`; framer-motion is now a second
  animation library in the bundle.

#### Changes

- `app/frontend/package.json`: added `"framer-motion": "^12.40.0"` to dependencies.
- `app/frontend/package-lock.json`: updated (framer-motion + 2 transitive packages, v12.40.0).

### Tutor mode: don't re-offer mode selection on "what topics are there?"

#### Decisions

- Bug report: after choosing Tutor mode and being asked for a topic, a user who asks "what topics are
  there?" got the topics list followed by "Would you like Tutor mode or Q&A mode?" — bouncing them back
  to mode selection. Root cause: two overlapping handlers for that request. The initial-state **Material
  Overview Questions** handler (which ends by re-offering the mode choice and says "keep the user in the
  initial state") was firing even though the user was already inside Tutor Mode at the topic-selection
  step, instead of the **Topic Recognition & Selection** "available topics" branch that lists topics and
  re-asks which one to test.
- Fix is prompt-only and scoped to the same nine tutor prompts: guard the Material Overview handler to
  the INITIAL state and explicitly redirect an "available topics?" request to topic selection once a mode
  is already active (no Tutor/Q&A re-offer). No model/config changes.

#### Changes

- `app/backend/approaches/chatbots/{lemon,bensberg,internal,demo,fbn,moodle,steuertipps,publishone}/sampleprompt.py`:
  added an INITIAL-state context guard to the Material Overview handler and a reinforcing bullet in the
  Topic Recognition "no match / available topics" branch (one-off script).
- `app/backend/approaches/chatbots/knoll/sampleprompt.py`: equivalent guard + topic-recognition bullet in
  its compact style (by hand).
- Validation: `py_compile` clean on all nine prompts; guard marker present once per file.

### Deterministic tutor flow + reasoning_effort=high for tutor bots

#### Decisions

- Root cause of the "bot never asks how many questions" bug: the count step lived at 🟡 P2 among
  ~30 other rules with no hard gate, the salient "Beginnen wir mit Frage 1" template sat at the top
  of the level/count section (priming an early start), and level (1–5) vs. count (3/5/10) overlap on
  the values 3 and 5, so a level answer of "3" was read as "intake complete". Counter drift came from
  there being no visible anchor for the total — the model had to recount prior questions from history
  across hint/revision/Case-2 detours.
- Fix is prompt-hardening only (no backend state machine), per user choice: true 100% determinism
  isn't guaranteeable from an LLM prompt, but a P1 start gate + a mandatory visible `Frage {{N}} von
  {{Total}}:` counter + an explicit terminal stop + `reasoning_effort="high"` make it effectively
  deterministic in normal use. User explicitly approved the visible "Frage 3 von 5" progress label.
- Reasoning effort is set per bot in each `config.py` (triggers the per-bot override approach in
  `app.py`); models were intentionally left following the global default (`gpt-5.4-mini`) rather than
  pinned, since only the effort was meant to change.
- `internal` routes prompts through its selected `source_chatbot`, so it inherits the prompt fix from
  whichever source bot is active; its own `sampleprompt.py` was patched too for consistency, and its
  `config.py` effort was raised because `internal` runs under its own approach (selected by name).

#### Changes

- `app/backend/approaches/chatbots/{lemon,bensberg,demo,fbn,moodle,steuertipps,publishone,internal,knoll}/sampleprompt.py`:
  added a 🟠 P1 "Tutor Start Gate" (no Frage 1 until topic+level+count collected; count question
  mandatory; level-vs-count disambiguation) and a 🟠 P1 "Deterministic Question Count" block; changed
  question transitions and the start-confirmation template to render `Frage {{N}} von {{Total}}:`;
  reinforced the counter rules and reconciled the "no number prefix" rule with the mandatory visible
  heading. (Standard 8 patched by a one-off script; knoll patched by hand to match its compact style.)
- `app/backend/approaches/chatbots/{lemon,bensberg,demo,fbn,moodle,steuertipps,publishone,internal,knoll}/config.py`:
  set `reasoning_effort="high"` (lemon/bensberg changed from `"medium"`; the other seven added it).
- `app/frontend/src/chatbots/registry.ts`: `reasoningEffort` `medium` → `high` for all nine tutor-mode
  entries (display metadata mirrors the backend config).
- `tests/test_app_config.py::test_app_creates_chatbot_override_for_nerilio_config`: updated to the new
  override behavior — moodle/publishone now get per-bot override approaches (reasoning differs) and
  assert `reasoning_effort == "high"`; also corrected pre-existing staleness (fhg is overridden via its
  pinned model; nerilio model/deployment is `gpt-4.1-mini`).
- `CLAUDE.md`: added a Contracts-To-Preserve bullet describing the tutor start gate, visible counter,
  terminal stop, and `reasoning_effort="high"` for tutor bots.
- Validation: `pytest tests/test_app_config.py::test_app_creates_chatbot_override_for_nerilio_config
  tests/test_app_config.py::test_app_creates_chatbot_overrides_for_deployment_and_reasoning_only_differences
  tests/test_chatbot_config_registry.py` pass; `py_compile` clean on all 18 edited backend files. The
  other `test_app_config.py` failures are pre-existing (app-startup `Lifespan`/network in this offline
  env), confirmed identical on baseline via `git stash`.

### Generic category purge script

#### Decisions

- Added a new generic script instead of changing `delete_documents_by_category.py`, because the
  existing script is a narrowly scoped search-index-only tool and remains useful for index-only
  purges.
- The new command defaults storage deletion to `content/<category>/` by translating the storage
  container (`content`) to a blob prefix of `<category>/`. It accepts `--blobprefix` for exceptional
  layouts and strips a leading `content/` segment when supplied.

#### Changes

- `app/backend/delete_category_data.py` (new): deletes Azure AI Search documents where
  `category=<category>` and blobs under the matching content-container prefix in one run, using the
  same azd environment and Azure credential setup as the existing backend scripts.
- `tests/test_delete_category_data.py` (new): covered category/prefix validation, blob-prefix
  deletion, combined search/storage deletion, and Azure setup/cleanup wiring.
- `CLAUDE.md`: documented `delete_category_data.py <category>` for combined category purges and kept
  `delete_documents_by_category.py <category>` documented for search-only purges.
- Validation: `.\.venv\Scripts\python.exe -m pytest tests/test_delete_category_data.py tests/test_delete_documents_by_category.py`
  passed (`9 passed`).

### FHG: auto-index JSON drops from Nerilio folder

#### Decisions

- Reused the existing `moodle-auto-indexer` Function App instead of creating a separate FHG service,
  because its blob mirror/delete/index workflow already matches the requested behavior.
- FHG auto-index events watch `content/nerilio/Nerilio-fhg/*.json`, mirror accepted files into
  `content/fhg/`, and index the generated search documents with category `fhg`.
- Kept FHG on the existing `prepdocslib.fhgjson` parser so URL citations, titles, tags, and
  FHG-specific chunk IDs stay aligned with the manual `prep_fhg_json.py` ingestion path.

#### Changes

- `app/functions/moodle_auto_indexer/function_app.py`: added an `fhg` feed definition, FHG JSON
  section builder, and `fhg_auto_index` / `fhg_delete_sync` Event Grid handlers.
- `app/backend/prepdocslib/{blobautoindex.py,blobmanager.py,searchmanager.py}`: added exact
  storage-URL cleanup support so FHG updates/deletes remove indexed documents even though FHG
  sections keep per-study `sourcefile` metadata instead of the dataset filename; synchronized the
  `app/functions/*/prepdocslib/` copies with `scripts/copy_prepdocslib.py`.
- `scripts/setup_moodle_delete_event_subscription.py`: added create/delete Event Grid subscriptions
  for `nerilio/Nerilio-fhg/` JSON blobs.
- `tests/test_function_apps.py`: covered FHG create/delete routing and metadata-preserving JSON
  section generation.
- `tests/test_blobautoindex.py` and `tests/test_searchmanager.py`: covered storage-URL-based
  cleanup behavior and exact `storageUrl` filtering.
- `CLAUDE.md`: documented FHG as part of the feed automation contract and adding-data workflow.
- Validation: `.\.venv\Scripts\python.exe -m pytest tests/test_blobautoindex.py tests/test_fhgjson.py tests/test_function_apps.py tests/test_searchmanager.py::test_build_filter_can_match_exact_storage_url`
  passed (`68 passed`).

## 2026-06-18

### Free Bot: finish the `public-test` → `free` code/folder rename (names only, persisted keys kept)

#### Decisions

- Scope confirmed with the user as **code & folder names only**: rename the source folder, Python
  module, classes/functions, internal TS symbols, comments, and log text — but **leave every
  persisted-state key and legacy route untouched** so live data and sessions stay stable. This is the
  compatibility split the `public-test` contract in `CLAUDE.md` warns about; renaming the persisted
  keys would orphan accounts/history or log users out.
- Persisted VALUES kept exactly as-is (identifier *names* now say `free`, with explanatory comments):
  blob container `"public-test-auth"`, session cookie `"public_test_session"`, serializer salt
  `"public-test-auth-session"`, CosmosDB history scope id `"public-test"` and prefix `"public-test:"`,
  the in-process app.config key value `"public_test_auth_service"`, all legacy `/public-test-*` routes
  and the `/public-test` → `/free` redirect, the `KNOWN_CHATBOT_NAMES`/`EMBED_DEMO_EXCLUDED`/embed-id
  `public-test` aliases, and per the user the infra `publicTest*` / `PUBLIC_TEST_SMTP_*` env vars.
- Pre-existing, unrelated test failures left as-is (not caused by this change): `test_chatapproach.py`
  ×2 (asserts old `info@snap.de` vs the bot's `hallo@nerilio.ai`) and `test_upload.py` ×6 (assert
  stale `public-test/` upload paths; runtime already writes `free/` + a `MockBlobClient.delete_blob`
  gap). Verified the failure set is unchanged before/after.

#### Changes

- Renamed (via `git mv`): `app/frontend/src/chatbots/public-test/` → `free/`;
  `app/backend/core/publictestauth.py` → `core/freeauth.py`;
  `app/backend/approaches/chatbots/public_test/` → `chatbots/free/`;
  `pages/PublicTestUsersPage.tsx`(+`.module.css`) → `FreeUsersPage.*`;
  `pages/publicTestUsersApi.ts` → `freeUsersApi.ts`; `tests/test_publictestauth.py` → `test_freeauth.py`.
- Backend symbols: `PublicTestAuthStore`→`FreeAuthStore`, `PublicTestSession`→`FreeSession`,
  `normalize_public_test_email`→`normalize_free_email`, `get_authenticated_public_test_user`→
  `get_authenticated_free_user`, route handler fns `public_test_*`→`free_*`,
  `CONFIG_PUBLIC_TEST_AUTH_SERVICE`→`CONFIG_FREE_AUTH_SERVICE` (value kept), app.py
  `PUBLIC_TEST_CHATBOT_NAME`→`FREE_CHATBOT_NAME`, cosmosdb constants →
  `FREE_HISTORY_CHATBOT_NAME`/`FREE_ROUTE_CHATBOT_NAME`/`FREE_HISTORY_USER_PREFIX` (values kept).
- Registries: prompt module path → `approaches.chatbots.free.sampleprompt`; emptied
  `CHATBOT_CONFIG_FOLDER_MAP` (folder now matches the name). Kept the `"public-test" → "free"` alias.
- Frontend symbols inside `free/`: `PublicTestSession`/`PublicTestProfile`/`PublicTestUserOptions`/
  `getPublicTestUserScope`/`validatePublicTestEmail` → `Free*`/`getFreeUserScope`/`validateFreeEmail`;
  `registry.ts` import `./public-test` → `./free`; `index.tsx`/`FreeUsersPage`/`freeUsersApi` symbols.
- Validation: backend pytest matched baseline (28 free/legacy app tests pass; app boots clean);
  `npm run build` + `tsc --noEmit` pass; `ty` shows only pre-existing diagnostics.

### `bensberg`: Lemon-derived public Tutor + Q&A bot route

#### Decisions

- Added `/bensberg` as a Lemon-derived bot: same yellow Lemon visual theme, Lemon logo/chrome,
  Tutor + Q&A mode, agentic retrieval default enabled, and no simple/basic-auth credential entry.
- The visible browser/header title is `Bensberg`. The backend prompt/config retains Lemon's support
  address (`info@lemon-systems.de`) because the request explicitly asked to base the bot on Lemon
  and did not specify a different fallback contact.
- Bensberg uses its own retrieval category (`bensberg`) so the attached document can be indexed as a
  single-category knowledge base. No Bensberg source document was present in the workspace, so
  ingestion was not completed in this session.
- The HYROX assessment bot is now explicitly excluded from Internal Bot source-bot options/history
  validation because it is an assessment flow, not a normal retrieval source bot.

#### Changes

- Backend: added `app/backend/approaches/chatbots/bensberg/` with Lemon prompt/config, registered
  `bensberg` in `chatbot_prompt_registry.py`, `KNOWN_CHATBOT_NAMES`, embed public IDs, and widget
  launcher colors.
- Backend: expanded the Lemon-style output sanitizer to apply to `bensberg` as well, so Bensberg
  suppresses source labels, filenames, and structural IDs like Lemon.
- Frontend: added `app/frontend/src/chatbots/bensberg/` with Lemon-reused layout/chat components,
  Bensberg i18n titles/examples, `/bensberg` routing, Lemon theme color, and Internal Bot labels.
- Tests: updated chatbot config, `/config`, embed ID, prompt rendering, sanitizer, and invalid
  Internal Bot source-bot coverage for Bensberg/HYROX.
- Validation: focused pytest set passed (`22 passed`); `npm run build` in `app/frontend` passed.

## 2026-06-17

### `hyrox-assessment`: Start button moved inline below the welcome text

#### Decisions

- Moved the Start button from the sticky bottom footer to **inline, directly below the welcome/rules
  message** (left-aligned with it). On the welcome screen there is no transcript above, so a pinned
  bottom button floated with a large empty gap on tall/desktop screens; inline placement gives strong
  read→act proximity and reads as the natural next step. Consistent at the principle level: the action
  follows the content it relates to — Start follows the welcome (top); Restart still follows the
  completion bubbles (bottom footer). The button keeps the shared `.footerActionButton` look
  (48px target, 1.5rem radius).

#### Changes

- `app/frontend/src/chatbots/hyrox-assessment/pages/chat/Chat.tsx`: render the Start button inside the
  message stream right after the answers map (new `.startInline` container) instead of the footer.
- `app/frontend/src/chatbots/hyrox-assessment/pages/chat/Chat.module.css`: added `.startInline`
  (left-aligned, in-flow); `.footerAction` is now the Restart-only footer slot (comment updated).
- No test changes needed — the e2e tests locate the button by role/name, independent of placement.

### `hyrox-assessment`: footer button sizing + radius polish

#### Decisions

- The footer button (Start/Restart) was too small on phones and its radius didn't match the chat
  surface. Root cause of the size: the html root font-size scales 12px (320px phones) → 16px
  (desktop), so the button's rem-based padding shrank the tap area to ~36px on small phones (below
  the 44–48px touch-target minimum). Fix: a fixed `min-height: 48px` (a device-independent floor),
  `display: inline-flex` centering, and `padding: 0.5em 2em` (em tracks the fixed 15px label, not the
  shrinking root), so the target is ≥48px on every device. Mirrors the px-not-rem rule already used
  for readable text.
- Border-radius changed `0.5rem` → `1.5rem` to match the question-input composer the button shares
  the footer slot with (and the chat bubbles at 1.5em); both use 1.5rem so they look identical in
  that slot at every breakpoint.

#### Changes

- `app/frontend/src/chatbots/hyrox-assessment/pages/chat/Chat.module.css`: reworked
  `.footerActionButton` (min-height/flex/em-padding/max-width + `border-radius: 1.5rem`). Applies to
  both the Start and Restart buttons (shared class).

### `hyrox-assessment`: "Start assessment" button replaces typing "Start"

#### Decisions

- The welcome screen now shows a **"Start assessment"** button instead of instructing the learner to
  type "Start" — chosen for consistency with the new Restart button, accessibility (no typing/locale
  guessing), and one-tap mobile UX. Technically free: the backend begins the run on the *first*
  message regardless of wording, so the button just calls `makeApiRequest("Start")` — identical to
  the old typed flow.
- On the welcome screen the text input is **hidden** and replaced by the button (there is nothing
  meaningful to type until Q1). The input returns once the run begins. Footer states are mutually
  exclusive: not-started → Start button; in-progress → input; failed → Restart button; passed →
  nothing. Detection reuses `stripLeadingSyntheticInitialPairs(answers).length === 0` (no real turn
  yet). After a Restart, the welcome's Start button is what reappears.

#### Changes

- `app/frontend/src/chatbots/hyrox-assessment/pages/chat/Chat.tsx`: added `assessmentNotStarted`;
  render the Start button on the welcome screen (hidden while loading); input now gated on
  `!assessmentNotStarted`.
- `app/frontend/src/chatbots/hyrox-assessment/pages/chat/Chat.module.css`: renamed `.restartInput`/
  `.restartButton` → neutral `.footerAction`/`.footerActionButton` (shared by Start + Restart).
- `app/frontend/src/chatbots/hyrox-assessment/locales/{en,de,nl}/translation.json`: added
  `startAssessment`; removed the trailing "type Start" instruction line from `initialAssistantMsg`.
- Tests: `tests/e2e.py` — the three HYROX tests now begin via the Start button (and assert the input
  is absent on the welcome screen / the Start button reappears after a Restart).

#### Validation

- `tests/test_hyrox_assessment.py`: 51 passed. Frontend `tsc --noEmit`: 0 errors. `npm run build`: ok.
  All three locale JSON re-validated (parse OK, welcome lines trimmed, no leftover newline). e2e still
  not runnable locally (same Azure-auth startup limitation).

### `hyrox-assessment`: in-app "Restart assessment" after a failed run

#### Decisions

- A failed assessment can now be retaken in-app with no limit, instead of only via a fresh
  Lemon-app launch. On a **failed** completion the chat shows a **"Restart assessment"** button in
  the same sticky footer slot the question input occupied; clicking it calls the existing
  `clearChat`, which resets to a fresh session (welcome + rules) exactly like a brand-new launch.
  No backend message is sent — the reset just drops the conversation so the next run has no
  `[[PLAN]]` and starts over. The backend remains stateless/terminal-in-session; only *where* a
  fresh session is launched from changed.
- Pass detection is the backend's hidden `[[PROGRESS value=N]]` marker (pass-only). A completed run
  (`[[DONE]]`) **without** `[[PROGRESS]]` is a fail → show restart. A pass takes the certificate
  flow with **no** restart button. `clearChat` now also re-arms `progressReportedRef` so a passing
  run *after* a restart still fires the one-shot `lemon://save_progress` hand-off.
- Edited the failed closing copy to the shorter, app-agnostic wording ("…you'll find the option to
  restart.") and dropped the "lemon app" reference from `closing_failed` (en/de/nl) and from the
  completed-run model state-injection (now points at the restart button). The completion bubble
  structure (5 `[[BREAK]]` sections) is unchanged.

#### Changes

- `app/backend/approaches/chatbots/hyrox_assessment/results.py`: rewrote `closing_failed` for en/de/nl;
  updated the `build_state_injection` completed-run branch to reference the restart button instead of
  the Lemon app; refreshed the `[[DONE]]`/`derive_turn_state`/`render_completion_bubbles` comments to
  the new retake model.
- `app/frontend/src/chatbots/hyrox-assessment/pages/chat/Chat.tsx`: derive `assessmentPassed`
  (`parseProgressValue`) / `assessmentFailed`; render the restart button on a fail; reset
  `progressReportedRef` in `clearChat`; updated the completion comment.
- `app/frontend/src/chatbots/hyrox-assessment/pages/chat/Chat.module.css`: added `.restartInput`
  (footer slot) + `.restartButton` (HYROX black/yellow).
- `app/frontend/src/chatbots/hyrox-assessment/locales/{en,de,nl}/translation.json`: added
  `restartAssessment`.
- `app/frontend/src/chatbots/hyrox-assessment/components/Answer/assessmentMarkers.ts`: refreshed the
  `[[DONE]]` comment.
- Tests: updated `tests/test_hyrox_assessment.py` (failed-injection + failed-closing assertions);
  `tests/e2e.py` made the passed-completion mock faithful (`[[PROGRESS value=100]]`) + assert no
  restart on pass, and added `test_hyrox_assessment_failed_offers_restart`.

#### Validation

- `tests/test_hyrox_assessment.py`: 51 passed. Frontend `tsc --noEmit`: 0 errors. `npm run build`: ok.
- e2e (`tests/e2e.py -k hyrox_assessment`) could **not** run locally: the live-server fixture starts
  the real app, whose startup uses `AzureDeveloperCliCredential` against the fixture's fake
  `AZURE_SUBSCRIPTION_ID`; with `azd` logged in on this machine the CLI is invoked and fails. The
  unchanged `test_hyrox_assessment_keeps_input_mid_assessment` fails identically — environment, not a
  regression.

## 2026-06-16

### Fix: `/embed-demo` tab showed the stale Azure favicon, not the nerilio robot

#### Decisions

- Root cause: the React SPA template (`app/frontend/index.html`) declares an explicit
  `<link rel="icon" … robo1.png>` (Vite bundles it to a hashed `/assets/*.png`), so every
  chatbot/admin page shows the robot. The server-rendered `embed_demo.html` has **no** icon
  link, so the browser falls back to `/favicon.ico` — which was still the leftover Azure-default
  favicon from the original azure-search-openai-demo template (the blue "A").
- Fixed at the shared fallback rather than per-page: regenerated `favicon.ico` from the nerilio
  robot so `/favicon.ico` serves the robot everywhere it's used as a fallback (embed-demo and any
  non-SPA page). The SPA keeps its own explicit link, so no SPA change was needed. Did not add a
  per-page `<link>` to `embed_demo.html` because the robot asset is content-hashed per build (no
  stable URL to point at from a static template).

#### Changes

- `app/frontend/public/favicon.ico` (committed source) and `app/backend/static/favicon.ico`
  (served build artifact, not git-tracked): replaced the Azure default with a multi-size ICO
  (16/24/32/48/64/128/256) generated from `app/frontend/src/assets/robo1.png` via Pillow. Source
  was 885×885 (already square), so no padding/distortion.

### Fix: embedded bots shared one chat history (publishone showed nerilio's chats)

#### Decisions

- Regression from the anonymized embed route: chat-history scope, the active-session pointer,
  citation paths, and the cosmos `chatbot_name` all derive from `getCurrentChatbotName()`, which
  reads the **first URL path segment**. The old embed URL was `/<name>?embed=1` (segment = the bot),
  but the new one is `/embed/<publicId>` (segment = the literal `embed` for *every* bot) — so all
  embedded bots collapsed onto a single `embed` scope and showed each other's history.
- Fix at the single source: on the `/embed/...` route, `getCurrentChatbotName()` returns the
  backend-injected `window.__EMBED_CHATBOT_NAME__` instead of the path segment, restoring exact
  per-bot scoping. This simultaneously fixes the IndexedDB history bleed, the active-session
  pointer, citation `/content/<name>/…` paths, and the cosmos history `chatbot_name`.
- Also restored backend parity: `get_request_route_chatbot_name()` now maps an `/embed/<publicId>`
  `Referer` back to the real bot (was returning None, falling back to the request-body name) so
  telemetry and simple-auth route resolution match the old behavior.

#### Changes

- `app/frontend/src/chatHistoryScope.ts`: `getCurrentChatbotName()` resolves the `/embed` route via
  `window.__EMBED_CHATBOT_NAME__`.
- `app/backend/app.py`: `get_request_route_chatbot_name()` resolves an `/embed/<publicId>` referer
  via `resolve_public_id`.
- `tests/test_app.py`: added referer-resolution tests (embed public ID, unknown ID, plain name) and
  a guard that `chatHistoryScope.ts` consults `__EMBED_CHATBOT_NAME__`.

### Embeddable widget: anonymous public IDs + per-bot domain whitelist

#### Decisions

- Two new widget requirements: (1) reference each chatbot by an **anonymous public ID** (GA/Clarity
  style, e.g. `oba6k03jtq`) instead of the readable route name in the embed code, and (2) a
  configurable **domain whitelist** per bot so the widget renders only on allowed pages.
- Confirmed four design forks with the user before building: public IDs are a **committed code map**
  (stable across deploys), the whitelist is **blob-backed + admin-edited** (no redeploy), enforcement
  is **client-side hide + backend `frame-ancestors` CSP** (layered), the public ID anonymizes **both
  the script tag and the iframe URL**, and this is a **hard cutover** — the widget no longer accepts
  plain chatbot names.
- Public IDs cover the 15 embeddable bots (everything with a backend prompt module; `internal` and
  `public-test` excluded). The committed values must never change once shipped, or live embeds break.
- Empty whitelist = **allow all** (keeps today's `frame-ancestors *` default), so deploying the
  feature does not silently break existing embeds; admins opt into restriction by adding rules.
- Rule semantics (shared between Python `embed_rules.py` and the TS matcher in `widget.ts`):
  case-insensitive host, `*.host` matches subdomains but not the apex, case-insensitive scheme is
  ignored, path is case-sensitive with `/*`/trailing-`*` prefix matching, query ignored. Only the
  **origin** part is enforceable via CSP; path-level rules are client-side only (documented).
- The anonymized `/embed/<publicId>` route resolves the bot server-side and serves the SPA with
  `window.__EMBED_CHATBOT_NAME__` injected, so the name never appears in the host DOM or iframe
  `src`. The widget fetches `/embed/<publicId>/config` (CORS) for launcher color + rules, returning
  **no name** so the host page cannot recover the bot identity. Launcher colors are mirrored in a
  small backend map (kept in sync with `chatbotThemes.ts`) since the widget no longer bundles themes.
- Canonical `/<chatbot_name>` routes stay (direct/admin browsing) and also get the per-bot
  `frame-ancestors` lock, closing the bypass of iframing `/<name>?embed=1` directly.

#### Changes

- `app/backend/embed_public_ids.py` (new): committed public-ID↔name map, resolver helpers,
  `generate_public_id`, and a `python -m embed_public_ids` generator for new bots.
- `app/backend/embed_rules.py` (new): rule parsing/normalization, `match_url`, and
  `rules_to_frame_ancestors` (CSP value builder).
- `app/backend/core/chatbotembedconfigstore.py` (new): blob-backed per-bot whitelist store
  (`chatbot-embed-config` container), mirrors `ChatbotPromptStore`.
- `app/backend/config.py`: added `CONFIG_CHATBOT_EMBED_CONFIG_STORE`.
- `app/backend/app.py`: imported the new modules; wired the store at startup; `serve_spa_index`
  gained `chatbot_name`/`embed_public_id` params (per-bot CSP + name injection); added
  `/embed/<publicId>/config` (CORS) and `/embed/<publicId>` routes, plus admin
  `GET/PUT /internal-admin/embed-config/<name>`; `chatbot_entry` now locks framing per bot;
  `/embed-demo` options now emit public IDs; reserved `embed`/`embed-demo` prefixes.
- `app/frontend/src/widget/widget.ts`: treats `data-chatbot-id` as a public ID; fetches config,
  validates the host URL against the whitelist (renders nothing on no match), resolves launcher
  color from config, points the iframe at `/embed/<publicId>`; dropped the `chatbotThemes` import.
- `app/frontend/src/index.tsx`: added the `/embed/:publicId` route that mounts the bot named by the
  injected `window.__EMBED_CHATBOT_NAME__`.
- `app/frontend/src/pages/embedAdminApi.ts` (new) + `EmbedSnippetModal.tsx`/`.module.css`: the Embed
  dialog now loads the public ID, shows the public-ID snippet, and edits/saves the domain whitelist.
- `app/backend/embed_demo.html`: rewrote the served `/embed-demo` page into a full how-to — live
  demo, a two-step "add it to your website" guide, and plain-language explainers for the anonymous
  ID and the domain whitelist (with a rules table), alongside the how-it-works + options tables.
  Then gated it behind the internal-admin password (vanilla-JS login form posting to
  `/internal-admin/login`/`session`/`logout`, mirroring `useInternalAdminAccess`) and added an
  inline whitelist editor so the allowed-domains list can be managed from `/embed-demo` as well as
  the `/chatbots` Embed dialog (both call the same admin-gated `/internal-admin/embed-config/<name>`).
- `docs/embedding.md`, `CLAUDE.md` (embed contract): documented public IDs, the whitelist, and the
  layered enforcement model.

### hyrox-assessment: drop the redundant LLM intro before Question 1

#### Decisions

- The `/hyrox-assessment` bot showed **two** welcome messages: (1) the static frontend
  `initialAssistantMsg` ("Welcome to the HYROX Assessment 'Managing Performance'! … Type 'Start'
  when you are ready to begin.") and, after the learner typed "start", (2) an LLM-generated intro
  paragraph that restated the same rules (20 questions, free text, one revision, 80% to pass, topic
  summary at the end) before Question 1. The second was redundant with the first.
- Fix: keep the static frontend welcome; remove the model-authored intro so the assessment begins
  **immediately with Question 1** after "start". The `is_first_of_run` branch in
  `build_state_injection` (the only place that requested the intro) now explicitly tells the model
  the learner has already seen the full welcome/rules and to output only `[[ASK]]` with no preamble.
- Scope kept minimal: no change to the static welcome copy, the question flow, or the rendering
  pipeline. No test asserted on the old intro wording, so no test changes were needed; all 51
  `tests/test_hyrox_assessment.py` cases still pass.

#### Changes

- `app/backend/approaches/chatbots/hyrox_assessment/results.py`: rewrote the `is_first_of_run`
  instruction in `build_state_injection` to forbid any intro/welcome/greeting/rules-recap and begin
  immediately with the question (`[[ASK]]` only, nothing before it).

---

## 2026-06-15

### All bots: answer-table containment extended to tablet portrait (fix 768–991px x-scroll)

#### Decisions

- Bug: in `/nerilio` (embed/widget) the answer pricing table forced a **horizontal page scroll** at
  tablet-portrait widths (iPad Mini 768, iPad Air 820) while phones (412px) were fine.
- Root cause: the table guard `.tableScroll { contain: inline-size; }` — which stops a wide table's
  intrinsic min-content from propagating up the answer bubble + `min-width:auto` flex chain and pushing
  the page past the viewport — was gated at `@media (max-width: 767px)` (phones only). But the app's
  compact-layout breakpoint is **991px** (`Chat.module.css`: mobile padding `max-width:991px`, history
  overlay `min-width:992px`). So 768–991px rendered the compact layout **without** the containment → the
  table grew the page. Phones had containment, hence "fine on mobile, broken on tablet".
- Fix in the **shared** answer CSS (nerilio renders via `createBotAnswer` → `ChatbotAnswer` →
  `SharedAnswer.module.css`; its local `Answer.module.css` is legacy/unused), so the fix lands for every
  bot — consistent with the recent "All bots:" responsive-table work. Pulled `contain: inline-size` into
  its own `@media (max-width: 991px)` block; desktop (≥992px) still intentionally lets wide tables grow
  the bubble to fill width. Phone-only cosmetic tweaks (padding, font-size, `th/td` min-width, wordmark)
  stay at `max-width:767px`.

#### Changes

- `app/frontend/src/chatbots/shared/answer/SharedAnswer.module.css` — moved `.tableScroll { contain:
  inline-size; }` out of the `max-width:767px` block into a new `max-width:991px` block (with explanatory
  comment); removed the now-redundant rule + comment from the 767px block.

### All bots: navbar menu + chat-history chrome mobile-legibility (14px)

#### Decisions

- Follow-up to the readable-text fix below. User asked whether the navbar **menu items** ("New chat",
  "Chat history"/"View recent chats") and the **chat-history** list were also handled — they weren't.
  Same root cause: those chrome elements are `rem`-based, so they shrank with the responsive `html` root
  on phones (menu items landed at ~10.5–12px, history panel/items ~10.8–12px).
- User chose **14px** (over 15px-match-body or leave-as-is): fixed `px` so they stop shrinking on mobile,
  while staying a touch below the 15px answer body — the conventional hierarchy for nav/list chrome that
  top chatbots use. Desktop barely moves (most `.dropdownItem` were already `0.875rem`≈14px on desktop).
- Scope limited to the readable chrome the user named: `.dropdownItem` (menu), `.groupLabel` (history
  date groups), `.historyItemTitle` (history entries). Left alone: navbar **title** (`1.4rem`/`1.7rem`,
  already large enough), already-fixed-px values (delete-modal `20px`/`14px`, history timestamps), and
  public-test's separate **profile panel** text (not a navbar menu).

#### Changes

- 15 `pages/layout/Layout.module.css` — `.dropdownItem` font-size → `14px` (was `0.875rem` most bots,
  `0.92rem` demo/public-test/rak, `1rem` nerilio). internal has no Layout (reuses another bot's).
- 15 `components/HistoryPanel/HistoryPanel.module.css` — `.groupLabel` `0.9rem` → `14px`.
- 15 `components/HistoryItem/HistoryItem.module.css` — `.historyItemTitle` `1rem` → `14px`.
- Applied via a one-shot selector-scoped regex (each replacement anchored to its own block, so the navbar
  title and public-test's profile panel were untouched). Verified: `npm run build` passes; Playwright at
  390px (root 12px) measures the open menu items ("New chat", "View recent chats") at **14px** for nerilio
  and lemon (were 12px / 10.5px), screenshot confirms clean rendering.

### All bots: mobile-legible readable-text sizing (15px, decoupled from shrinking root)

#### Decisions

- **Root cause** of "text too small on mobile": the global `html` root font-size in
  `app/frontend/src/index.css` scales **down** on small screens (16px desktop → 15 → 14 → 13 →
  **12px below 480px**). Because nearly all readable text is sized in `rem`/`em` (or inherits the
  root), every text element shrinks ~25% on a phone. The shared answer body (`0.95rem` mobile) landed
  at **~11.4px** on a typical phone; the disclaimer at **~10.8px**; user messages inherited the root at
  **~12px**. Desktop (~15.7px) was already fine and matched top chatbots, as the user noted.
- The user's earlier nerilio fix (hardcoding `--chatbot-answer-font-size*` and the disclaimer vars to
  `15px`) was the **right direction** — fixed `px` bypasses the shrinking root — but only covered
  nerilio's answer + disclaimer + user message, leaving the composer untouched and the other 15 bots
  still tiny.
- **Approach chosen** (user picked "whatever is smoothest / looks best across all sizes", **15px
  everywhere**, **all readable text**): targeted token fix, **not** a global root-font change. The root
  scale is left intact for layout proportions; only readable text is decoupled from it. Lowest blast
  radius across 16 forked bots, no layout disturbance. Rejected raising the `html` root floor (would
  resize every `rem`-based padding/gap/width on mobile — high risk, needs per-bot QA).
- **Target = 15px**, applied as fixed `px` so body text is constant on every viewport. (Industry ideal
  is ~16px — ChatGPT/Claude/Gemini/Material; 15px matches the user's tuned nerilio and is very
  readable. Noted but not overridden.) Answer **headings** and code-block toolbar labels converted
  `rem`→`em` so they track the 15px body and keep a consistent hierarchy at every width instead of
  shrinking with the root.
- **Composer left as-is**: all 16 bots already set `fontSize: 16` inline on the FluentUI TextField
  (internal reuses lemon's QuestionInput), and the viewport meta uses `maximum-scale=1` so iOS
  input-zoom isn't a concern.
- Shared answer + shared disclaimer are single levers (all 16 `Answer.tsx` route through
  `shared/answer/createBotAnswer`), so their default change fixes every bot at once; per-bot
  `--chatbot-*-font-size*` overrides still win (nerilio's redundant 15px overrides left untouched).

#### Changes

- `app/frontend/src/chatbots/shared/answer/SharedAnswer.module.css`: `.answerMarkdown` body default
  `0.98rem`→`15px` (desktop) and `0.95rem`→`15px` (≤767px mobile branch); `h1–h4` `rem`→`em`
  (1.45/1.22/1.08/1em); `.codeBlockLanguage` `0.74rem`→`0.78em`; `.codeBlockCopyButton` `0.82rem`→`0.82em`.
- `app/frontend/src/chatbots/shared/disclaimer/ChatbotDisclaimerBanner.module.css`: `.message` default
  `0.95rem`→`15px` (desktop) and `0.9rem`→`15px` (≤640px mobile branch).
- 14 `UserChatMessage.module.css` forks — added `font-size: 15px` to `.message` (agindo, demo, fbn, fhg,
  hyrox-assessment, knoll, lemon, moodle, public-test, publishone, rak, sartorius, steuertipps, vjoonk4;
  nerilio already had it; internal reuses lemon's component).
- Verified with the Vite-dev + Playwright route-mock harness (see memory `verify-frontend-answer-rendering`):
  lemon & nerilio measure **body 15px / h2 18.3px / user-msg 15px / table 15px** at 375/768/1280px (root
  12/15/16px respectively); mobile screenshots confirm comfortable legibility. Frontend `npm run build`
  passes. rak/sartorius are basic-auth-gated in the harness but share the same edited code.

### All bots: continuous table scroll shadow (overlay instead of background)

#### Decisions

- Follow-up to the 2026-06-13 scroll-shadow work. User reported the right-edge "more content" shadow broke
  **cell-by-cell** — it disappeared over the darker header row. Root cause: the 2026-06-13 fix painted the edge
  shadows into the **`background` of `.tableScroll`**, i.e. *behind* the table (Lea Verou technique). For a background
  shadow to show, everything stacked on top must be transparent — which is why `.answerTable` was made transparent.
  But the header cells (`.answerMarkdown th { background: #f8fafc }`, and any cell with its own fill) are opaque and
  paint their own box *over* the shadow, punching a hole in it. The break lined up with cell edges because that's
  where the opaque fill starts/stops. Not an inconsistent shadow — an **occluded** one.
- Chose the **overlay** fix (option 1, user pick) over making cells semi-transparent (option 2): render the edge
  shadows *above* the cells so no cell background can occlude them, giving one continuous edge regardless of cell fills.
- Implementation: wrap the scroller in a new positioned `.tableScrollFrame`; draw the two edge shadows as
  `::before`/`::after` overlays on the frame (`position: absolute`, `pointer-events: none`, `z-index: 2`). Visibility is
  driven by the **live scroll position** via `data-can-scroll-left/right` attributes set from a small `ScrollableTable`
  React component (scroll + `ResizeObserver` listeners). This preserves the original self-hiding behaviour (each side
  hides at its extreme; neither shows on a table that fits) which a pure-CSS overlay can't do without phantom shadows —
  and `ResizeObserver` re-checks on streamed-content growth / resize. Border + radius + corner clipping moved to the
  frame; `.tableScroll` keeps the scroll/scrollbar styling and a plain white background. Mobile
  `contain: inline-size` stays on `.tableScroll` (still the load-bearing page-overflow fix).
- Verified live in Playwright at 390px: data attributes track correctly (left edge → right shadow only; mid → both;
  far right → left shadow only) and screenshots show the right-edge shadow running continuously over the darker header
  cell. Added an e2e test asserting the attribute toggling; the existing publishone table test still passes.
- Note (not a regression): `test_shared_answer_renderer_handles_markdown_and_literal_html` fails because it looks for
  the old composer placeholder `"Type a new question (e.g. …)"`; nerilio's i18n is now `"Type your message"`.
  Pre-existing test-vs-app drift, unrelated to this change.

#### Changes

- `app/frontend/src/chatbots/shared/answer/ChatbotAnswer.tsx`: added `ScrollableTable` component (refs + scroll/
  `ResizeObserver` → `data-can-scroll-left/right`); the markdown `table` renderer now returns `<ScrollableTable>`.
- `app/frontend/src/chatbots/shared/answer/SharedAnswer.module.css`: replaced the background-gradient scroll shadows on
  `.tableScroll` with a `.tableScrollFrame` wrapper + `::before`/`::after` overlay shadows toggled by data attributes;
  moved border/radius/`overflow: hidden` to the frame; `.tableScroll` keeps scrollbar styling + white background.
- `tests/e2e.py`: added `test_shared_answer_wide_table_scroll_shadows_track_position` (wide table overflows at 480px;
  asserts the frame's `data-can-scroll-*` attributes follow scroll position).

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
