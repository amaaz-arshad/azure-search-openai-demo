# Instructions for Coding Agents

This file contains instructions for developers working on the Azure Search and OpenAI demo application. It covers the overall code layout, how to add new data, how to add new azd environment variables, how to add new developer settings, and how to add tests for new features.

Always keep this file up to date with any changes to the codebase or development process.
If necessary, edit this file to ensure it accurately reflects the current state of the project.

## Overall code layout

* app: Contains the main application code, including frontend and backend.
    * app/backend: Contains the Python backend code, written with Quart framework.
      * app/backend/core/publictestauth.py: Persistent auth store for the `public-test` chatbot. It stores verified account records and pending signup verification state as JSON blobs in a dedicated private container on the main storage account, hashes passwords and one-time verification codes with PBKDF2-HMAC-SHA256, sends signup verification emails through configured SMTP settings, and issues signed cookie-based sessions. It prefers `AZURE_SERVER_APP_SECRET` for session signing and otherwise persists a shared fallback session secret in blob storage so all Container App replicas can validate the same cookies.
      * app/backend/approaches: Contains the different approaches
      * app/backend/approaches/approach.py: Base class for all approaches
      * app/backend/approaches/chatreadretrieveread.py: Chat approach, includes query rewriting step first
      * app/backend/approaches/chatbot_content_filter_registry.py: Provides localized default content-filter messages plus optional chatbot-specific overrides loaded from `app/backend/approaches/chatbots/<chatbot_name>/contentfilter.py`.
      * app/backend/approaches/chatbot_prompt_registry.py: Maps chatbot names to chatbot-specific prompt modules
      * app/backend/approaches/chatbots/<chatbot_name>/sampleprompt.py: Chatbot-specific `SAMPLE_PROMPT` definitions used by `get_system_prompt_variables`. The FHG prompt assumes the frontend's initial assistant message has already been shown, so it answers the user's next message directly instead of sending a second welcome.
      * app/backend/approaches/chatbots/<chatbot_name>/contentfilter.py: Optional chatbot-specific `CONTENT_FILTER_MESSAGES` dictionaries keyed by locale/language code for overriding the default OpenAI content-filter error text.
      * app/backend/approaches/promptmanager.py: Manages loading and rendering of Jinja2 prompt templates
      * app/backend/approaches/prompts/query_rewrite.system.jinja2: Jinja2 template used to rewrite the query based off search history into a better search query
      * app/backend/approaches/prompts/chat_query_rewrite_tools.json: Tools used by the query rewriting prompt
      * app/backend/approaches/prompts/chat_answer.system.jinja2: Jinja2 template for the system message used by the Chat approach to answer questions
      * app/backend/approaches/prompts/chat_answer.user.jinja2: Jinja2 template for the user message used by the Chat approach, including sources
    * app/backend/prepdocslib: Contains the document ingestion library used by both local and cloud ingestion
      * app/backend/prepdocslib/blobmanager.py: Manages uploads to Azure Blob Storage
      * app/backend/prepdocslib/cloudingestionstrategy.py: Builds the Azure AI Search indexer and skillset for the cloud ingestion pipeline
      * app/backend/prepdocslib/csvparser.py: Parses CSV files
      * app/backend/prepdocslib/embeddings.py: Generates embeddings for text and images using Azure OpenAI
      * app/backend/prepdocslib/figureprocessor.py: Generates figure descriptions for both local ingestion and the cloud figure-processor skill
      * app/backend/prepdocslib/fileprocessor.py: Orchestrates parsing and chunking of individual files
      * app/backend/prepdocslib/filestrategy.py: Strategy helpers for local ingestion, authenticated user uploads in ADLS, and shared chatbot uploads in blob storage. `ChatbotUploadStrategy` powers the demo-style public upload flows using local parsers only, indexes uploads into the chatbot's normal category, rejects filename collisions with built-in chatbot content, stores physical upload blobs under versioned blob paths with manifest files in `.manifests/`, supports cooperative cancellation through blob-backed cancel markers in `.cancel/`, and supports per-chatbot upload rules such as allowed file extensions, maximum total PDF pages across uploaded files, and optional per-user upload scoping. `public-test` uses that per-user mode and stores uploads under `chatbot-uploads/public-test/<user-token>/uploaded-files/...`.
      * app/backend/prepdocslib/xmlparser.py: Local XML parser that preserves hierarchy, carries forward lightweight document context, and splits repeated sibling records (for example `<item>` or `<product>`) into separate retrieval-friendly sections before chunking.
      * app/backend/prepdocslib/htmlparser.py: Parses HTML files
      * app/backend/prepdocslib/integratedvectorizerstrategy.py: Strategy using Azure AI Search integrated vectorization
      * app/backend/prepdocslib/jsonparser.py: Parses JSON files
      * app/backend/prepdocslib/listfilestrategy.py: Lists files from local filesystem or Azure Data Lake
      * app/backend/prepdocslib/mediadescriber.py: Interfaces for describing images (Azure OpenAI GPT-4o, Content Understanding)
      * app/backend/prepdocslib/page.py: Data classes for pages, images, and chunks
      * app/backend/prepdocslib/parser.py: Base parser interface
      * app/backend/prepdocslib/pdfparser.py: Parses PDFs using Azure Document Intelligence or local parser
      * app/backend/prepdocslib/searchmanager.py: Manages Azure AI Search index creation and updates. The managed index schema includes `storageUrl` for source blob lookups and a filterable `user` field used by per-user chatbot upload flows such as `public-test`.
      * app/backend/prepdocslib/servicesetup.py: Shared service setup helpers for OpenAI, embeddings, blob storage, etc.
      * app/backend/prepdocslib/strategy.py: Base strategy interface for document ingestion
      * app/backend/prepdocslib/textparser.py: Parses plain text and markdown files
      * app/backend/prepdocslib/textprocessor.py: Processes text chunks for cloud ingestion (merges figures, generates embeddings)
      * app/backend/prepdocslib/textsplitter.py: Splits text into chunks using different strategies
      * app/backend/prepdocslib/fhgjson.py: FHG-specific JSON ingestion helpers that validate the wrapped dataset structure, preserve all study fields in chunk text, generate source blobs for citations, and build search-ready documents with stable IDs. In the FHG chatbot, answer citations use the indexed `storageUrl` so citation clicks open the original study URL in a new tab.
    * app/backend/delete_documents_by_category.py: Utility script that deletes all Azure AI Search documents whose `category` field matches a provided value.
    * app/backend/prep_fhg_json.py: Dedicated ingestion script for `data/fhg_alle_studien_*.json` files. It chunks each FHG study entry logically, uploads per-study source blobs for citations, generates embeddings for every indexed chunk, stores them in Azure AI Search with category `fhg`, and by default replaces existing `fhg` documents before re-indexing.
    * app/backend/app.py: The main entry point for the backend application, including SPA fallback routes for chatbot URLs like `/<chatbot_name>`, server-side redirect of unknown chatbot names back to `/`, SPA fallback for `/chatbots`, public chatbot upload routes at `/chatbot_uploads/<chatbot_name>` (currently used by the demo and public-test bots), upload cancellation at `/chatbot_uploads/<chatbot_name>/cancel/<upload_id>`, chatbot-upload content fallback in `/content/<path>`, locale-aware content-filter error handling for `/chat` and `/chat/stream` based on `context.overrides.language` or `Accept-Language`, and no-store caching headers for `index.html` responses to avoid stale frontend routing behavior. `public-test` uses dedicated backend auth endpoints at `/public-test-auth/*` for signup, email-code verification, resend, login, session lookup, and logout, plus a signed session cookie, per-user upload storage paths, and per-user search filtering.
  * app/functions: Azure Functions used for cloud ingestion custom skills (document extraction, figure processing, text processing). Each function bundles a synchronized copy of `prepdocslib`; run `python scripts/copy_prepdocslib.py` to refresh the local copies if you modify the library.
  * app/frontend: Contains the React frontend code, built with TypeScript, built with vite.
    * app/frontend/index.html: Shared Vite HTML entry document. It loads the browser-tab favicon from `app/frontend/src/assets/robo1.png`.
    * app/frontend/src/index.tsx: Frontend entry point and router setup. It resolves chatbot UI by URL path (`/<chatbot_name>`), serves a landing/error page on `/`, provides a password-gated chatbot directory at `/chatbots`, and routes unknown frontend paths back to `/`.
    * app/frontend/src/pages/ChatbotDirectory.tsx: Password-gated page listing all currently registered chatbot links.
    * app/frontend/src/chatbots/registry.ts: Registry of available chatbot UIs, including the chatbot-specific i18n instance.
    * app/frontend/src/chatbots/shared/basicauth/BasicLoginPage.tsx: Shared themed basic-auth login page used by chatbot-specific basic auth routes. It supports chatbot-specific logo frame and logo class overrides so wordmark logos can use a different treatment than square icons.
    * app/frontend/src/chatbots/shared/disclaimer: Shared dismissible chatbot disclaimer banner used in chat pages. It opens on initial chatbot load and re-opens when the in-chat login state changes from logged out to logged in.
    * app/frontend/src/chatbots/shared/speech: Shared Azure Speech browser helpers/components for chatbot mic input and low-latency TTS playback. It fetches short-lived auth tokens from `/speech/token`, uses Azure Speech SDK microphone recognition instead of the browser `SpeechRecognition` API, chooses a Firefox-safe streamed synthesis format at runtime, and includes `chatbotSpeechFeatureFlags.ts` as the single frontend switchboard for enabling/disabling speech input/browser output/Azure output per chatbot UI without editing component JSX.
    * app/frontend/src/chatbots/shared/theme: Shared chatbot theme registry and route wrapper. `chatbotThemes.ts` is the single frontend switchboard for navbar colors, header login button colors, basic-login page background/button colors, and user chat bubble colors across chatbot UIs. Most chatbots only need a single `primary` color there because the rest of the theme is auto-derived, with optional overrides for exceptions.
    * app/frontend/src/chatbots/<chatbot_name>: Chatbot-specific frontend implementation (pages, components, layout wrapper, i18n, locales, assets, and chatbot wiring).
      * app/frontend/src/chatbots/nerilio: Chatbot implementation.
      * app/frontend/src/chatbots/agindo: Chatbot implementation with an additional basic username/password login gate shown before chat.
      * app/frontend/src/chatbots/sartorius: Chatbot implementation with an additional basic username/password login gate shown before chat.
      * app/frontend/src/chatbots/steuertipps: Chatbot implementation.
      * app/frontend/src/chatbots/knoll: Chatbot implementation with an additional basic username/password login gate shown before chat.
      * app/frontend/src/chatbots/lemon: Chatbot implementation.
      * app/frontend/src/chatbots/moodle: Chatbot implementation with an additional basic username/password login gate shown before chat.
      * app/frontend/src/chatbots/public-test: Chatbot implementation cloned from `demo`, but now with its own email-based login/signup gate backed by backend persistence plus an HttpOnly signed session cookie, a two-step signup flow with email verification codes, a user-scoped upload-manager modal, and per-user PDF-only uploads. It accepts only PDF uploads, enforces a per-user limit of 30 total PDF pages across all uploaded files, and relies on the server-side session for upload, search, and citation isolation.
      * app/frontend/src/chatbots/publishone: Chatbot implementation.
      * app/frontend/src/chatbots/fbn: Chatbot implementation.
      * app/frontend/src/chatbots/demo: Chatbot implementation with a public upload manager modal opened from the header dropdown. Demo uploads use the backend `/chatbot_uploads/demo` endpoints, support local XML parsing in addition to the existing local formats, run as a per-file queue so users can select multiple files at once, expose a stop action that cancels the active upload and skips the remaining queue while keeping the searchable `demo` index/storage state consistent, and include both per-file delete controls and a bulk delete action for the uploaded-file library.
      * app/frontend/src/chatbots/fhg: Chatbot implementation with an additional basic username/password login gate shown before chat. Its frontend shows the initial assistant message "Hello! Just type your question in the chat." on load, and the backend FHG prompt continues from that message without sending an extra welcome.
      * app/frontend/src/chatbots/vjoonk4: Chatbot implementation with an additional basic username/password login gate shown before chat.
    * app/frontend/src/api: Contains the API client code for communicating with the backend.
    * app/frontend/src/chatbots/<chatbot_name>/locales: Chatbot-specific translation files.
      * app/frontend/src/chatbots/nerilio/locales/da/translation.json: Danish translations
      * app/frontend/src/chatbots/nerilio/locales/de/translation.json: German translations
      * app/frontend/src/chatbots/nerilio/locales/en/translation.json: English translations
      * app/frontend/src/chatbots/nerilio/locales/es/translation.json: Spanish translations
      * app/frontend/src/chatbots/nerilio/locales/fr/translation.json: French translations
      * app/frontend/src/chatbots/nerilio/locales/it/translation.json: Italian translations
      * app/frontend/src/chatbots/nerilio/locales/ja/translation.json: Japanese translations
      * app/frontend/src/chatbots/nerilio/locales/nl/translation.json: Dutch translations
      * app/frontend/src/chatbots/nerilio/locales/pl/translation.json: Polish translations
      * app/frontend/src/chatbots/nerilio/locales/ptBR/translation.json: Portuguese translations
      * app/frontend/src/chatbots/nerilio/locales/tr/translation.json: Turkish translations
