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
- Shared internal admin auth gates `/chatbots`, `/upload-files`, `/public-test-users`, and `/manage-prompts`; keep frontend and backend route names aligned.
- `public-test` keeps some legacy internal identifiers for compatibility even though public branding is "Free Bot". Verify compatibility before renaming storage, auth, or history namespaces.
- Frontend chatbot locales are standardized to `en`, `de`, and `nl`. Do not add extra locale folders unless expanding the entire bot set intentionally.
- Generic app marks should import `app/frontend/src/assets/applogo.svg`; avoid duplicate per-bot `applogo.svg` assets.
- If shared ingestion logic changes under `app/backend/prepdocslib/`, refresh synchronized copies under `app/functions/` with `python scripts/copy_prepdocslib.py`.
- Moodle/PublishOne XML feed automation must preserve both blob-copy/index behavior and the post-deploy Event Grid subscription script.
- `OPENLIT_ENDPOINT` points at an already-running OpenLIT backend. `azd up` does not provision or repair the standalone OpenLIT Container App.
- Azure Files SMB is not safe for OpenLIT ClickHouse data here. The known-working Container App setup uses `EmptyDir` for `clickhousedata` and `openlitdata`, with only config volumes on Azure Files; request history is non-persistent across replica recreation.

## Adding Data

- Put new source files in `data/`, then ingest with `scripts/prepdocs.sh` or `scripts/prepdocs.ps1`.
- With generic `prepdocs --category <name>`, source blobs go under `content/<name>/` and indexed `storageUrl` values point to that category-specific path.
- For FHG wrapped study exports such as `data/fhg.json` or `data/fhg_alle_studien_YYYYMMDD.json`, use `python app/backend/prep_fhg_json.py <path-to-json>`.
- For HYROX Academy Level 1 exports such as `data/HYROX_Level_1.json`, use `python app/backend/prep_hyrox_json.py <path-to-json>`; records are indexed into category `lemon`.
- Moodle and PublishOne XML feeds are auto-indexed from `content/nerilio/Nerilio-Moodle/` and `content/nerilio/Nerilio-PublishOne/`, mirrored into `content/moodle/` or `content/publishone/`, and indexed into Azure AI Search with categories `moodle` and `publishone`.
- The feed parser maps outer `<document id="...">` to `sourcepage`, direct `<naam>` to `title`, `url` to the external PublishOne document URL, structured document text into `content`, and extra metadata into `tags`; citations use first-class `title` and `url`.
- Deleting one of those source XML blobs must remove the mirrored target blob and matching indexed documents.
- To purge one indexed category without re-ingesting, run `python app/backend/delete_documents_by_category.py <category>`.
- LLM Wiki compiled Markdown lives in blob storage under `content/__llm_wiki__/<chatbot>/wiki/`. To compile raw source blobs already in Azure Storage, run `python app/backend/compile_llm_wiki.py --chatbot <chatbot>`. To compile raw files from this repo's `content/<chatbot>/` folders and upload the resulting wiki to blob storage, add `--local-content-root content --overwrite`. Very large raw files may compile into multiple `sources/*-part-NNN.md` pages.

## Adding A Chatbot

Frontend:

1. Create `app/frontend/src/chatbots/<chatbot_name>/`.
2. Export `name`, `LayoutWrapper`, `Chat`, `NoPage`, and `i18n` from `app/frontend/src/chatbots/<chatbot_name>/index.ts`.
3. Register it in `app/frontend/src/chatbots/registry.ts`. The entry must also supply `ChatbotMetadata` shown on the chatbot directory cards: `llm`, optional `reasoningEffort` (only when the model is in the backend `GPT_REASONING_MODELS` map), `mode` (`"qna"` for Q&A-only prompts, `"tutor-qna"` for dual-mode prompts), and `agenticRetrievalDefault` (`true` only when the chatbot's `Chat.tsx` auto-checks the agentic-retrieval toggle, e.g. `lemon`'s `setUseAgenticRetrieval(config.showAgenticRetrievalOption)`). For chatbots whose `config.py` leaves `chatgpt_model`/`reasoning_effort` unset, mirror the values from the deployment `.env` (currently `.azure/agentic-retrieval-nerilio/.env` is the active one).
4. Add its theme in `app/frontend/src/chatbots/shared/theme/chatbotThemes.ts`; prefer a single `primary` color unless overrides are needed.
5. Add chatbot-specific i18n setup and `en`, `de`, `nl` translation files.
6. Prefer re-exporting shared `Example` and building answers with `app/frontend/src/chatbots/shared/answer/createBotAnswer.tsx`.
7. If chatbot auth is needed, gate it in that chatbot's `layoutWrapper.tsx` and standalone `NoPage` route.

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
