# Instructions for Coding Agents

This file contains instructions for developers working on the Azure Search and OpenAI demo application. It covers the overall code layout, how to add new data, how to add new azd environment variables, how to add new developer settings, and how to add tests for new features.

Always keep this file up to date with any changes to the codebase or development process.
If necessary, edit this file to ensure it accurately reflects the current state of the project.

## Overall code layout

* app: Contains the main application code, including frontend and backend.
    * app/start.ps1: Local startup helper for the combined app. It loads the active `azd` environment, reuses an existing `app/.venv` when present, otherwise creates one with `PYTHON_VERSION` or defaults to Python `3.11` to match the deployed Azure runtime, restores backend/frontend dependencies, builds the frontend, and starts Quart on `localhost:50505`.
    * app/backend: Contains the Python backend code, written with Quart framework.
      * app/backend/core/internaladminauth.py: Shared internal-tools admin auth store. It validates the backend `INTERNAL_TOOLS_PASSWORD` (falling back to `CHATBOT_DIRECTORY_PASSWORD` for local/dev compatibility), issues the HttpOnly `internal_tools_admin_session` cookie for `/chatbots`, `/upload-files`, `/free-users`, and `/manage-prompts`, prefers `AZURE_SERVER_APP_SECRET` for session signing, and otherwise persists a shared fallback secret in the private `chatbot-prompts` container at `.auth/session-secret.txt`.
      * app/backend/core/chatbotpromptstore.py: Blob-backed runtime prompt override store for chatbot prompts. It keeps one JSON override per bot under `chatbot-prompts/prompts/<normalized-chatbot-name>.json`, rejects blank prompts, collapses identical-to-default saves back to delete, and leaves each bot's `sampleprompt.py` as the default fallback source.
      * app/backend/core/publictestauth.py: Persistent auth store for the Free Bot chatbot. It still uses the legacy `public-test` storage/auth identifiers internally for backward compatibility, stores verified account records plus pending signup and password-reset verification state as JSON blobs in a dedicated private container on the main storage account, hashes passwords and one-time verification codes with PBKDF2-HMAC-SHA256, sends signup and password-reset verification emails through configured SMTP settings, issues signed cookie-based sessions, can list verified accounts for the internal admin page, can delete account blobs when an admin removes a Free Bot user, can reset a verified user's password by overwriting the stored password salt/hash, and enforces a minimum password length of 8 characters for signup/password-reset flows. It prefers `AZURE_SERVER_APP_SECRET` for session signing and otherwise persists a shared fallback session secret in blob storage so all Container App replicas can validate the same cookies.
      * app/backend/approaches: Contains the different approaches
      * app/backend/approaches/approach.py: Base class for all approaches. Search-index result serialization includes optional first-class `storageUrl`, `title`, `url`, `tags`, and `user` fields when present, and URL-based document citations also add `external_results_metadata` entries so the frontend can show document titles while linking to external document URLs. `get_system_prompt_variables()` now routes chatbot prompts through each bot's configured `prompt_mode`, so simpler bots can inject their `sampleprompt.py` content into the shared `chat_answer.system.jinja2` base prompt while workflow-heavy bots still fully override it.
      * app/backend/approaches/chatreadretrieveread.py: Chat approach, includes query rewriting step first, and now resolves the document citation target (`sourcepage` vs `url`) through the chatbot config registry so external-feed bots can link directly to source URLs without hardcoded category checks.
      * app/backend/approaches/chatbot_config_registry.py: Loads optional chatbot backend config modules from `app/backend/approaches/chatbots/<chatbot_name>/config.py`, normalizes chatbot names, exposes `get_chatbot_config()` / `get_chatbot_citation_target()` / `get_chatbot_prompt_mode()`, renders prompt placeholders such as `{{SUPPORT_EMAIL}}` and `{{POSSIBLE_CITATIONS_PROMPT}}`, and auto-discovers which bots need backend-specific settings.
      * app/backend/approaches/chatbot_content_filter_registry.py: Provides localized default content-filter messages plus optional chatbot-specific overrides loaded from `app/backend/approaches/chatbots/<chatbot_name>/contentfilter.py`.
      * app/backend/approaches/chatbot_prompt_registry.py: Maps chatbot names to chatbot-specific prompt modules and exposes the registered chatbot names used by the prompt admin API.
      * app/backend/approaches/chatbots/chatbot_config.py: Shared `ChatbotConfig` dataclass for per-bot backend overrides such as `chatgpt_model`, `chatgpt_deployment`, `reasoning_effort`, support-contact prompt values like `support_email`, `prompt_mode` (`inject` vs `override`), and citation target behavior.
      * app/backend/approaches/chatbots/<chatbot_name>/config.py: Optional chatbot-specific backend config. Add one when a bot needs a different LLM model/deployment, a different default reasoning effort, prompt-time contact/config values such as `support_email`, a specific `prompt_mode` (`inject` to extend the shared system prompt or `override` to replace it), or a non-default citation target such as direct URL citations.
      * app/backend/approaches/chatbots/<chatbot_name>/sampleprompt.py: Chatbot-specific `SAMPLE_PROMPT` definitions used by `get_system_prompt_variables`. These files remain the default/fallback prompt source even when `/manage-prompts` stores a runtime override in blob storage. Depending on each bot's `prompt_mode`, the prompt is either injected into the shared `chat_answer.system.jinja2` base prompt or used as the full system prompt override.
      * app/backend/approaches/chatbots/<chatbot_name>/contentfilter.py: Optional chatbot-specific `CONTENT_FILTER_MESSAGES` dictionaries keyed by locale/language code for overriding the default OpenAI content-filter error text.
      * app/backend/approaches/promptmanager.py: Manages loading and rendering of Jinja2 prompt templates
      * app/backend/approaches/prompts/query_rewrite.system.jinja2: Jinja2 template used to rewrite the query based off search history into a better search query
      * app/backend/approaches/prompts/chat_query_rewrite_tools.json: Tools used by the query rewriting prompt
      * app/backend/approaches/prompts/chat_answer.system.jinja2: Jinja2 template for the system message used by the Chat approach to answer questions. It remains the shared base prompt for bots configured with `prompt_mode="inject"` and is bypassed only for bots configured with `prompt_mode="override"` or for explicit request-level prompt overrides.
      * app/backend/approaches/prompts/chat_answer.user.jinja2: Jinja2 template for the user message used by the Chat approach, including sources
      * app/backend/approaches/prompts/demo.system.sample.jinja2: Demo-only full Jinja2 mirror of `app/backend/approaches/chatbots/demo/sampleprompt.py` for inspection/testing. It is not wired into runtime prompt selection, and literal instructional placeholders such as `{{N}}` remain unescaped on purpose because the file is illustrative.
    * app/backend/prepdocslib: Contains the document ingestion library used by both local and cloud ingestion
      * app/backend/prepdocslib/blobmanager.py: Manages uploads to Azure Blob Storage. Generic `prepdocs` ingestion now stores original blobs under `<category>/<filename>` inside the main content container when `--category` is provided, so the indexed `storageUrl` also points to `content/<category>/<filename>`.
      * app/backend/prepdocslib/blobautoindex.py: Shared helper for blob-triggered automatic ingestion. It filters supported source blobs, copies them into a target category folder such as `content/moodle/`, removes stale search documents for that file/category, and re-indexes the copied blob with either the repo's normal parser/chunking pipeline or a feed-specific section builder so `storageUrl` points at the chatbot-owned copy. It can also skip index-schema management for workers that only need to write documents into an already-existing Azure AI Search index.
      * app/backend/prepdocslib/categoryupload.py: Category-aware shared upload manager used by the internal `/upload-files` page. It stores the uploaded file itself directly under `content/<category>/<filename>`, keeps hidden management manifests and cancel markers under `content/<category>/.managed-uploads/`, indexes the file back into the same search `category`, writes the uploaded blob URL into `storageUrl`, lists managed uploads across categories via those manifests, and deletes only uploads it owns so built-in category content is left untouched.
      * app/backend/prepdocslib/cloudingestionstrategy.py: Builds the Azure AI Search indexer and skillset for the cloud ingestion pipeline
      * app/backend/prepdocslib/csvparser.py: Parses CSV files with dialect detection for delimiters such as comma/semicolon/tab/pipe, preserves quoted multiline cells as one logical row, emits one retrieval-friendly labeled record per row, and surfaces optional row-level `sourcepage`, `title`, `url`, `tags`, and `user` metadata for indexing.
      * app/backend/prepdocslib/embeddings.py: Generates embeddings for text and images using Azure OpenAI
      * app/backend/prepdocslib/figureprocessor.py: Generates figure descriptions for both local ingestion and the cloud figure-processor skill
      * app/backend/prepdocslib/fileprocessor.py: Orchestrates parsing and chunking of individual files
      * app/backend/prepdocslib/filestrategy.py: Strategy helpers for local ingestion, authenticated user uploads in ADLS, and shared chatbot uploads in blob storage. `ChatbotUploadStrategy` powers the demo-style public upload flows using local parsers only, indexes uploads into the chatbot's normal category, rejects filename collisions with built-in chatbot content, stores new demo uploads directly under `content/demo/<filename>`, new `internal` uploads under `content/internal/<filename>`, new `public-test` uploads under `content/public-test/<user-token>/<filename>`, and user-scoped `rak` uploads under `content/rak/<user-token>/<filename>`. It keeps hidden manifest/cancel metadata under `.manifests/` and `.cancel/` within those prefixes, and still recognizes older `chatbot-uploads/...` blobs so existing uploads can be listed, downloaded, and deleted during the transition. It also supports cooperative cancellation plus per-chatbot upload rules such as allowed file extensions, maximum total PDF pages across uploaded files, and optional per-user upload scoping.
      * app/backend/prepdocslib/xmlparser.py: Local XML parser that preserves hierarchy, carries forward lightweight document context, and splits repeated sibling records (for example `<item>` or `<product>`) into separate retrieval-friendly sections before chunking.
      * app/backend/prepdocslib/htmlparser.py: Parses HTML files
      * app/backend/prepdocslib/integratedvectorizerstrategy.py: Strategy using Azure AI Search integrated vectorization
      * app/backend/prepdocslib/jsonparser.py: Parses JSON files
      * app/backend/prepdocslib/listfilestrategy.py: Lists files from local filesystem or Azure Data Lake
      * app/backend/prepdocslib/mediadescriber.py: Interfaces for describing images (Azure OpenAI GPT-4o, Content Understanding)
      * app/backend/prepdocslib/page.py: Data classes for pages, images, and chunks. `Page` can also carry optional ingestion metadata such as `sourcepage`, `title`, `url`, `tags`, and `user`, which row-oriented parsers like the CSV parser propagate into indexed sections.
      * app/backend/prepdocslib/parser.py: Base parser interface
      * app/backend/prepdocslib/pdfparser.py: Parses PDFs using Azure Document Intelligence or local parser
      * app/backend/prepdocslib/publishonefeed.py: Specialized XML section builder for the Moodle and PublishOne external feeds. It treats each outer `<document id="...">` node as one logical record, maps that id to `sourcepage`, maps direct `<naam>` to the first-class `title` field, builds `url` as `https://snap.publishone.nl/document/<document-id>/content`, renders the logical document subtree into structured plain text for the searchable `content` field, keeps direct document metadata readable without duplicating `<meta>` blocks, preserves folder-level metadata plus inline link/image targets inside `content`, and maps document, direct meta, and folder metadata such as state, type, version, orientation, language, and folder path into the `tags` field.
      * app/backend/prepdocslib/searchmanager.py: Manages Azure AI Search index creation and updates. The managed index schema includes `storageUrl` for source blob lookups, first-class `title`/`url`/`tags` fields for richer retrieval metadata, and a `user` field used by per-user chatbot upload flows such as `public-test` and `rak`. Section-level metadata from row-aware parsers is written directly into those fields during indexing.
      * app/backend/prepdocslib/servicesetup.py: Shared service setup helpers for OpenAI, embeddings, blob storage, etc. `.csv` files use the CSV parser together with a row-aware `CsvTextSplitter` so one CSV row stays one logical retrieval record unless it is too large and must be split with repeated row identity context.
      * app/backend/prepdocslib/strategy.py: Base strategy interface for document ingestion
      * app/backend/prepdocslib/textparser.py: Parses plain text and markdown files
      * app/backend/prepdocslib/textprocessor.py: Processes text chunks for cloud ingestion (merges figures, generates embeddings) and propagates any page-level metadata such as row `sourcepage`, `title`, `url`, `tags`, and `user` onto the generated search sections.
      * app/backend/prepdocslib/textsplitter.py: Splits text into chunks using different strategies
      * app/backend/prepdocslib/fhgjson.py: FHG-specific JSON ingestion helpers that validate the wrapped dataset structure, map `title`/`url`/`tags` into first-class search fields, map `sourcefile` from each study's `filename`, map `sourcepage` from `doc_id` plus `parent_id`, and build search-ready documents with stable IDs. The indexed `content` field keeps the chunked study body plus semantically useful study metadata such as title, tags, categories, and degree information, but excludes operational fields like ids, filenames, raw JSON dumps, and storage URLs.
    * app/backend/delete_documents_by_category.py: Utility script that deletes all Azure AI Search documents whose `category` field matches a provided value.
    * app/backend/migrate_storage_urls_to_category_paths.py: One-time migration utility for existing generic `prepdocs` content. It copies root-level blobs like `content/<filename>` to `content/<category>/<filename>` based on each indexed document's `category`, updates the corresponding `storageUrl` values in Azure AI Search, and deletes old root blobs once nothing in the index still references them.
    * app/backend/prep_fhg_json.py: Dedicated ingestion script for wrapped FHG studies exports such as `data/fhg.json`. It chunks each FHG study entry logically, uploads the raw dataset file to `content/fhg/<filename>` in blob storage, maps that blob URL to `storageUrl`, generates embeddings for every indexed chunk, stores them in Azure AI Search with category `fhg`, and by default replaces existing `fhg` documents before re-indexing.
    * app/backend/app.py: The main entry point for the backend application, including SPA fallback routes for chatbot URLs like `/<chatbot_name>`, server-side redirect of unknown chatbot names back to `/`, SPA fallbacks for `/chatbots`, `/upload-files`, `/public-test-users`, and `/manage-prompts`, public chatbot upload routes at `/chatbot_uploads/<chatbot_name>` (currently used by the demo, `internal`, `public-test`, and `rak` bots), category-aware shared upload management routes at `/managed_uploads` for the internal upload page, upload cancellation at `/chatbot_uploads/<chatbot_name>/cancel/<upload_id>` and `/managed_uploads/cancel/<upload_id>`, chatbot-upload content fallback in `/content/<path>` with category-prefixed blob fallback based on `chatbot_name` or the page referrer, locale-aware content-filter error handling for `/chat` and `/chat/stream` based on `context.overrides.language` or `Accept-Language`, and no-store caching headers for `index.html` responses to avoid stale frontend routing behavior. Its `/config` payload includes internal developer-setting metadata such as `availableChatModels`, `reasoningCapableChatModels`, and `chatModelReasoningEfforts`, so the internal bot can show model-specific reasoning-effort options like `minimal` for GPT-5 and `none`/`xhigh` for GPT-5.4. On startup it auto-discovers chatbot `config.py` files and builds per-bot `ChatReadRetrieveReadApproach` overrides when a bot's model, Azure deployment, or reasoning effort differs from the global defaults. Its OpenLIT wiring now keeps standalone OpenLIT mode LLM-only by disabling the generic HTTP/framework instrumentors there, while the Azure Monitor + OpenLIT dual-export path continues exporting only LLM spans to OpenLIT through the filtered OTLP exporter. It also exposes backend-enforced internal admin auth endpoints at `/internal-admin/login`, `/internal-admin/session`, and `/internal-admin/logout`, protects `/managed_uploads*`, `/public-test-admin/*`, and `/internal-admin/prompts*` with the shared admin session, and injects saved prompt overrides into `/chat` and `/chat/stream` unless a request-level `prompt_template` override was supplied. `public-test` uses dedicated backend auth endpoints at `/public-test-auth/*` for signup, email-code verification, password-reset code flows, profile lookup, login, session lookup, and logout, plus internal admin endpoints at `/public-test-admin/users` for listing verified users, deleting accounts, and resetting user passwords, a signed session cookie, per-user upload storage paths, and per-user search filtering. `rak` uses a demo-style upload flow with frontend basic login and backend-enforced username scoping via `X-Chatbot-User` / `chatbot_user` for uploads, search filters, and citation file access.
  * scripts/setup_moodle_delete_event_subscription.py: Post-deploy helper that creates or updates the Event Grid subscriptions for the external XML feed automations after the `moodle_auto_indexer` Function App has been published, avoiding the provisioning-time race where the function resources do not exist yet. It currently manages both the Moodle and PublishOne create/delete sync subscriptions, and it requires Azure CLI (`az`) on `PATH` because it shells out to `az resource`, `az functionapp`, and `az eventgrid` commands while using the default `azd` environment for resource identifiers.
  * scripts/load_python_env.ps1: Shared Windows helper for the repo-root auth/prepdocs/deploy scripts. It reuses the repo-root `.venv` when present, otherwise creates one with `PYTHON_VERSION` or defaults to Python `3.11` to match Azure, and fails fast if virtual-environment creation or backend dependency installation fails.
  * app/functions: Azure Functions used for cloud ingestion custom skills plus blob-event automation. Existing custom skills are `document_extractor`, `figure_processor`, and `text_processor`; `moodle_auto_indexer` is a separate Function App that uses Event Grid subscriptions on `content/nerilio/Nerilio-Moodle/` and `content/nerilio/Nerilio-PublishOne/` to detect new or updated XML blobs, copies them into `content/moodle/` and `content/publishone/`, indexes them as categories `moodle` and `publishone`, parses each outer XML `<document id="...">` into a title/url/sourcepage-aware logical search record, and also handles delete-sync by removing the copied blobs plus their indexed documents when the source blobs are deleted. Each function bundles a synchronized copy of `prepdocslib`; run `python scripts/copy_prepdocslib.py` to refresh the local copies if you modify the library.
    * app/frontend: Contains the React frontend code, built with TypeScript, built with vite.
    * app/frontend/index.html: Shared Vite HTML entry document. It loads the browser-tab favicon from `app/frontend/src/assets/robo1.png`.
    * app/frontend/src/index.tsx: Frontend entry point and router setup. It resolves chatbot UI by URL path (`/<chatbot_name>`), serves the shared branded `NoPage` experience on `/`, provides backend-session-gated internal tools at `/chatbots`, `/upload-files`, `/public-test-users`, and `/manage-prompts`, routes each chatbot root through its normal `LayoutWrapper`, and renders chatbot catch-all `/<chatbot_name>/*` `NoPage` routes outside that layout so the branded 404 page shows without the chatbot navbar/header shell.
    * app/frontend/src/authConfig.ts and app/frontend/src/chatbots/<chatbot_name>/authConfig.ts: Shared MSAL/App Service auth helpers. App Service auth endpoints use absolute `/.auth/*` paths so deep links such as chatbot-local `NoPage` routes continue to boot correctly instead of resolving auth requests relative to the current chatbot URL.
    * app/frontend/src/pages/ChatbotDirectory.tsx: Backend-session-gated page listing all currently registered chatbot links. It signs into the shared internal admin backend session instead of comparing a frontend-shipped password, and links to the upload manager, prompt manager, and `public-test` user admin pages.
    * app/frontend/src/pages/PublicTestUsersPage.tsx: Backend-session-gated internal admin page for `public-test` accounts. It lists verified users, their timestamps, their uploaded-file counts and filenames, can delete a user account while also removing that user's `public-test` uploads, includes an inline password-reset form that updates the stored password hash for a verified account, and shares the same backend admin session used by the other internal tools.
    * app/frontend/src/pages/UploadFilesPage.tsx: Backend-session-gated internal upload-management page that lets admins queue files into any chatbot/search category, shows per-file upload status while the queue runs, supports stopping the active managed-upload queue, allows adding more files while uploads are already in progress, supports dismissing completed/failed/canceled queue rows in bulk, and uses server-side pagination/search for the managed file library with a 10/15 rows-per-page selector. The page now patches successful uploads into the visible library state optimistically and only revalidates the current page after the queue completes, rather than reloading the entire managed upload library after every uploaded file. It also lists uploaded files across all categories or by category, deletes individual uploads, all uploads in one category, or all managed uploads, and links to the prompt manager and `public-test` user admin page.
    * app/frontend/src/pages/ManagePromptsPage.tsx: Backend-session-gated internal prompt-management page. It lists every chatbot prompt from the backend prompt registry, supports search, raw prompt editing, save/reset actions, source badges, updated timestamps, and unsaved-change warnings, and saves prompt overrides through `/internal-admin/prompts/*` without modifying the chatbot `sampleprompt.py` files.
    * app/frontend/src/pages/useInternalAdminAccess.ts: Shared internal-tools auth hook used by `/chatbots`, `/upload-files`, `/public-test-users`, and `/manage-prompts`. It verifies the backend admin session, handles login/logout against `/internal-admin/*`, and clears local UI state when the shared admin session expires.
    * app/frontend/src/chatbots/registry.ts: Registry of available chatbot UIs, including the chatbot-specific i18n instance.
    * app/frontend/src/chatbots/shared/basicauth/BasicLoginPage.tsx: Shared themed basic-auth login page used by chatbot-specific basic auth routes. It supports chatbot-specific logo frame and logo class overrides so wordmark logos can use a different treatment than square icons.
    * app/frontend/src/chatbots/shared/components/Example/Example.tsx: Shared clickable example-card component used by most chatbot `components/Example/Example.tsx` wrappers, so bots that do not need special example-card behavior can re-export one shared implementation.
    * app/frontend/src/chatbots/shared/noPage/NoPage.tsx: Shared branded 404/NoPage experience used by the root `/` route and all chatbot catch-all routes. It renders the attached nerilio-style support page as a standalone view without the chatbot navbar/header shell, including the gradient background, support CTA buttons, footer links, and the translated page title, and resolves its copy through each chatbot's `noPage.*` locale strings with explicit `en`/`de`/`nl` support plus English fallback for other active locales.
    * app/frontend/src/chatbots/shared/answer: Shared premium answer renderer used by chatbot UIs. `createBotAnswer.tsx` is the factory most bots use for thin `Answer.tsx` wrappers, while `ChatbotAnswer.tsx` holds the shared rendering/runtime behavior. It parses inline citations into safe markdown links, renders markdown without `rehypeRaw`, supports premium typography plus table/code-block rendering, supports either circular assistant avatars or wordmark-style assistant logos with per-chatbot size overrides, can place avatar logos either inside the answer card header or outside the card on the left, and keeps chatbot-specific branding/citation path behavior in thin chatbot-local wrappers.
    * app/frontend/src/chatbots/shared/disclaimer: Shared dismissible chatbot disclaimer banner used in chat pages. It opens on initial chatbot load and re-opens when the in-chat login state changes from logged out to logged in.
    * app/frontend/src/chatbots/shared/speech: Shared Azure Speech browser helpers/components for chatbot mic input and low-latency TTS playback. It fetches short-lived auth tokens from `/speech/token`, uses Azure Speech SDK microphone recognition instead of the browser `SpeechRecognition` API, chooses a Firefox-safe streamed synthesis format at runtime, and includes `chatbotSpeechFeatureFlags.ts` as the single frontend switchboard for enabling/disabling speech input/browser output/Azure output per chatbot UI without editing component JSX.
    * app/frontend/src/chatbots/shared/theme: Shared chatbot theme registry and route wrapper. `chatbotThemes.ts` is the single frontend switchboard for navbar colors, header login button colors, basic-login page background/button colors, and user chat bubble colors across chatbot UIs. Most chatbots only need a single `primary` color there because the rest of the theme is auto-derived, with optional overrides for exceptions.
    * app/frontend/src/chatbots/<chatbot_name>: Chatbot-specific frontend implementation (pages, components, layout wrapper, i18n, locales, assets, and chatbot wiring). All chatbot header dropdowns use `New chat` to reset the current conversation and expose a `View recent chats` action that opens that bot's history panel. Chat history is scoped per chatbot in both browser IndexedDB and Cosmos-backed history, so one bot does not show another bot's recent chats. Chat pages that render an initial assistant welcome treat it as a synthetic UI-only assistant turn: it appears once in chat, but it is stripped from saved/restored history payloads and browser-history fallbacks use a client-generated session id when the backend does not return one. Most chatbot `components/Answer/Answer.tsx` and `components/Example/Example.tsx` files are intentionally thin wrappers around the shared factories; keep a chatbot-local implementation only when branding or behavior really differs, such as wordmark logos or user-scoped citation paths.
      * app/frontend/src/chatbots/nerilio: Chatbot implementation. Its assistant answers use the shared outside-left avatar layout so the round nerilio logo sits beside the answer card instead of inside the card header.
      * app/frontend/src/chatbots/agindo: Chatbot implementation with an additional basic username/password login gate shown before chat.
      * app/frontend/src/chatbots/sartorius: Chatbot implementation with an additional basic username/password login gate shown before chat and wordmark-only branding in both the navbar and assistant answer header.
      * app/frontend/src/chatbots/steuertipps: Chatbot implementation with an additional basic username/password login gate shown before chat and wordmark-only branding in the navbar, assistant answer header, and basic-login card.
      * app/frontend/src/chatbots/knoll: Chatbot implementation with an additional basic username/password login gate shown before chat.
      * app/frontend/src/chatbots/lemon: Chatbot implementation.
      * app/frontend/src/chatbots/internal: Chatbot implementation that reuses the lemon chat stack and branding, routes at `/internal`, uses the same yellow theme as lemon, scopes retrieval/uploads to category `internal`, exposes the demo-style shared upload-manager modal from the navbar dropdown, and places the developer-options action inside that same dropdown instead of a standalone button.
      * app/frontend/src/chatbots/moodle: Chatbot implementation with an additional basic username/password login gate shown before chat.
      * app/frontend/src/chatbots/public-test: Chatbot implementation cloned from `demo`, but now with its own email-based login/signup gate backed by backend persistence plus an HttpOnly signed session cookie, a two-step signup flow with email verification codes, a matching forgot-password flow with emailed reset codes, a navbar profile modal fed by the signed-in account, a user-scoped upload-manager modal, and per-user PDF-only uploads. Its upload modal supports queue stop/cancel, per-item dismiss, bulk dismissal of finished queue rows, and library delete actions. It accepts only PDF uploads, enforces a per-user limit of 30 total PDF pages across all uploaded files, relies on the server-side session for upload, search, citation isolation, and profile lookup, scopes browser chat history per signed-up public-test email on the current browser profile, and uses that same signed session to derive a per-user history scope when Cosmos chat history is enabled.
      * app/frontend/src/chatbots/publishone: Chatbot implementation that uses split PublishOne branding: the navbar shows the light-text `publishone-nav.svg` wordmark without a separate title, while assistant answer headers show the dark-text `publishone-chat.png` wordmark without assistant-name text.
      * app/frontend/src/chatbots/rak: Chatbot implementation cloned from `demo` with upload support, a static two-username basic login gate, a red shared theme, split branding between a horizontal navbar wordmark and a round logo for login/assistant cards, per-username upload/search/citation/chat-history scoping for the two configured RAK users, and an upload modal that supports bulk dismissal of finished queue rows.
      * app/frontend/src/chatbots/fbn: Chatbot implementation.
      * app/frontend/src/chatbots/demo: Chatbot implementation with a public upload manager modal opened from the header dropdown. Demo uploads use the backend `/chatbot_uploads/demo` endpoints, support local XML parsing in addition to the existing local formats, run as a per-file queue so users can select multiple files at once, expose a stop action that cancels the active upload and skips the remaining queue while keeping the searchable `demo` index/storage state consistent, support both per-item dismiss and bulk dismissal of finished queue rows, and include both per-file delete controls and a bulk delete action for the uploaded-file library. Demo local history uses a demo-scoped browser IndexedDB namespace with a client-generated session id fallback so recent chats still work even if the backend does not provide a chat-history session id.
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
* infra: Contains the Bicep templates for provisioning Azure resources. `infra/main.bicep` grants the backend managed identity `Storage Blob Data Contributor` on the main storage account and `Search Index Data Contributor` on Azure AI Search because shared chatbot uploads (currently the demo, `public-test`, and `rak` upload flows) write to blob storage and the search index even when `USE_USER_UPLOAD=false`. The same Bicep entry point also wires optional `PUBLIC_TEST_SMTP_*`, `PUBLIC_TEST_EMAIL_FROM*`, `OPENLIT_ENDPOINT`, and `INTERNAL_TOOLS_PASSWORD` environment variables into the backend so deployed environments can deliver `public-test` emails, export traces to OpenLIT, and protect the shared internal admin tools. `infra/main.parameters.json` must continue mapping the `OPENLIT_ENDPOINT` azd env var into the `openLitEndpoint` Bicep parameter so `azd up` does not clear the deployed backend's OpenLIT exporter setting. For backward compatibility, deployments also accept the legacy `CHATBOT_DIRECTORY_PASSWORD` azd env var as a fallback source for `INTERNAL_TOOLS_PASSWORD`, and optional Container Apps secrets must only be emitted when they have a non-empty value because Azure Container Apps rejects blank secret values.
* docker-compose.openlit.yml: Optional local OpenLIT Docker Compose stack for observability experiments. It starts ClickHouse, the OpenTelemetry Collector, and the OpenLIT dashboard locally with the matching collector config from `otel-collector-config.yaml`, which filters stored traces down to LLM spans only.
* otel-collector-config.aci.yaml: OpenTelemetry Collector configuration used by the ACI-hosted OpenLIT setup so OTLP traffic on ports `4317`/`4318` is written into the colocated ClickHouse instance, with the same LLM-only trace filter as the local collector stack.
* aci-openlit.example.yaml: Sanitized template for a local Azure Container Instances OpenLIT deployment. Copy it to the ignored `aci-openlit.yaml`, fill in the real storage account key and app secret locally, and keep those live secrets out of git.
* tests: Contains the test code, including e2e tests, app integration tests, and unit tests.