* infra: Contains the Bicep templates for provisioning Azure resources. `infra/main.bicep` grants the backend managed identity `Storage Blob Data Contributor` on the main storage account and `Search Index Data Contributor` on Azure AI Search because shared chatbot uploads (currently the demo and public-test upload flows) write to blob storage and the search index even when `USE_USER_UPLOAD=false`. The same Bicep entry point also wires optional `PUBLIC_TEST_SMTP_*` and `PUBLIC_TEST_EMAIL_FROM*` environment variables into the backend so `public-test` can deliver signup verification emails from deployed environments.
* tests: Contains the test code, including e2e tests, app integration tests, and unit tests.

## Adding new data

New files should be added to the `data` folder, and then either run scripts/prepdocs.sh or scripts/prepdocs.ps1 to ingest the data.
For the wrapped FHG studies export (`data/fhg_alle_studien_*.json`), use `python app/backend/prep_fhg_json.py data/fhg_alle_studien_YYYYMMDD.json` instead of the generic `prepdocs` flow so that each `documents[]` entry is chunked as a study record, all metadata fields are preserved in the indexed content, source blobs are generated for citations, and embeddings are created for every chunk.
To purge indexed content for a single category without re-ingesting, use `python app/backend/delete_documents_by_category.py <category>`.

## Adding a new chatbot UI

