# graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:

- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- After modifying code files in this session, run `graphify update .` to keep the graph current (AST-only, no API cost)

# Instructions for Coding Agents

Very important: Do not make any changes until you have 95% confidence in what you need to build. Ask me follow-up questions until you reach that confidence.

This repo is an Azure Search and OpenAI RAG demo with many chatbot-specific forks. Agents should use graphify for structure, but keep the human workflow and safety contracts in this file.

## Operating Rules

- Keep this file updated when a change affects agent workflow, repo invariants, deployment steps, or feature playbooks. Do not expand it into a file-by-file index.
- Use Context7 MCP for current documentation whenever a question depends on a library, framework, SDK, API, CLI tool, or cloud service. Start with library resolution unless an exact `/org/project` ID is provided, then query docs. Prefer this over web search for library docs. Do not use it for refactoring, business-logic debugging, code review, or general programming concepts.

## Canonical artifacts

| File | Role |
| --- | --- |
| `CLAUDE.md` | Canonical agent playbook (this file) |
| `AGENTS.md` | Thin pointer to `CLAUDE.md` for non-Claude agents |
| `CHANGES.md` | Project changes log — read first to catch up on prior sessions |
| `graphify-out/GRAPH_REPORT.md` | God nodes and community structure for architecture questions |
| `graphify-out/wiki/index.md` | Navigable wiki view of the codebase, if present |
| `PULL_REQUEST_TEMPLATE.md` | PR format to follow when sending pull requests |

## Changes log maintenance

`CHANGES.md` at the project root records all file edits and design decisions
from each session. **At the end of any session that produced file edits or
recorded design decisions, append a new dated entry before signing off.** Use
the existing two-category format (Decisions, Changes) and newest-on-top order.
If today already has a section, append to it rather than creating a duplicate.
Convert relative dates to absolute (e.g., "today" → `2026-05-26`).

At the **start** of a session, read `CHANGES.md` (most recent entries first)
to catch up on what's been done since you were last here. This is the primary
mechanism for cross-session continuity between Claude, Codex, and any other
agent working on the repo.

## Where To Start

Use graphify as the map, then inspect the smallest relevant code surface. The highest-signal entrypoints are:

- `app/start.ps1`: local bootstrap for azd env loading, `app/.venv`, dependency restore, frontend build, and Quart startup.
- `app/backend/app.py`: main Quart app and backend route surface.
- `app/backend/approaches/`: shared RAG logic, prompt rendering, chatbot config discovery, and per-bot behavior.
- `app/backend/prepdocslib/`: ingestion, parsing, upload/indexing, Azure AI Search schema writes, and feed-specific section builders.
- `app/functions/`: Azure Functions copies of shared ingestion code plus `moodle_auto_indexer`.
- `app/frontend/src/index.tsx`: frontend router for root, chatbot routes, chatbot fallbacks, and internal tools.
- `app/frontend/src/chatbots/registry.ts`: chatbot registration and route wiring.
- `app/frontend/src/chatbots/shared/`: shared answer, example, theme, speech, disclaimer, auth, and fallback building blocks.
- `infra/main.bicep` and `infra/main.parameters.json`: Azure provisioning and azd environment wiring.
- `tests/`: pytest unit, app integration, and Playwright e2e coverage.

## Contracts To Preserve

