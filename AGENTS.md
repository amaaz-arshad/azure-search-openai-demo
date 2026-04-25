# graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:

- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- After modifying code files in this session, run `graphify update .` to keep the graph current (AST-only, no API cost)

# Instructions for Coding Agents

Do not make any changes until you have 95% confidence in what you need to build. Ask me follow-up questions until you reach that confidence.

This file captures repo-specific workflow, invariants, and change playbooks for the Azure Search and OpenAI demo application. Use `graphify-out/` for detailed structure discovery; keep this file focused on entrypoints, contracts, and required process rather than a file-by-file code index.

Always keep this file up to date with any changes to the codebase or development process.
If necessary, edit this file to ensure it accurately reflects the current state of the project.

## Codebase map

Use `graphify-out/GRAPH_REPORT.md` as the primary structural map for this repo. If `graphify-out/wiki/index.md` exists, prefer that for deeper navigation rather than expanding this file into another file-by-file layout dump.

High-signal entrypoints:

* `app/start.ps1`: local bootstrap for azd env loading, `app/.venv`, dependency restore, frontend build, and Quart startup.
* `app/backend/app.py`: main Quart app and backend route surface, including `/config`, chatbot upload routes, managed upload routes, `public-test` auth/admin routes, and internal admin auth/prompt routes.
* `app/backend/approaches/`: shared RAG logic, prompt rendering, chatbot backend config discovery, and per-bot model/prompt/citation behavior.
* `app/backend/prepdocslib/`: ingestion, parsers, upload/indexing flows, Azure AI Search schema writes, and feed-specific section builders.
* `app/functions/`: Azure Functions copies of the shared ingestion pipeline plus `moodle_auto_indexer`; refresh with `python scripts/copy_prepdocslib.py` after changing shared ingestion code.
* `app/frontend/src/index.tsx`: router for `/`, `/<chatbot_name>`, chatbot catch-all `NoPage`, and internal tool routes.
* `app/frontend/src/chatbots/registry.ts`: chatbot registration and route wiring.
* `app/frontend/src/chatbots/shared/`: shared answer, example, theme, speech, disclaimer, basic-auth, and `NoPage` building blocks reused across bots.
* `app/frontend/src/pages/`: internal tool pages such as chatbot directory, upload manager, prompt manager, and Free Bot user admin.
* `infra/main.bicep` and `infra/main.parameters.json`: Azure provisioning and azd env-var wiring.
* `scripts/setup_moodle_delete_event_subscription.py`: post-deploy Event Grid sync setup for Moodle and PublishOne feed automation; requires Azure CLI on `PATH`.
* `docker-compose.openlit.yml`, `otel-collector-config.yaml`, `otel-collector-config.aci.yaml`, and `aci-openlit.example.yaml`: local/cloud OpenLIT stack, persistence wiring, and LLM-only trace filtering.
* `tests/`: e2e, app integration, and unit tests.

## Critical contracts

Keep `AGENTS.md` focused on workflow, invariants, and change guides. Do not rebuild a detailed code inventory here when `graphify-out/` already provides that navigation layer.