Frontend chatbot UIs are routed by path segment (`/<chatbot_name>`). To add a new chatbot:

1. Create `app/frontend/src/chatbots/<chatbot_name>/` with that chatbot's pages/components/layout.
1. Export its definition (`name`, `LayoutWrapper`, `Chat`, `NoPage`, `i18n`) from `app/frontend/src/chatbots/<chatbot_name>/index.ts`.
1. Register it in `app/frontend/src/chatbots/registry.ts`.
1. Add that chatbot's theme entry in `app/frontend/src/chatbots/shared/theme/chatbotThemes.ts`. Usually a single `primary` color is enough; only add overrides if the auto-derived theme needs adjustment.
1. Add chatbot-specific i18n setup in `app/frontend/src/chatbots/<chatbot_name>/i18n/` and chatbot-specific translations in `app/frontend/src/chatbots/<chatbot_name>/locales/`.
1. If chatbot-specific auth is needed (for example, a basic username/password page), implement the gate in that chatbot's `layoutWrapper.tsx` so it applies only to that chatbot route.

## Adding a new azd environment variable

An azd environment variable is stored by the azd CLI for each environment. It is passed to the "azd up" command and can configure both provisioning options and application settings.
When adding new azd environment variables, update:

1. infra/main.parameters.json : Add the new parameter with a Bicep-friendly variable name and map to the new environment variable
1. infra/main.bicep: Add the new Bicep parameter at the top, and add it to the `appEnvVariables` object
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
  * app/backend/app.py: Some settings may need to be sent down in the /config route.

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