- Frontend chatbot routing is `/<chatbot_name>` inside each bot's `LayoutWrapper`; `/<chatbot_name>/*` renders that bot's `NoPage` outside the layout so fallback pages do not show chatbot chrome.
- Bots with frontend basic auth must guard both `LayoutWrapper` and standalone `NoPage`; otherwise `/<chatbot_name>/*` can bypass the gate.
- Chatbot basic auth for `agindo`, `demo`, `fbn`, `fhg`, `internal`, `knoll`, `moodle`, `rak`, `sartorius`, `steuertipps`, and `vjoonk4` uses server-side `/chatbot-auth/<chatbot_name>/*` HttpOnly cookies. `/chat` and `/chat/stream` intentionally remain ungated by that simple-auth cookie for iframe compatibility.
- Frontend login wrappers are API clients only. Do not reintroduce hardcoded browser-side credential checks.
- Backend `/config` is the frontend capability contract for model selection and reasoning effort. When model behavior changes, update backend metadata rather than hardcoding frontend assumptions.
- `/internal` is a router shell, not its own retrieval category. Internal requests must carry `context.overrides.source_chatbot`; backend validation derives the effective bot identity, prompt, and `include_category` from that selected source bot.
- `/config` includes `internalSourceBots` for the `/internal` source-bot dropdown. Do not reintroduce `All`; only one real source bot can be active per internal session.
- Internal chat history sessions must persist `source_chatbot` metadata. Legacy internal sessions without that metadata are intentionally hidden and non-restorable.
- Internal citations resolve against the selected source bot's content path while visible `/internal` branding stays fixed as `Internal Bot`.
- Backend startup auto-discovers optional chatbot backend modules under `app/backend/approaches/chatbots/<chatbot_name>/`. Do not add manual registration unless the code path truly requires it.
- Shared internal admin auth gates `/chatbots`, `/upload-files`, `/public-test-users`, `/manage-prompts`, and `/verwaltung/*` (excluding `/verwaltung/portal`); keep frontend and backend route names aligned.
- `public-test` keeps some legacy internal identifiers for compatibility even though public branding is "Free Bot". Verify compatibility before renaming storage, auth, or history namespaces.
- Frontend chatbot locales are standardized to `en`, `de`, and `nl`. Do not add extra locale folders unless expanding the entire bot set intentionally.
- Generic app marks should import `app/frontend/src/assets/applogo.svg`; avoid duplicate per-bot `applogo.svg` assets.
- If shared ingestion logic changes under `app/backend/prepdocslib/`, refresh synchronized copies under `app/functions/` with `python scripts/copy_prepdocslib.py`.
- Moodle/PublishOne/FHG feed automation must preserve both blob-copy/index behavior and the post-deploy Event Grid subscription script.
- `OPENLIT_ENDPOINT` points at an already-running OpenLIT backend. `azd up` does not provision or repair the standalone OpenLIT Container App.
- Azure Files SMB is not safe for OpenLIT ClickHouse data here. The known-working Container App setup uses `EmptyDir` for `clickhousedata` and `openlitdata`, with only config volumes on Azure Files; request history is non-persistent across replica recreation.
- External sites embed a chatbot via the `/widget.js` loader (built from `app/frontend/src/widget/widget.ts` by `vite.widget.config.ts`, chained after the main `vite build`). `data-chatbot-id` is an anonymous **public ID** (committed map in `app/backend/embed_public_ids.py`, GA/Clarity style), never the route name — this is a hard cutover, the widget no longer accepts plain names. On load the widget fetches `/embed/<publicId>/config` (CORS, returns launcher color + whitelist rules, never the name) and renders nothing unless the host page matches the bot's whitelist; on open it injects an iframe pointing at `/embed/<publicId>?embed=1`, which `embed_chatbot_entry` resolves server-side and serves via `serve_spa_index` with `window.__EMBED_CHATBOT_NAME__` injected (the `/embed/:publicId` SPA route mounts that bot). Chat calls inside the iframe are same-origin, so no CORS is needed for chat. The per-bot allowed-domains whitelist is blob-backed (`ChatbotEmbedConfigStore`, mirrors `ChatbotPromptStore`), edited via admin-gated `/internal-admin/embed-config/<name>` from both the directory's Embed modal and the `/embed-demo` page. Enforcement is layered: client-side hide (path + origin rules) plus per-bot `Content-Security-Policy: frame-ancestors` from `serve_spa_index` on both `/embed/<publicId>` and `/<chatbot_name>` (origins only — empty whitelist still means `frame-ancestors *`). The Python rule matcher (`app/backend/embed_rules.py`) and the TS matcher in `widget.ts` must stay in lockstep. Never reintroduce `X-Frame-Options`. Embed mode is detected via `?embed=1` (`isEmbedMode`), surfaced as `data-embed="1"` on the theme root, with `EmbedBridge` posting `chatbot:ready`/`chatbot:close`. Per-bot simple-auth cookies use `SameSite=None; Secure; Partitioned` over HTTPS so login survives the cross-site iframe; MSAL-gated bots cannot be embedded. A served `/embed-demo` route renders `app/backend/embed_demo.html` with a chatbot picker (options injected as public IDs); the page is gated client-side by the internal-admin session (login form posting to `/internal-admin/login`, mirroring `useInternalAdminAccess`) and also edits the per-bot whitelist. See `docs/embedding.md`.
- Tutor-mode bots (`bensberg`, `demo`, `fbn`, `knoll`, `lemon`, `moodle`, `publishone`, `steuertipps`, and `internal` via its selected source bot) share a hardened tutor flow in each `sampleprompt.py`. A 🟠 P1 **Tutor Start Gate** forbids asking Frage 1 until topic **and** knowledge level (1–5) **and** number of questions (3/5/10) are all collected; the count question is mandatory (level vs. count is disambiguated because 3/5 overlap). Every tutor question is headed with a visible running counter rendered in the active `{{language_locale}}` — `Frage {{N}} von {{Total}}:` (de) / `Question {{N}} of {{Total}}:` (en) / `Vraag {{N}} van {{Total}}:` (nl); the word "Frage" is NOT a fixed literal, so each prompt's three governing counter rules (bold-allowance, the DETERMINISTIC QUESTION COUNT master bullet, the "Always head the question…" bullet) must list all three forms or the model emits German even in en/nl sessions. There is an absolute terminal stop: after the answer to the final question (`Frage {{Total}} von {{Total}}`), go straight to the Performance Summary — never ask beyond `{{Total}}`. A 🟠 P1 **Question Difficulty MUST Match Knowledge Level** section ties the chosen level `{{Level}}` to the *cognitive demand* of every question (Bloom-style: L1 recall → L3 apply → L5 evaluate/synthesize), with a per-question self-check ("could a user one level lower answer this just as easily?") and a hard ban on bare definition/recall questions at Level 4–5 — without this the model collapses every level to easy recall, so a Level-5 test feels like Level 1. `{{Level}}`/`{{Total}}`/`{{N}}`/`{{Topic}}` are model-filled narrative placeholders (only `SUPPORT_EMAIL`, `POSSIBLE_CITATIONS_PROMPT`, and `language_locale` are code-substituted in `render_chatbot_prompt`). These bots run `gpt-5.4-mini` at `reasoning_effort="high"` (set per bot in `config.py`; `registry.ts` `reasoningEffort` metadata mirrors it). Keep the gate, the visible counter, the level-difficulty rubric, and the high effort in sync across all tutor prompt variants (lemon/bensberg/internal, demo/fbn/moodle/steuertipps/publishone, and the compact knoll).
- Tutor-mode closed-choice prompts (mode, topic, knowledge level, question count, in-flow yes/no) render as interactive buttons via a hidden marker the model appends at the END of a message: `[[CHOICES kind=mode|topic|level|count|generic allowOther=0|1]]Label | Label[[/CHOICES]]`. It is parsed/stripped by `app/frontend/src/chatbots/shared/answer/optionMarkers.ts` and rendered by shared `AnswerOptions.tsx` inside `ChatbotAnswer` (same hidden-marker pattern as HYROX `assessmentMarkers.ts`). The marker stays in stored content (replays into history) but is display-stripped. `mode`/`level`/`count` carry an EMPTY body — the frontend supplies localized labels (and level descriptions) from each bot's `options.*` i18n keys (de/en/nl); `topic`/`generic` carry pipe-separated labels in the body. `level` and `count` are fixed sets and NEVER render an "Andere Option" — `parseChoiceMarker` force-disables `allowOther` for them regardless of what the model emits. Clicking sends the value as a normal request, but the user bubble is suppressed (`isOptionSelectionTurn`) and the choice is shown locked inside the assistant's option group (derived from `answers[i+1][0]`, survives history restore); "Andere Option" focuses the chat input for a free-typed answer (which still shows a normal user bubble); on send, that free-typed value is recorded in `pendingOptionSelection` so the "Other" highlight survives the `answers`↔`streamedAnswers` render switch (which remounts `AnswerOptions` and would otherwise drop its local optimistic-selected state until the response arrives). The welcome mode choice is the marker appended in each tutor `Chat.tsx` to `initialAssistantMessageContent` (the synthetic welcome pair is stripped before any backend call). A separate hidden bubble-split marker `[[SPLIT]]` (parsed by `splitBubbleSegments`, display-stripped) renders everything after it as a NEW assistant bubble inside the SAME stored message. The turn that evaluates the user's **answer** to the FINAL question (never the turn that asks it — asking `Frage {{Total}}` still stops and waits) emits the ending in ONE turn (no extra user input): the final-answer feedback, then `[[SPLIT]]`, the Performance Summary, then `[[SPLIT]]`, the closing "anderes Thema oder Q&A?" question ending with a `[[CHOICES kind=mode]]` button group (Tutor/Q&A) exactly like the welcome — three stacked bubbles. `ChatbotAnswer` renders the first segment in the main card and each extra segment as its own card, placing the option group on the LAST one; the extra cards are wrapped in a `.answerBubbleGroup` column (the `.chatMessageGpt` row is flex, so without it the bubbles tile side-by-side — single-bubble messages use `display:contents` so their layout is unchanged). The end-of-test re-offer is `kind=mode` (not `generic`); its Q&A button label is "I have a question"/"Ich habe eine Frage"/"Ik heb een vraag" (not "Ask a question"/"Fragen stellen", which the model misread as a tutor request). Keep the marker grammar (`[[CHOICES …]]` + `[[SPLIT]]`), the per-bot `options.*` i18n, the welcome marker, and the "🟠 P1 — INTERACTIVE OPTION MARKERS" prompt section in lockstep across all tutor bots; the HYROX assessment Start/Continue/Retry buttons likewise suppress their control-message user bubble (`isControlMessage`).
- The `hyrox-assessment` bot (HYROX Level 2 "Managing Performance" certificate) is NOT a tutor/RAG bot: it runs a backend-driven, stateless **module-by-module** knowledge assessment (no retrieval — `chatreadretrieveread._is_hyrox_assessment_chatbot` skips search). 52 questions in `app/backend/approaches/chatbots/hyrox_assessment/questions.py` (auto-generated; see Adding Data) are grouped into 13 modules (`M1`–`M6`, `M7.1`–`M7.4`, `M8`–`M10`), asked in fixed order; **all** questions of a module are asked, each module is scored separately at an **80% threshold**, a failed module is **retaken in full** until passed, and only after the **final** module passes is the run complete. State is reconstructed every turn (`results.py:derive_turn_state`) from hidden markers replayed in history: `[[PLAN]]` (run anchor), `[[MODULE m=.. attempt=..]]` (module-attempt anchor — its window scopes the current attempt's scores so a failed attempt never pollutes the retake), `[[ASKED q=K]]`, the model's `[[SCORE q=K points=".." max=Y mod="M.."]]` (per-key-point 0/1 verdict only; backend computes `awarded=min(sum,max_pts)`), `[[MODPASS m=..]]`/`[[MODFAIL m=..]]` (module-boundary signals that drive the frontend Continue/Retry buttons), `[[BREAK]]` (display bubble split), and — **only on the final module's pass** — `[[PROGRESS value=100]]` (→ `lemon://save_progress`, the LMS completion; never per-module) + `[[DONE]]` (terminal). The model writes NO numbers/headings/transitions/visible question text and **authors no summary**; the backend renders the module heading, per-module "Question N of M" counter, scores, module result, transitions, and the entire end sequence — including a **deterministic module-by-module summary** (`render_module_summary`: every module in fixed order with a ≥90%-or-revisit band, plus the key-point topics the learner earned (Strengths) vs missed (Worth revisiting) via `module_topic_breakdown`, built from the reconstructed per-key-point verdicts — naming missed key points is intentional end-of-assessment guidance after all modules are passed). The final question is handled exactly like any other last-question-of-a-module (brief feedback + `[[SCORE]]` only): never give it special "write the take-aways" instructions, or the model emits the ending early on a partial first answer and the correction loop stalls. `[[SUMMARY]]` is **legacy** — no longer model-emitted or used for logic; it is kept in the Python `ANY_MARKER_RE`/`SUMMARY_TOKEN_RE` and the TS `ASSESSMENT_MARKER_RE` only to display-hide it from old stored sessions and to cut any stray take-aways a misbehaving model still writes. Per-question grading keeps the one-revision rule (the premature-partial-score guard). The Python marker set in `results.py`/`sampleprompt.py` and the TS set in `components/Answer/assessmentMarkers.ts` (+ `pages/chat/Chat.tsx` boundary buttons) must stay in lockstep; `questions.py` has `len(key_points) == max_pts` for every question (one point per key point). The bot runs English-only (`Chat.tsx` hardcodes `HYROX_ASSESSMENT_LANGUAGE="en"`); de/nl locale strings are kept for parity.

## Adding Data

- Put new source files in `data/`, then ingest with `scripts/prepdocs.sh` or `scripts/prepdocs.ps1`.
- With generic `prepdocs --category <name>`, source blobs go under `content/<name>/` and indexed `storageUrl` values point to that category-specific path.
- For FHG wrapped study exports such as `data/fhg.json` or `data/fhg_alle_studien_YYYYMMDD.json`, use `python app/backend/prep_fhg_json.py <path-to-json>`.
- For HYROX Academy Level 1 exports such as `data/HYROX_Level_1.json`, use `python app/backend/prep_hyrox_json.py <path-to-json>`; records are indexed into category `lemon`.
- The HYROX Level 2 assessment question bank is NOT indexed — it is compiled into the prompt. Regenerate it from the workbook with `python app/backend/prep_hyrox_assessment_questions.py` (reads the master `Module 1` tab of `hyrox-files/HYROX_L2_QuestionBank_Final.xlsx`, the only tab covering all 52 questions; the per-module tabs are superseded drafts). It rewrites `app/backend/approaches/chatbots/hyrox_assessment/questions.py` (data + helpers) and asserts `len(key_points)==max_pts` per question and that module sums match the workbook. `hyrox-files/HYROX_L2_Assessment_Knowledge.xml` is a committed reference asset only — it is intentionally NOT wired into grading.
- The snap.de website (category `snap`) has a full end-to-end refresh script: `app/backend/refresh_snap.py`. Run it with the backend venv while azd-logged-in; it (1) change-checks via a WP-REST watermark in `data/snap.state.json` (`--force` to bypass, `--check-only` to just report), (2) re-scrapes `data/snap.json` (markdown via `scripts/scrape_snap.py`), then (3) deletes category `snap` and re-indexes through the custom snap parser (`delete_category_data.py` + `prepdocs.py`). It scrapes before deleting and writes the watermark only on success, so a failed run is safely retried. Automation (webhook/schedule) is intentionally deferred — it is a manual command for now.
- Moodle and PublishOne XML feeds are auto-indexed from `content/nerilio/Nerilio-Moodle/` and `content/nerilio/Nerilio-PublishOne/`, mirrored into `content/moodle/` or `content/publishone/`, and indexed into Azure AI Search with categories `moodle` and `publishone`.
- FHG JSON feeds are auto-indexed from `content/nerilio/Nerilio-fhg/`, mirrored into `content/fhg/`, and indexed into Azure AI Search with category `fhg` using the FHG JSON parser.
- The feed parser maps outer `<document id="...">` to `sourcepage`, direct `<naam>` to `title`, `url` to the external PublishOne document URL, structured document text into `content`, and extra metadata into `tags`; citations use first-class `title` and `url`.
- Deleting one of those source XML blobs must remove the mirrored target blob and matching indexed documents.
- To purge one category from both Azure AI Search and blob storage without re-ingesting, run
  `python app/backend/delete_category_data.py <category>`; it deletes search docs with
  `category=<category>` and blobs under `content/<category>/`. To purge only the search index, run
  `python app/backend/delete_documents_by_category.py <category>`.

## Adding A Chatbot

Frontend:

1. Create `app/frontend/src/chatbots/<chatbot_name>/`.
2. Export `name`, `LayoutWrapper`, `Chat`, `NoPage`, and `i18n` from `app/frontend/src/chatbots/<chatbot_name>/index.ts`.
3. Register it in `app/frontend/src/chatbots/registry.ts`. The entry must also supply `ChatbotMetadata` shown on the chatbot directory cards: `llm`, optional `reasoningEffort` (only when the model is in the backend `GPT_REASONING_MODELS` map), `mode` (`"qna"` for Q&A-only prompts, `"tutor-qna"` for dual-mode prompts), and `agenticRetrievalDefault` (`true` only when the chatbot's `Chat.tsx` auto-checks the agentic-retrieval toggle, e.g. `lemon`'s `setUseAgenticRetrieval(config.showAgenticRetrievalOption)`). For chatbots whose `config.py` leaves `chatgpt_model`/`reasoning_effort` unset, mirror the values from the deployment `.env` (currently `.azure/agentic-retrieval-nerilio/.env` is the active one).
4. Add its theme in `app/frontend/src/chatbots/shared/theme/chatbotThemes.ts`; prefer a single `primary` color unless overrides are needed.
5. Add chatbot-specific i18n setup and `en`, `de`, `nl` translation files.
6. Prefer re-exporting shared `Example` and building answers with `app/frontend/src/chatbots/shared/answer/createBotAnswer.tsx`.
7. If chatbot auth is needed, gate it in that chatbot's `layoutWrapper.tsx` and standalone `NoPage` route.

Backend, always required for routing:

- Add the chatbot name to `KNOWN_CHATBOT_NAMES` in `app/backend/app.py`. The `/<chatbot_name>` route gates against this set and redirects unknown names to `/`, so a bot missing here loads as a redirect to the home page even though the frontend route exists.

Backend, only when custom behavior is needed:

1. Add `sampleprompt.py` under `app/backend/approaches/chatbots/<chatbot_name>/` for default prompt variables.
2. Add `contentfilter.py` only if the default localized copy is insufficient.
3. Add `config.py` for different model, deployment, reasoning effort, prompt-time values, prompt mode, or citation target.

`internal` is the exception: it has a frontend shell but no active backend `sampleprompt.py` or upload manager at runtime. Internal behavior routes through the selected `source_chatbot`.

## Adding An azd Variable

When adding an azd environment variable, update:

1. `infra/main.parameters.json`
2. `infra/main.bicep`
3. `.azdo/pipelines/azure-dev.yml`
4. `.github/workflows/azure-dev.yml`

If the value is optional and goes into Azure Container Apps secrets, omit both the secret and matching `envSecrets` entry when empty. Also update `app/backend/prepdocs.py` or `app/backend/app.py` if ingestion or runtime code needs the variable.

## Adding Developer Settings

Frontend:

- Add the setting to `app/frontend/src/api/models.ts`.
- Add the UI element in the relevant chatbot `components/Settings/Settings.tsx`.
- Add translations for all supported locales of that chatbot.
- Pass the setting through the relevant chatbot `pages/chat/Chat.tsx`.

Backend:

- Read the override in `app/backend/approaches/chatreadretrieveread.py`.
- Use `/config` from `app/backend/app.py` for frontend capability metadata.
- Model-selection config uses `availableChatModels`, `defaultChatModel`, and `reasoningCapableChatModels`. If Azure deployment names differ from model IDs, use `AZURE_OPENAI_CHAT_MODEL_DEPLOYMENTS` as a JSON object.

## Tests And Checks

- Use pytest for backend and integration tests. Activate the virtual environment first.
- UI changes need Playwright e2e coverage where behavior matters. Build the frontend before e2e tests with `npm run build` in `app/frontend`.
- API endpoints need app integration tests, usually in `tests/test_app.py`.
- Functions and methods need focused unit tests.
- Use mocks from `tests/conftest.py`; prefer HTTP/request-level mocking when practical.
- Changing chatbot backend config loading requires tests for `app/backend/approaches/chatbot_config_registry.py` plus startup behavior for per-bot `ChatReadRetrieveReadApproach` overrides.
- Changing shared chatbot UI wrappers such as `createBotAnswer.tsx` or shared `Example` needs e2e coverage for bot-specific behavior that still matters, such as `rak` user-scoped citations or wordmark answer branding for `publishone`, `sartorius`, and `steuertipps`.
- For coverage, run `pytest --cov --cov-report=annotate:cov_annotate`; inspect generated files and add tests for lines marked with `!`.
- Type-check application code and scripts with `ty check`.
- Backend dependency upgrades use `cd app/backend && uv pip compile requirements.in -o requirements.txt --python-version 3.10 --upgrade-package <package-name>`.

## Deployment

- `azd up` provisions Azure resources and deploys application code.
- Windows deployments also need Azure CLI (`az`) on `PATH` because `scripts/setup_moodle_delete_event_subscription.py` configures Event Grid subscriptions after deploy.
- Use `azd provision` for Bicep-only changes.
- Use `azd deploy` for app-code-only changes.
- For individual cloud ingestion functions, use commands such as `azd deploy document-extractor`, `azd deploy figure-processor`, or `azd deploy text-processor`.
- Azure Container Apps custom-domain portal bindings can be overwritten by provisioning. Preserve existing binding with `SERVICE_BACKEND_RESOURCE_EXISTS`, or manage it with `AZURE_CONTAINER_APP_CUSTOM_DOMAIN` and `AZURE_CONTAINER_APP_CUSTOM_DOMAIN_CERTIFICATE_ID`.
- `AZURE_SPEECH_DISABLE_LOCAL_AUTH=false` keeps Speech "Allow API key based authentication" enabled across `azd up`; set it to `true` only for intentional Microsoft Entra ID-only access.

## Style

- Python code in this repo does not use leading single underscores for private methods or variables.
- Keep changes narrowly scoped and aligned with existing patterns.
- When sending pull requests, follow `PULL_REQUEST_TEMPLATE.md`.