## Adding new data

New files should be added to the `data` folder, and then either run scripts/prepdocs.sh or scripts/prepdocs.ps1 to ingest the data. When `--category <name>` is passed to the generic `prepdocs` flow, the original source blobs are stored under `content/<name>/` and the indexed `storageUrl` values point to that category-specific blob path.
For wrapped FHG studies exports such as `data/fhg.json` or `data/fhg_alle_studien_YYYYMMDD.json`, use `python app/backend/prep_fhg_json.py <path-to-json>` instead of the generic `prepdocs` flow so that each `documents[]` entry is chunked as a study record, the indexed `content` contains the study body plus retrieval-relevant metadata, the raw dataset file is uploaded under `content/fhg/`, first-class `title`/`url`/`tags` fields are populated, and embeddings are created for every chunk.
For the Moodle and PublishOne chatbots' externally synced XML feeds, blobs dropped into `content/nerilio/Nerilio-Moodle/` or `content/nerilio/Nerilio-PublishOne/` are picked up automatically by the `moodle_auto_indexer` Function App, copied into `content/moodle/` or `content/publishone/`, and indexed into Azure AI Search with categories `moodle` and `publishone` so the chatbot `storageUrl` values point at the copied chatbot-owned blobs instead of the external drop folders. The feed parser maps each outer `<document id="...">` to `sourcepage`, maps direct `<naam>` to `title`, maps `url` to `https://snap.publishone.nl/document/<document-id>/content`, renders the logical document subtree into structured plain text inside `content`, preserves folder-level metadata and inline link/image targets there, and stores additional document and direct meta metadata in `tags`. Moodle and PublishOne citations use those first-class `title` and `url` fields so the chat UI shows the document title while linking out to the external PublishOne document URL. When one of those source XML blobs is deleted, the same automation removes the mirrored target blob and the corresponding indexed documents as well.
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