* Frontend chatbot routing is `/<chatbot_name>` inside each bot's `LayoutWrapper`, while `/<chatbot_name>/*` renders that bot's `NoPage` outside the layout so the fallback page appears without chatbot navbar/header chrome.
* Chatbots that use frontend basic auth must guard both `LayoutWrapper` and the standalone `NoPage` route so `/<chatbot_name>/*` cannot bypass the auth gate. `/internal` now follows this pattern too.
* Backend `/config` is the frontend capability contract for model selection and reasoning effort. When models diverge, update backend metadata instead of hardcoding frontend assumptions.
* `OPENLIT_ENDPOINT` only points the app at an already-running OpenLIT backend. The repo's `azd up` flow does not provision or repair the standalone OpenLIT Container App.
* In this environment, Azure Files SMB is not a safe data volume for OpenLIT's bundled ClickHouse. Mounting `/var/lib/clickhouse` there caused insert and migration failures with `Operation not permitted`, so new requests stopped appearing even though `/v1/traces` was still being posted.
* The currently working OpenLIT Container App setup keeps both `clickhousedata` and `openlitdata` on `EmptyDir`, with only config volumes on Azure Files. That means requests appear in the dashboard again, but history is still non-persistent across replica recreation.
* `/internal` is a router shell, not its own retrieval category. Internal requests must carry `context.overrides.source_chatbot`; backend validation then derives the effective bot identity, prompt, and `include_category` from that selected source bot.
* `/config` now includes `internalSourceBots` for the `/internal` source-bot dropdown. Do not reintroduce `All` for internal; only one real source bot can be active per internal session.
* Internal chat history sessions must persist `source_chatbot` metadata. Legacy internal sessions without that metadata are intentionally hidden and non-restorable.
* Internal citations resolve against the selected source bot's content path, while the visible `/internal` shell branding stays fixed as `Internal Bot`.
* Backend startup auto-discovers optional chatbot backend modules under `app/backend/approaches/chatbots/<chatbot_name>/`; do not add manual registration unless the code path truly requires it.
* Shared internal admin auth gates `/chatbots`, `/upload-files`, `/public-test-users`, and `/manage-prompts`; keep frontend and backend route names aligned.
* `public-test` still keeps some legacy internal identifiers for compatibility even though the public branding is now "Free Bot"; verify compatibility before renaming storage/auth/history namespaces.
* Frontend chatbot locale support is standardized to `en`, `de`, and `nl`; do not add or keep extra chatbot locale folders unless the entire bot set is intentionally expanded together.
* If a chatbot uses the generic app mark on its empty state or similar generic surfaces, import the shared `app/frontend/src/assets/applogo.svg` instead of keeping duplicate per-bot `applogo.svg` assets.
* If you change shared ingestion logic in `app/backend/prepdocslib/`, refresh the synchronized copies under `app/functions/`.
* For Moodle/PublishOne XML feed automation, preserve both the blob-copy/index flow and the post-deploy Event Grid subscription script.

## Adding new data

New files should be added to the `data` folder, and then either run scripts/prepdocs.sh or scripts/prepdocs.ps1 to ingest the data. When `--category <name>` is passed to the generic `prepdocs` flow, the original source blobs are stored under `content/<name>/` and the indexed `storageUrl` values point to that category-specific blob path.
For wrapped FHG studies exports such as `data/fhg.json` or `data/fhg_alle_studien_YYYYMMDD.json`, use `python app/backend/prep_fhg_json.py <path-to-json>` instead of the generic `prepdocs` flow so that each `documents[]` entry is chunked as a study record, the indexed `content` contains the study body plus retrieval-relevant metadata, the raw dataset file is uploaded under `content/fhg/`, first-class `title`/`url`/`tags` fields are populated, and embeddings are created for every chunk.
For HYROX Academy Level 1 exports such as `data/HYROX_Level_1.json`, use `python app/backend/prep_hyrox_json.py <path-to-json>` so the records are indexed into category `lemon` with `lms_id` as `sourcepage`, first-class `title`/`url`/`tags`, raw `content` chunks only, and the raw dataset uploaded under `content/lemon/`.
For the Moodle and PublishOne chatbots' externally synced XML feeds, blobs dropped into `content/nerilio/Nerilio-Moodle/` or `content/nerilio/Nerilio-PublishOne/` are picked up automatically by the `moodle_auto_indexer` Function App, copied into `content/moodle/` or `content/publishone/`, and indexed into Azure AI Search with categories `moodle` and `publishone` so the chatbot `storageUrl` values point at the copied chatbot-owned blobs instead of the external drop folders. The feed parser maps each outer `<document id="...">` to `sourcepage`, maps direct `<naam>` to `title`, maps `url` to `https://amsterdam.publishone.nl/document/<document-id>/content`, renders the logical document subtree into structured plain text inside `content`, preserves folder-level metadata and inline link/image targets there, and stores additional document and direct meta metadata in `tags`. Moodle and PublishOne citations use those first-class `title` and `url` fields so the chat UI shows the document title while linking out to the external PublishOne document URL. When one of those source XML blobs is deleted, the same automation removes the mirrored target blob and the corresponding indexed documents as well.
To purge indexed content for a single category without re-ingesting, use `python app/backend/delete_documents_by_category.py <category>`.

## Adding a new chatbot UI

Frontend chatbot UIs are routed by path segment (`/<chatbot_name>`). To add a new chatbot:

1. Create `app/frontend/src/chatbots/<chatbot_name>/` with that chatbot's pages/components/layout.
1. Export its definition (`name`, `LayoutWrapper`, `Chat`, `NoPage`, `i18n`) from `app/frontend/src/chatbots/<chatbot_name>/index.ts`.
1. Register it in `app/frontend/src/chatbots/registry.ts`.
1. Add that chatbot's theme entry in `app/frontend/src/chatbots/shared/theme/chatbotThemes.ts`. Usually a single `primary` color is enough; only add overrides if the auto-derived theme needs adjustment.
1. Add chatbot-specific i18n setup in `app/frontend/src/chatbots/<chatbot_name>/i18n/` and chatbot-specific translations in `app/frontend/src/chatbots/<chatbot_name>/locales/`.
1. Prefer re-exporting `app/frontend/src/chatbots/shared/components/Example/Example.tsx` for example cards unless the chatbot needs special example-card behavior.
1. Prefer building `components/Answer/Answer.tsx` from `app/frontend/src/chatbots/shared/answer/createBotAnswer.tsx`; only keep a handwritten wrapper when the chatbot needs custom citation-path handling or branding options that differ from the factory defaults.
1. If chatbot-specific auth is needed (for example, a basic username/password page), implement the gate in that chatbot's `layoutWrapper.tsx` so it applies only to that chatbot route.

If the chatbot also needs backend-specific behavior, add the matching backend modules under `app/backend/approaches/chatbots/<chatbot_name>/`:

1. Add `sampleprompt.py` for chatbot-specific prompt variables. Keep it as the default raw prompt; `/manage-prompts` saves runtime overrides elsewhere and falls back to this file when no override exists.
1. Add `contentfilter.py` only if the default localized content-filter copy is not enough.
1. Add `config.py` when the bot needs a different `chatgpt_model`, `chatgpt_deployment`, `reasoning_effort`, prompt-time values such as `support_email`, a specific `prompt_mode`, or citation target. Startup auto-discovers these files; you do not need to register them manually anywhere else.

`internal` is the exception: it keeps its own frontend shell, but it does not use an active backend `sampleprompt.py` or upload manager at runtime. Internal behavior is routed through the selected `source_chatbot` instead.

## Adding a new azd environment variable

An azd environment variable is stored by the azd CLI for each environment. It is passed to the "azd up" command and can configure both provisioning options and application settings.
When adding new azd environment variables, update:

1. infra/main.parameters.json : Add the new parameter with a Bicep-friendly variable name and map to the new environment variable
1. infra/main.bicep: Add the new Bicep parameter at the top, and add it to `appEnvVariables`, App Service app settings, or Container Apps secrets/envSecrets as appropriate for whether the value is public config or a secret. If the value is optional and goes into Azure Container Apps secrets, conditionally omit the secret and matching `envSecrets` entry when the value is empty.
1. .azdo/pipelines/azure-dev.yml: Add the new environment variable under `env` section
1. .github/workflows/azure-dev.yml: Add the new environment variable under `env` section

You may also need to update:

1. app/backend/prepdocs.py: If the variable is used in the ingestion script, retrieve it from environment variables here. Not always needed.
1. app/backend/app.py: If the variable is used in the backend application, retrieve it from environment variables in setup_clients() function. Not always needed.

## Adding a new setting to "Developer Settings" in RAG app

When adding a new developer setting, update:

* frontend:
  * app/frontend/src/api/models.ts : Add to ChatAppRequestOverrides
  * app/frontend/src/chatbots/<chatbot_name>/components/Settings/Settings.tsx : Add a UI element for the setting
  * app/frontend/src/chatbots/<chatbot_name>/locales/*/translation.json: Add a translation for the setting label/tooltip for all languages of that chatbot
  * app/frontend/src/chatbots/<chatbot_name>/pages/chat/Chat.tsx: Add the setting to the component, pass it to Settings

* backend:
  * app/backend/approaches/chatreadretrieveread.py :  Retrieve from overrides parameter
  * app/backend/app.py: Some settings may need to be sent down in the /config route. Model-selection settings now use `availableChatModels`, `defaultChatModel`, and `reasoningCapableChatModels` from `/config`. When Azure deployment names do not match the model ids, override the selector mapping with `AZURE_OPENAI_CHAT_MODEL_DEPLOYMENTS` as a JSON object.

## When adding tests for a new feature

All tests are in the `tests` folder and use the pytest framework.
There are three styles of tests:

* e2e tests: These use playwright to run the app in a browser and test the UI end-to-end. They are in e2e.py and they mock the backend using the snapshots from the app tests. (Before running e2e tests, make sure to run `npm run build` in app/frontend first to build the frontend code.)
* app integration tests: Mostly in test_app.py, these test the app's API endpoints and use mocks for services like Azure OpenAI and Azure Search.
* unit tests: The rest of the tests are unit tests that test individual functions and methods. They are in test_*.py files.

When adding a new feature, add tests for it in the appropriate file.
If the feature is a UI element, add an e2e test for it.
If it is an API endpoint, add an app integration test for it.
If it is a function or method, add a unit test for it.
Use mocks from tests/conftest.py to mock external services. Prefer mocking at the HTTP/requests level when possible.
When changing chatbot backend config loading, add or update unit tests for `app/backend/approaches/chatbot_config_registry.py` and app-startup tests that verify per-bot `ChatReadRetrieveReadApproach` overrides are created only for bots whose model, deployment, or reasoning effort differs from the global defaults.
When changing shared chatbot UI wrappers such as `createBotAnswer.tsx` or the shared `Example` component, add e2e coverage for the bot-specific behavior that still matters after deduplication, for example user-scoped citation URLs (`rak`) or wordmark answer branding (`publishone`, `sartorius`, `steuertipps`).

When you're running tests, make sure you activate the .venv virtual environment first:

```shell
source .venv/bin/activate
```

To check for coverage, run the following command:

```shell
pytest --cov --cov-report=annotate:cov_annotate
```

Open the cov_annotate directory to view the annotated source code. There will be one file per source file. If a file has 100% source coverage, it means all lines are covered by tests, so you do not need to open the file.

For each file that has less than 100% test coverage, find the matching file in cov_annotate and review the file.

If a line starts with a ! (exclamation mark), it means that the line is not covered by tests. Add tests to cover the missing lines.

## Sending pull requests

When sending pull requests, make sure to follow the PULL_REQUEST_TEMPLATE.md format.

## Upgrading dependencies

To upgrade a particular package in the backend, use the following command, replacing `<package-name>` with the name of the package you want to upgrade:

```shell
cd app/backend && uv pip compile requirements.in -o requirements.txt --python-version 3.10 --upgrade-package package-name
```

## Checking Python type hints

To check Python type hints, use the following command:

```shell
ty check
```

Note that we do not currently enforce type hints in the tests folder, as it would require adding a lot of `# type: ignore` comments to the existing tests.
We only enforce type hints in the main application code and scripts.

## Python code style

Do not use single underscores in front of "private" methods or variables in Python code. We do not follow that convention in this codebase, since this is an application and not a library.

## Deploying the application

To deploy the application, use the `azd` CLI tool. Make sure you have the latest version of the `azd` CLI installed. Then, run the following command from the root of the repository:

```shell
azd up
```

That command will BOTH provision the Azure resources AND deploy the application code.
On this repo, Windows deployments also expect Azure CLI (`az`) to be installed and available on `PATH`, because the `moodle_auto_indexer` post-deploy hook configures Event Grid subscriptions through `scripts/setup_moodle_delete_event_subscription.py`.

If you only changed the Bicep templates and want to re-provision the Azure resources, run:

```shell
azd provision
```

If you only changed the application code and want to re-deploy the code, run:

```shell
azd deploy
```

If you are using cloud ingestion and only want to deploy individual functions, run the necessary deploy commands, for example:

```shell
azd deploy document-extractor
azd deploy figure-processor
azd deploy text-processor
```

For Azure Container Apps deployments, manual portal custom-domain bindings can be overwritten by provisioning updates. To keep the backend Container App domain stable through `azd up`, either rely on the preserved existing binding when `SERVICE_BACKEND_RESOURCE_EXISTS` is present, or explicitly set `AZURE_CONTAINER_APP_CUSTOM_DOMAIN` plus `AZURE_CONTAINER_APP_CUSTOM_DOMAIN_CERTIFICATE_ID` so the ingress custom domain is managed in IaC.

For Azure Speech resources, `AZURE_SPEECH_DISABLE_LOCAL_AUTH=false` keeps portal setting "Allow API key based authentication" enabled across `azd up`. Set it to `true` only if you intentionally want Microsoft Entra ID-only access.
