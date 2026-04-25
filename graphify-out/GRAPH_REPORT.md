# Graph Report - agentic-retrieval  (2026-04-25)

## Corpus Check
- 1319 files · ~1,063,007 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 6651 nodes · 18808 edges · 97 communities detected
- Extraction: 73% EXTRACTED · 27% INFERRED · 0% AMBIGUOUS · INFERRED: 5086 edges (avg confidence: 0.69)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 60|Community 60]]
- [[_COMMUNITY_Community 70|Community 70]]
- [[_COMMUNITY_Community 71|Community 71]]
- [[_COMMUNITY_Community 72|Community 72]]
- [[_COMMUNITY_Community 73|Community 73]]
- [[_COMMUNITY_Community 75|Community 75]]
- [[_COMMUNITY_Community 76|Community 76]]
- [[_COMMUNITY_Community 77|Community 77]]
- [[_COMMUNITY_Community 680|Community 680]]
- [[_COMMUNITY_Community 681|Community 681]]
- [[_COMMUNITY_Community 682|Community 682]]
- [[_COMMUNITY_Community 683|Community 683]]
- [[_COMMUNITY_Community 684|Community 684]]
- [[_COMMUNITY_Community 685|Community 685]]
- [[_COMMUNITY_Community 686|Community 686]]
- [[_COMMUNITY_Community 687|Community 687]]
- [[_COMMUNITY_Community 688|Community 688]]
- [[_COMMUNITY_Community 689|Community 689]]
- [[_COMMUNITY_Community 690|Community 690]]
- [[_COMMUNITY_Community 691|Community 691]]
- [[_COMMUNITY_Community 692|Community 692]]
- [[_COMMUNITY_Community 693|Community 693]]
- [[_COMMUNITY_Community 694|Community 694]]
- [[_COMMUNITY_Community 698|Community 698]]
- [[_COMMUNITY_Community 700|Community 700]]
- [[_COMMUNITY_Community 701|Community 701]]
- [[_COMMUNITY_Community 702|Community 702]]
- [[_COMMUNITY_Community 703|Community 703]]
- [[_COMMUNITY_Community 704|Community 704]]
- [[_COMMUNITY_Community 705|Community 705]]
- [[_COMMUNITY_Community 706|Community 706]]
- [[_COMMUNITY_Community 707|Community 707]]
- [[_COMMUNITY_Community 708|Community 708]]
- [[_COMMUNITY_Community 709|Community 709]]
- [[_COMMUNITY_Community 710|Community 710]]
- [[_COMMUNITY_Community 711|Community 711]]
- [[_COMMUNITY_Community 712|Community 712]]
- [[_COMMUNITY_Community 713|Community 713]]
- [[_COMMUNITY_Community 714|Community 714]]
- [[_COMMUNITY_Community 715|Community 715]]
- [[_COMMUNITY_Community 716|Community 716]]

## God Nodes (most connected - your core abstractions)
1. `nT` - 144 edges
2. `set()` - 139 edges
3. `BlobManager` - 137 edges
4. `SentenceTextSplitter` - 136 edges
5. `Page` - 135 edges
6. `FileProcessor` - 119 edges
7. `File` - 119 edges
8. `ImageEmbeddings` - 99 edges
9. `OE()` - 97 edges
10. `SearchManager` - 96 edges

## Surprising Connections (you probably didn't know these)
- `build_publishone_feed_sections()` --semantically_similar_to--> `XmlParser`  [INFERRED] [semantically similar]
  app\functions\text_processor\prepdocslib\publishonefeed.py → app\functions\text_processor\prepdocslib\xmlparser.py
- `Ensures that a directory path exists and has proper permissions.         Create` --uses--> `File`  [INFERRED]
  app\functions\text_processor\prepdocslib\blobmanager.py → app\functions\text_processor\prepdocslib\listfilestrategy.py
- `Uploads a file directly to the user's directory in ADLS (no subdirectory).` --uses--> `File`  [INFERRED]
  app\functions\text_processor\prepdocslib\blobmanager.py → app\functions\text_processor\prepdocslib\listfilestrategy.py
- `Downloads a blob from Azure Data Lake Storage.          Args:             blo` --uses--> `File`  [INFERRED]
  app\functions\text_processor\prepdocslib\blobmanager.py → app\functions\text_processor\prepdocslib\listfilestrategy.py
- `Downloads a blob from Azure Blob Storage.          Args:             blob_pat` --uses--> `File`  [INFERRED]
  app\functions\text_processor\prepdocslib\blobmanager.py → app\functions\text_processor\prepdocslib\listfilestrategy.py

## Hyperedges (group relationships)
- **Per-chatbot customization stack** — chatbot_prompt_registry_module, chatbot_config_registry_module, chatbot_content_filter_module, chatbot_prompt_normalize_chatbot_name [EXTRACTED 0.90]
- **Azure AI Search document ingestion pipeline** — prepdocs_module, setup_cloud_ingestion_main, prep_fhg_json_run, migrate_storage_urls_run, delete_documents_by_category_fn [INFERRED 0.80]
- **RAG chat request flow** — app_py_module, chatreadretrieveread_ChatReadRetrieveReadApproach, approach_Approach, promptmanager_PromptManager, approach_run_agentic_retrieval [EXTRACTED 0.90]
- **Demo AnalysisPanel module** — AnalysisPanel_component, AnalysisPanelTabs_enum, ThoughtProcess_component, agentPlanUtils_getStepLabel [INFERRED 0.85]
- **Demo Answer module** — Answer_demo, AnswerLoading_component, AnswerError_component, AnswerParser_parseAnswerToHtml [INFERRED 0.85]
- **Demo chat control buttons** — ClearChatButton_component, HistoryButton_component, HelpCallout_component [INFERRED 0.75]
- **Per-tenant ChatbotConfig instances** — chatbot_config_ChatbotConfig, agindo_config, demo_config, fbn_config, fhg_config, internal_config, knoll_config, lemon_config [EXTRACTED 1.00]
- **Tutor/Q&A dual-mode prompt family with P0-P3 priority hierarchy and SUPPORT_EMAIL fallback** — demo_sampleprompt, fbn_sampleprompt, knoll_sampleprompt, internal_sampleprompt, lemon_sampleprompt [INFERRED 0.90]
- **Simple Q&A-only prompts with markdown style rules and support-email fallback** — agindo_sampleprompt, fhg_sampleprompt [INFERRED 0.70]
- **Tutor/Q&A Dual-Mode Learning Chatbots with Priority Hierarchy** — moodle_sampleprompt, steuertipps_sampleprompt, publishone_sampleprompt [INFERRED 0.90]
- **Generic Minimal RAG Prompts (source-restricted + citations)** — sartorius_sampleprompt, public_test_sampleprompt [INFERRED 0.85]
- **Per-Chatbot ChatbotConfig Plugin Registry** — moodle_config, nerilio_config, public_test_config, publishone_config, rak_config, sartorius_config, steuertipps_config [EXTRACTED 1.00]
- **Document Ingestion Pipeline** — filestrategy_parse_file, fileprocessor_fp, figureprocessor_process_page_image, blobmanager_blob, embeddings_openai [INFERRED 0.85]
- **Chatbot Upload Strategy Family** — filestrategy_chatbot_upload_strategy, categoryupload_strategy, filestrategy_upload_user_file_strategy, blobautoindex_indexer [INFERRED 0.80]
- **Blob-Backed Auth Stores** — publictestauth_store, internaladminauth_store, chatbotpromptstore_store, blobmanager_blob [INFERRED 0.80]
- **Shared answer rendering pipeline (parse -> render -> speech/copy)** — shared_parse_answer_to_markdown, shared_chatbot_answer, shared_create_bot_answer, shared_strip_citation_links, shared_clean_speech_text, shared_citation_detail_type [EXTRACTED 0.95]
- **Shared UI primitives reused by all bots** — shared_chatbot_answer, shared_basic_login_page, shared_example_component, shared_create_bot_answer [INFERRED 0.85]
- **Sartorius chatbot is a clone of Agindo** — sartorius_chat_page, sartorius_layout, sartorius_basic_login, sartorius_vector_settings, sartorius_upload_file, sartorius_user_chat_message, sartorius_supporting_content_parser, sartorius_i18n_config, sartorius_language_picker [INFERRED 0.90]
- **Azure Speech Primitives (shared token/recognize/synthesize)** — azureSpeech_getSpeechToken, azureSpeech_getSpeechRecognitionLocale, azureSpeech_getPreferredSpeechSynthesisOutputFormat, SpeechInputButton_component, SpeechOutputAzureButton_component [INFERRED 0.90]
- **Theme Derivation Pipeline (seed -> theme -> CSS vars -> root)** — chatbotThemes_registry, chatbotThemes_resolveChatbotTheme, chatbotThemes_getChatbotThemeCssVariables, ChatbotThemeRoot_component, chatbotThemes_colorUtilities [EXTRACTED 1.00]
- **Per-chatbot Speech UI Gating** — chatbotSpeechFeatureFlags_registry, chatbotSpeechFeatureFlags_applyChatbotSpeechFeatureFlags, SpeechInputButton_component, SpeechOutputAzureButton_component [INFERRED 0.85]
- **Parser implementations** — parser_Parser, jsonparser_JsonParser, textparser_TextParser, pdfparser_LocalPdfParser, pdfparser_DocumentAnalysisParser, xmlparser_XmlParser [EXTRACTED 1.00]
- **TextSplitter implementations** — textsplitter_TextSplitter, textsplitter_SentenceTextSplitter, textsplitter_CsvTextSplitter, textsplitter_SimpleTextSplitter [EXTRACTED 1.00]
- **Integrated vectorization ingestion pipeline** — integratedvectorizerstrategy_IntegratedVectorizerStrategy, listfilestrategy_ListFileStrategy, searchmanager_SearchManager, strategy_SearchInfo [EXTRACTED 1.00]
- **Internal Admin Auth API Module** — internalAdminApi_getInternalAdminSessionApi, internalAdminApi_loginInternalAdminApi, internalAdminApi_logoutInternalAdminApi [EXTRACTED 1.00]
- **Chatbot Directory Admin Panel** — ChatbotDirectory_ChatbotDirectory, chatbotDisplay_formatChatbotLabel, internalAdminApi_loginInternalAdminApi [INFERRED 0.85]
- **Root i18n Re-export Bridge to Nerilio** — config_rootI18nConfig, index_rootI18nIndex, LanguagePicker_rootLanguagePicker [EXTRACTED 1.00]
- **Internal Admin Panel (shared auth + cross-linked pages)** — useInternalAdminAccess_hook, internalToolsAccess_sessionStorageGate, ManagePromptsPage_component, PublicTestUsersPage_component, UploadFilesPage_component [EXTRACTED 0.95]
- **Document Extractor Azure Function Pipeline** — document_extractor_function_app, document_extractor_extract_route, document_extractor_process_document, document_extractor_get_file_acls, document_extractor_global_settings [EXTRACTED 0.95]
- **prepdocslib duplication: backend copy vs Azure Function copy** — docextractor_prepdocslib_copy, document_extractor_global_settings, document_extractor_process_document [EXTRACTED 0.90]
- **Azure Functions triggers in app/functions** — figure_processor_http_trigger, moodle_auto_indexer_moodle_trigger, moodle_auto_indexer_moodle_delete_trigger, moodle_auto_indexer_publishone_trigger, moodle_auto_indexer_publishone_delete_trigger [EXTRACTED 0.95]
- **Duplicated prepdocslib copies across functions** — backend_prepdocslib_module, document_extractor_prepdocslib_tree, figure_processor_prepdocslib_tree, prepdocslib_duplicate_trees [EXTRACTED 0.95]
- **Moodle/PublishOne auto-indexer feed pipeline** — moodle_auto_indexer_feed_definition, moodle_auto_indexer_build_auto_indexer, moodle_auto_indexer_handle_create_event, moodle_auto_indexer_handle_delete_event, prepdocslib_auto_blob_indexer_ref, prepdocslib_search_manager_ref, prepdocslib_publishone_feed_ref [EXTRACTED 0.90]
- **Figure Processor enrichment pipeline** — figure_processor_http_trigger, figure_processor_configure_global_settings, prepdocslib_blobmanager_class_ref, prepdocslib_figure_processor_class_ref, prepdocslib_image_embeddings_class_ref, prepdocslib_image_on_page_ref, prepdocslib_process_page_image_ref, prepdocslib_servicesetup_ref [EXTRACTED 0.90]
- **Text Processor Custom Skill Pipeline** — function_app_process_text_entry, function_app_process_document, prepdocslib_textprocessor_process_text, prepdocslib_page_Page, prepdocslib_page_ImageOnPage, prepdocslib_embeddings_OpenAIEmbeddings [EXTRACTED 0.90]
- **Azure Function Apps Family (shared prepdocslib pattern)** — function_app_text_processor, function_app_document_extractor, function_app_figure_processor, function_app_moodle_auto_indexer [INFERRED 0.80]
- **Eval framework (metrics + ground truth + safety)** — evaluate_module, generate_ground_truth_module, safety_evaluation_module, evaluate_any_citation_metric, evaluate_citations_matched_metric [INFERRED 0.90]
- **Auth setup toolchain (init + update + shared helpers + ps1 wrappers)** — auth_init_module, auth_update_module, auth_common_module, auth_init_ps1, auth_update_ps1 [EXTRACTED 0.95]
- **prepdocslib duplicated into 4 function apps by copy script** — copy_prepdocslib_module, backend_prepdocslib_source, document_extractor_prepdocslib_target, figure_processor_prepdocslib_target, moodle_auto_indexer_prepdocslib_target, text_processor_prepdocslib_target [EXTRACTED 1.00]
- **CosmosDB v1 to v2 schema migration** — cosmosdb_migrator_class, cosmosdb_old_container, cosmosdb_new_container, cosmosdb_migration_legacy_fn [EXTRACTED 1.00]
- **Entra/Graph server+client app registration flow** — auth_init_server_app_initial, auth_init_server_app_permission_setup, auth_init_client_app, auth_init_server_app_known_client_application, auth_init_grant_application_admin_consent [EXTRACTED 0.95]
- **Test Infrastructure (Conftest + Mocks + E2E)** — tests_conftest, tests_mocks, tests_e2e [INFERRED 0.90]
- **AZD Environment Setup Scripts** — load_azd_env_module, manageacl_script, verify_search_index_acls_module [INFERRED 0.85]
- **Chatbot Configuration Test Suite** — test_chatbot_config_registry, test_chatbotpromptstore, test_app_config [INFERRED 0.80]
- **Prepdocslib Parser Test Suite** — test_csvparser_module, test_htmlparser_module, test_jsonparser_module, test_pdfparser_module, test_textparser_module [INFERRED 0.90]
- **Prepdocslib Ingestion Pipeline Tests** — test_prepdocs_module, test_prepdocslib_filestrategy_module, test_prepdocslib_textsplitter_module, test_sentencetextsplitter_module, test_listfilestrategy_module, test_searchmanager_module, test_servicesetup_module [INFERRED 0.90]
- **Storage, CosmosDB and Migration Tests** — test_cosmosdb_module, test_cosmosdb_migration_module, test_content_file_module, test_delete_documents_by_category_module, test_migrate_storage_urls_to_category_paths_module, test_manageacl_module [INFERRED 0.85]
- **Agindo App Bootstrap Participants** — agindo_entryPoint, agindo_AppGate, agindo_LayoutWrapper, agindo_authConfig_msalConfig [EXTRACTED 1.00]
- **Root Router Chatbot Wiring** — index_router, registry_chatbotDefinitions, index_wrapChatbotElement [EXTRACTED 1.00]
- **Chat History Scoped API Calls** — chatHistoryScope_getCurrentChatbotName, api_postChatHistoryApi, api_getChatHistoryListApi, api_getChatHistoryApi, api_deleteChatHistoryApi [EXTRACTED 1.00]
- **Deployment Documentation Group** — doc_azd, doc_azure_app_service, doc_azure_container_apps [INFERRED 0.85]
- **Root Project Documentation** — readme_md, agents_md, contributing_md [INFERRED 0.85]
- **RAG Architecture Core Concepts** — concept_chat_read_retrieve_read, concept_chat_approach_rag, concept_agentic_retrieval [INFERRED 0.85]
- **Deployment Variants** — deploy_existing_doc, deploy_lowcost_doc, deploy_private_doc [EXTRACTED 0.90]
- **Ingestion Pipeline Stages** — data_ingestion_document_extraction, data_ingestion_figure_processing, data_ingestion_text_processing [EXTRACTED 0.95]
- **Auth & Access Control Topics** — login_acl_entra_apps, login_acl_adls_gen2, login_acl_builtin_access_control [EXTRACTED 0.90]
- **Evaluation Concepts** — evaluation_ground_truth, evaluation_bulk_run, safety_eval_metrics [EXTRACTED 0.85]
- **Text Splitter Components** — textsplitter_recursive_split, textsplitter_cross_page_repair, textsplitter_semantic_overlap [EXTRACTED 0.95]
- **Multimodal Stack** — multimodal_image_embeddings, svc_azure_ai_vision, data_ingestion_figure_processing [EXTRACTED 0.90]
- **Cloud Ingestion Custom Skills** — data_ingestion_indexer_architecture, svc_azure_functions, data_ingestion_shaper_skill [EXTRACTED 0.95]
- **HTTP Protocol Message Parts** — http_protocol_request_format, http_protocol_streaming, http_protocol_response_context [EXTRACTED 0.95]
- **Local Dev Modes** — localdev_hot_reload, localdev_vscode_tasks, localdev_local_openai [EXTRACTED 0.90]
- **Production Scaling Measures** — productionizing_openai_capacity, productionizing_loadtest_locust, deploy_features_openai_loadbalancer [EXTRACTED 0.85]
- **Multilingual PDF Test Fixtures** — ar_tribute_michael_hart_pdf, en_owl_creek_bridge_pdf, ja_rtl_toptobottom_test_pdf, ja_akuma_pdf, ko_city_mouse_pdf, zh_you_xue_qiong_lin_pdf [EXTRACTED 0.90]
- **Agindo Answer Component Suite** — Answer_agindo, AnswerLoading_agindo, AnswerError_agindo, AnswerIcon_agindo, AnswerParser_parseAnswerToHtml [INFERRED 0.85]
- **Agindo History UI Stack** — HistoryPanel_agindo, HistoryItem_agindo, HistoryButton_agindo [EXTRACTED 1.00]
- **Agindo Speech Output Variants** — SpeechOutputAzure_agindo, SpeechOutputBrowser_agindo, Answer_agindo [EXTRACTED 1.00]
- **History Provider implementations share IHistoryProvider contract** — cosmosdb_cosmosdbprovider, indexeddb_indexeddbprovider, none_noneprovider [EXTRACTED 1.00]
- **Agindo chat controls form the interactive UI surface** — questioninput_questioninput, speechinput_speechinput, uploadfile_uploadfile [INFERRED 0.75]
- **Settings button and Settings panel participate in developer configuration** — settingsbutton_settingsbutton, settings_settings, settings_settingsprops [INFERRED 0.80]
- **Agindo i18n Stack** — agindo_i18n_config, agindo_i18n_index, agindo_languagepicker, agindo_supportedlngs [EXTRACTED 0.90]
- **Agindo BasicAuth Flow** — agindo_basicauth, agindo_basiclogin, agindo_layout [EXTRACTED 0.95]
- **Demo Chatbot Bootstrap** — demo_chatbot_main, demo_layoutwrapper, demo_authconfig, demo_logincontext [EXTRACTED 0.90]

## Communities

### Community 0 - "Community 0"
Cohesion: 0.0
Nodes (913): a(), h(), R(), e(), fu(), _i(), _o(), pd() (+905 more)

### Community 1 - "Community 1"
Cohesion: 0.01
Nodes (460): ABC, cancel_managed_upload(), delete_managed_uploaded_file(), delete_managed_uploaded_files(), get_category_upload_manager(), JSONEncoder, list_managed_uploads(), LLMOnlySpanExporter (+452 more)

### Community 2 - "Community 2"
Cohesion: 0.01
Nodes (528): getCurrentProfile(), getCurrentSession(), isEmailValid(), normalizeEmail(), parseProfile(), parseSession(), readErrorKey(), readSessionResponse() (+520 more)

### Community 3 - "Community 3"
Cohesion: 0.01
Nodes (118): $2(), a7(), aE(), aG(), Ao(), B2(), bv(), by() (+110 more)

### Community 4 - "Community 4"
Cohesion: 0.01
Nodes (277): apply_saved_chatbot_prompt_override(), build_chat_model_deployments(), build_prompt_admin_payload(), cancel_chatbot_upload(), chat(), chat_stream(), chatbot_directory(), chatbot_entry() (+269 more)

### Community 5 - "Community 5"
Cohesion: 0.02
Nodes (237): ab(), Ac(), ad(), Ag(), ah(), Ai(), An(), ao() (+229 more)

### Community 6 - "Community 6"
Cohesion: 0.01
Nodes (123): AdlsGen2Setup, main(), Sets up a Data Lake Storage Gen 2 account with sample data and access control, Initializes the command          Parameters         ----------         data_, close_clients(), BaseMetric, Downloads a blob from Azure Blob Storage.          Args:             blob_pat, ChatbotPromptStore (+115 more)

### Community 7 - "Community 7"
Cohesion: 0.03
Nodes (206): FileProcessor, build_document_components(), configure_global_settings(), extract_document(), get_file_acls(), GlobalSettings, process_document(), process_figure_request() (+198 more)

### Community 8 - "Community 8"
Cohesion: 0.03
Nodes (64): getAuthenticatedUser(), isAuthenticated(), login(), logout(), InternalBasicAuthGate(), handleLockDirectory(), handleSubmit(), formatChatbotLabel() (+56 more)

### Community 9 - "Community 9"
Cohesion: 0.02
Nodes (107): Managed Identity & RBAC, RAG Chunking Pattern (token limits), Semantic Ranker, Vector Search (embeddings), Data Categorization (--category), Cloud Ingestion (Azure Functions Skills), Data Ingestion Guide, Document Extraction Stage (+99 more)

### Community 10 - "Community 10"
Cohesion: 0.07
Nodes (57): askApi(), cancelChatbotUploadApi(), chatApi(), configApi(), deleteAllChatbotUploadedFilesApi(), deleteChatbotUploadedFileApi(), deleteChatHistoryApi(), deleteUploadedFileApi() (+49 more)

### Community 11 - "Community 11"
Cohesion: 0.05
Nodes (9): zf(), Es(), gue(), Hn, Ji(), que(), rde, xue() (+1 more)

### Community 12 - "Community 12"
Cohesion: 0.06
Nodes (36): auth_setup(), AuthError, get_token_auth_header(), Validate an access token is issued by Entra, getSpeechRecognitionLocale(), getSpeechToken(), Decorator for routes that request a specific file that might require access cont, Decorator for routes that might require access control. Unpacks Authorization he (+28 more)

### Community 13 - "Community 13"
Cohesion: 0.14
Nodes (28): AutoBlobIndexer, AutoBlobIndexerConfig, AutoBlobIndexResult, blob_name_from_event_grid_subject(), build_file(), content_type_for_filename(), normalize_blob_name(), normalize_prefix() (+20 more)

### Community 14 - "Community 14"
Cohesion: 0.25
Nodes (38): append_tag(), build_document_content(), build_feed_document(), build_folder_context_lines(), build_publishone_feed_sections(), build_tags(), collect_direct_meta_fields(), collect_direct_value_fields() (+30 more)

### Community 15 - "Community 15"
Cohesion: 0.09
Nodes (18): CsvParser, Parse CSV-like tabular files into one Page per logical row.      Goals:     -, test_csvparser_empty_file(), test_csvparser_handles_semicolon_and_multiline_fields_with_metadata(), test_csvparser_multiple_rows_keep_row_boundaries_and_offsets(), test_csvparser_single_row_renders_labeled_record(), test_htmlparser_full(), test_htmlparser_remove_hyphens() (+10 more)

### Community 16 - "Community 16"
Cohesion: 0.29
Nodes (23): buildInitialAssistantPair(), buildInitialConversation(), clearChat(), createClientSessionId(), getConfig(), getCurrentSessionState(), getLastRealQuestion(), handleAsyncRequest() (+15 more)

### Community 17 - "Community 17"
Cohesion: 0.09
Nodes (33): get_application(), test_authentication_enabled(), add_client_secret(), client_app(), create_application(), create_or_update_application_with_secret(), grant_application_admin_consent(), GrantDefinition (+25 more)

### Community 18 - "Community 18"
Cohesion: 0.15
Nodes (13): Rm(), Vwe(), formatProfileDate(), globalClearChat(), handleBasicLogout(), handleClickOutside(), handleOpenRecentChats(), handleOpenUploadManager() (+5 more)

### Community 19 - "Community 19"
Cohesion: 0.09
Nodes (20): CosmosDBMigrator, migrate_cosmosdb_data(), A migration script to migrate data from CosmosDB to a new format. The old schem, Close the CosmosDB client., Legacy function for backward compatibility.     Migrate data from CosmosDB to a, Migrator class for CosmosDB data migration., Initialize the migrator with CosmosDB account and database.          Args:, Connect to CosmosDB and initialize containers. (+12 more)

### Community 20 - "Community 20"
Cohesion: 0.06
Nodes (2): useHistoryManager(), HistoryPanel()

### Community 21 - "Community 21"
Cohesion: 0.27
Nodes (23): build_chunk_texts(), build_metadata_lines(), FhgPreparedDataset, FhgPreparedDocument, get_optional_string_field(), get_text_field(), make_sourcepage_value(), prepare_fhg_dataset() (+15 more)

### Community 22 - "Community 22"
Cohesion: 0.08
Nodes (23): Adding a New azd Environment Variable Guide, Adding New Data Guide, Adding a New Developer Setting Guide, Adding Tests for a New Feature Guide, Overall Code Layout Guide, Python Code Style Guide, Deploying the Application Guide, AGENTS.md - Coding Agent Instructions (+15 more)

### Community 23 - "Community 23"
Cohesion: 0.51
Nodes (8): appServicesLogout(), checkLoggedIn(), fetchAuthSetup(), getAppServicesToken(), getRedirectUri(), getToken(), getTokenClaims(), getUsername()

### Community 24 - "Community 24"
Cohesion: 0.15
Nodes (2): j7(), Y7

### Community 25 - "Community 25"
Cohesion: 0.47
Nodes (6): buildActivityStepMap(), collectCitations(), extractCitationDetails(), isWebCitation(), normalizeAnswerText(), parseAnswerToHtml()

### Community 26 - "Community 26"
Cohesion: 0.46
Nodes (6): handleCompositionEnd(), handleCompositionStart(), onEnterPress(), onQuestionChange(), sendQuestion(), StopCircleIcon()

### Community 27 - "Community 27"
Cohesion: 0.27
Nodes (17): createPageGradient(), createSurfaceColor(), darken(), getChatbotTheme(), getChatbotThemeCssVariables(), getContrastRatio(), getReadableText(), getRelativeLuminance() (+9 more)

### Community 28 - "Community 28"
Cohesion: 0.2
Nodes (1): dO

### Community 29 - "Community 29"
Cohesion: 0.31
Nodes (3): onRetrievalModeChange(), onSearchImageEmbeddingsChange(), onSearchTextEmbeddingsChange()

### Community 30 - "Community 30"
Cohesion: 0.24
Nodes (2): getResultsForStep(), getStepQuery()

### Community 31 - "Community 31"
Cohesion: 0.12
Nodes (1): renderLabel()

### Community 32 - "Community 32"
Cohesion: 0.13
Nodes (1): AnalysisPanel()

### Community 33 - "Community 33"
Cohesion: 0.13
Nodes (1): AnswerError()

### Community 34 - "Community 34"
Cohesion: 0.13
Nodes (1): AnswerIcon()

### Community 35 - "Community 35"
Cohesion: 0.13
Nodes (1): startOrStopSpeech()

### Community 36 - "Community 36"
Cohesion: 0.13
Nodes (1): ClearChatButton()

### Community 37 - "Community 37"
Cohesion: 0.13
Nodes (1): HistoryButton()

### Community 38 - "Community 38"
Cohesion: 0.13
Nodes (1): HistoryItem()

### Community 39 - "Community 39"
Cohesion: 0.13
Nodes (1): LoginButton()

### Community 40 - "Community 40"
Cohesion: 0.13
Nodes (1): SpeechInput()

### Community 41 - "Community 41"
Cohesion: 0.13
Nodes (1): SettingsButton()

### Community 42 - "Community 42"
Cohesion: 0.13
Nodes (1): parseSupportingContentItem()

### Community 43 - "Community 43"
Cohesion: 0.13
Nodes (1): UserChatMessage()

### Community 44 - "Community 44"
Cohesion: 0.13
Nodes (1): LanguagePicker()

### Community 45 - "Community 45"
Cohesion: 0.14
Nodes (1): getStepLabel()

### Community 46 - "Community 46"
Cohesion: 0.14
Nodes (1): truncateImageUrl()

### Community 47 - "Community 47"
Cohesion: 0.27
Nodes (4): buildActivityStepMap(), collectCitations(), normalizeAnswerText(), parseAnswerToMarkdown()

### Community 48 - "Community 48"
Cohesion: 0.2
Nodes (10): System Architecture Diagram, Chat Query Flow, ChatReadRetrieveRead Approach, Deployment Options (Container Apps vs App Service), Document Ingestion Flow, RAG Chat Application Architecture, App Features List, README.md - RAG Chat App Overview (+2 more)

### Community 51 - "Community 51"
Cohesion: 0.5
Nodes (4): Agentic Retrieval (Azure AI Search LLM query planning), Web and SharePoint Knowledge Sources, Retrieval Reasoning Effort (minimal/low/medium), Agentic Retrieval Guide

### Community 52 - "Community 52"
Cohesion: 0.5
Nodes (4): DEPLOYMENT_TARGET azd env var, Container Apps Workload Profile, Deploying on Azure App Service, Deploying on Azure Container Apps

### Community 53 - "Community 53"
Cohesion: 0.67
Nodes (3): QueryPlanStep type, activityTypeLabels, getStepLabel()

### Community 55 - "Community 55"
Cohesion: 0.67
Nodes (3): Deployment Logs & Debugging, Oryx Build Process, Debugging App Service Deployments

### Community 56 - "Community 56"
Cohesion: 0.67
Nodes (3): azd up workflow (hooks, provisioning, deploy), Continuous Deployment (GH Actions / Azure DevOps), Azure Developer CLI Deployment Guide

### Community 57 - "Community 57"
Cohesion: 1.0
Nodes (1): Knoll chatbot prompt package.

### Community 59 - "Community 59"
Cohesion: 1.0
Nodes (2): AnalysisPanelTabs enum, AnalysisPanel barrel (demo)

### Community 60 - "Community 60"
Cohesion: 1.0
Nodes (2): ThoughtProcess component (demo), truncateImageUrl helper

### Community 70 - "Community 70"
Cohesion: 1.0
Nodes (2): Graphify Integration Rules, CLAUDE.md - Claude Agent Rules

### Community 71 - "Community 71"
Cohesion: 1.0
Nodes (2): Simple Figure expected content (figure extraction fixture), Simple Figure PDF (figure extraction fixture)

### Community 72 - "Community 72"
Cohesion: 1.0
Nodes (2): Simple HTML Table expected content (table extraction fixture), Simple Table PDF (table extraction fixture)

### Community 73 - "Community 73"
Cohesion: 1.0
Nodes (1): Answer component (demo)

### Community 75 - "Community 75"
Cohesion: 1.0
Nodes (1): internal_admin_required decorator

### Community 76 - "Community 76"
Cohesion: 1.0
Nodes (1): app/backend/delete_documents_by_category.py

### Community 77 - "Community 77"
Cohesion: 1.0
Nodes (1): Error Response Module

### Community 680 - "Community 680"
Cohesion: 1.0
Nodes (1): Make requests to provided url until it responds without error.

### Community 681 - "Community 681"
Cohesion: 1.0
Nodes (1): Returns a free port for the test server to bind.

### Community 682 - "Community 682"
Cohesion: 1.0
Nodes (1): Test that the stop button feature works without breaking the chat flow.      N

### Community 683 - "Community 683"
Cohesion: 1.0
Nodes (1): Test that when streaming returns no content, the question is restored to input.

### Community 684 - "Community 684"
Cohesion: 1.0
Nodes (1): Test that selecting 'Minimal' effort deselects and disables the web source check

### Community 685 - "Community 685"
Cohesion: 1.0
Nodes (1): Return a dict of chatbot_name → ChatbotConfig for all bots that have a config.py

### Community 686 - "Community 686"
Cohesion: 1.0
Nodes (1): Test that selecting 'Minimal' effort deselects and disables the web source check

### Community 687 - "Community 687"
Cohesion: 1.0
Nodes (1): Test that selecting 'Minimal' effort deselects and disables the web source check

### Community 688 - "Community 688"
Cohesion: 1.0
Nodes (1): Get path to current azd env file and load file using python-dotenv

### Community 689 - "Community 689"
Cohesion: 1.0
Nodes (1): Return a dict of chatbot_name → ChatbotConfig for all bots that have a config.py

### Community 690 - "Community 690"
Cohesion: 1.0
Nodes (1): Builds OpenAI chat completion messages from Jinja2 templates.

### Community 691 - "Community 691"
Cohesion: 1.0
Nodes (1): Build a single system message. Use for simple prompts like query rewrite.

### Community 692 - "Community 692"
Cohesion: 1.0
Nodes (1): Build a single user message with optional images.          Args:

### Community 693 - "Community 693"
Cohesion: 1.0
Nodes (1): Build a full conversation with system, history, and user message.          Arg

### Community 694 - "Community 694"
Cohesion: 1.0
Nodes (1): Load tools from a JSON file.

### Community 698 - "Community 698"
Cohesion: 1.0
Nodes (1): safety_results.json output

### Community 700 - "Community 700"
Cohesion: 1.0
Nodes (1): app/backend/requirements.txt

### Community 701 - "Community 701"
Cohesion: 1.0
Nodes (1): SECURITY.md - Microsoft Security Policy

### Community 702 - "Community 702"
Cohesion: 1.0
Nodes (1): requirements-dev.txt (ruff, black, pytest, playwright)

### Community 703 - "Community 703"
Cohesion: 1.0
Nodes (1): app/backend/requirements.txt (backend deps)

### Community 704 - "Community 704"
Cohesion: 1.0
Nodes (1): document_extractor function requirements

### Community 705 - "Community 705"
Cohesion: 1.0
Nodes (1): figure_processor function requirements

### Community 706 - "Community 706"
Cohesion: 1.0
Nodes (1): moodle_auto_indexer function requirements

### Community 707 - "Community 707"
Cohesion: 1.0
Nodes (1): text_processor function requirements

### Community 708 - "Community 708"
Cohesion: 1.0
Nodes (1): Text Splitter Sections Snapshot (sentence splitter list parse)

### Community 709 - "Community 709"
Cohesion: 1.0
Nodes (1): Arabic PDF fixture - Tribute to Michael Hart (RTL/Arabic multilingual test)

### Community 710 - "Community 710"
Cohesion: 1.0
Nodes (1): English PDF fixture - An Occurrence at Owl Creek Bridge (literature sample)

### Community 711 - "Community 711"
Cohesion: 1.0
Nodes (1): Financial Market Analysis Report 2023 (technical doc fixture)

### Community 712 - "Community 712"
Cohesion: 1.0
Nodes (1): Japanese RTL Top-To-Bottom layout test PDF fixture

### Community 713 - "Community 713"
Cohesion: 1.0
Nodes (1): Japanese PDF fixture - 悪魔 (Akuma) literature sample

### Community 714 - "Community 714"
Cohesion: 1.0
Nodes (1): Korean PDF fixture - 도시로 간 쥐 (City Mouse) literature sample

### Community 715 - "Community 715"
Cohesion: 1.0
Nodes (1): Chinese PDF fixture - You Xue Qiong Lin (幼學瓊林) literature sample

### Community 716 - "Community 716"
Cohesion: 1.0
Nodes (1): agindo-chatbot.png asset

## Knowledge Gaps
- **205 isolated node(s):** `ChatUser Locust Load Test`, `/chat JSON API contract`, `authenticated decorator`, `internal_admin_required decorator`, `app/backend/delete_documents_by_category.py` (+200 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 20`** (32 nodes): `HistoryPanel.tsx`, `HistoryManager.ts`, `HistoryPanel.tsx`, `HistoryManager.ts`, `HistoryPanel.tsx`, `HistoryManager.ts`, `HistoryPanel.tsx`, `HistoryManager.ts`, `HistoryPanel.tsx`, `HistoryManager.ts`, `HistoryPanel.tsx`, `HistoryManager.ts`, `HistoryPanel.tsx`, `HistoryManager.ts`, `HistoryPanel.tsx`, `HistoryManager.ts`, `HistoryPanel.tsx`, `HistoryManager.ts`, `HistoryPanel.tsx`, `HistoryManager.ts`, `HistoryPanel.tsx`, `HistoryManager.ts`, `HistoryPanel.tsx`, `HistoryManager.ts`, `HistoryPanel.tsx`, `HistoryManager.ts`, `HistoryPanel.tsx`, `HistoryManager.ts`, `getPublicTestUserScope()`, `getRakUserScope()`, `useHistoryManager()`, `HistoryPanel()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 24`** (22 nodes): `j7()`, `.closeConnection()`, `.constructor()`, `.containsKey()`, `.deleteDatabase()`, `.getItem()`, `.getKeys()`, `.open()`, `.removeItem()`, `.setItem()`, `.validateDbIsOpen()`, `.clearKeystore()`, `Y7`, `.clearInMemory()`, `.clearPersistent()`, `.constructor()`, `.containsKey()`, `.getItem()`, `.getKeys()`, `.handleDatabaseAccessError()`, `.removeItem()`, `.setItem()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 28`** (17 nodes): `dO`, `.addNamespaces()`, `.addResource()`, `.addResourceBundle()`, `.addResources()`, `.constructor()`, `.getDataByLanguage()`, `.getResourceBundle()`, `.hasLanguageSomeTranslations()`, `.hasResourceBundle()`, `.removeNamespaces()`, `.removeResourceBundle()`, `.toJSON()`, `.emit()`, `.loaded()`, `.getResource()`, `.setResolvedLanguage()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 30`** (16 nodes): `getResultsForStep()`, `getStepQuery()`, `AgentPlan.tsx`, `AgentPlan.tsx`, `AgentPlan.tsx`, `AgentPlan.tsx`, `AgentPlan.tsx`, `AgentPlan.tsx`, `AgentPlan.tsx`, `AgentPlan.tsx`, `AgentPlan.tsx`, `AgentPlan.tsx`, `AgentPlan.tsx`, `AgentPlan.tsx`, `AgentPlan.tsx`, `AgentPlan.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 31`** (16 nodes): `Settings.tsx`, `Settings.tsx`, `Settings.tsx`, `Settings.tsx`, `Settings.tsx`, `Settings.tsx`, `Settings.tsx`, `Settings.tsx`, `Settings.tsx`, `Settings.tsx`, `Settings.tsx`, `Settings.tsx`, `Settings.tsx`, `Settings.tsx`, `Settings.tsx`, `renderLabel()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 32`** (15 nodes): `AnalysisPanel()`, `AnalysisPanel.tsx`, `AnalysisPanel.tsx`, `AnalysisPanel.tsx`, `AnalysisPanel.tsx`, `AnalysisPanel.tsx`, `AnalysisPanel.tsx`, `AnalysisPanel.tsx`, `AnalysisPanel.tsx`, `AnalysisPanel.tsx`, `AnalysisPanel.tsx`, `AnalysisPanel.tsx`, `AnalysisPanel.tsx`, `AnalysisPanel.tsx`, `AnalysisPanel.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 33`** (15 nodes): `AnswerError()`, `AnswerError.tsx`, `AnswerError.tsx`, `AnswerError.tsx`, `AnswerError.tsx`, `AnswerError.tsx`, `AnswerError.tsx`, `AnswerError.tsx`, `AnswerError.tsx`, `AnswerError.tsx`, `AnswerError.tsx`, `AnswerError.tsx`, `AnswerError.tsx`, `AnswerError.tsx`, `AnswerError.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 34`** (15 nodes): `AnswerIcon()`, `AnswerIcon.tsx`, `AnswerIcon.tsx`, `AnswerIcon.tsx`, `AnswerIcon.tsx`, `AnswerIcon.tsx`, `AnswerIcon.tsx`, `AnswerIcon.tsx`, `AnswerIcon.tsx`, `AnswerIcon.tsx`, `AnswerIcon.tsx`, `AnswerIcon.tsx`, `AnswerIcon.tsx`, `AnswerIcon.tsx`, `AnswerIcon.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 35`** (15 nodes): `SpeechOutputBrowser.tsx`, `SpeechOutputBrowser.tsx`, `SpeechOutputBrowser.tsx`, `SpeechOutputBrowser.tsx`, `SpeechOutputBrowser.tsx`, `SpeechOutputBrowser.tsx`, `SpeechOutputBrowser.tsx`, `SpeechOutputBrowser.tsx`, `SpeechOutputBrowser.tsx`, `SpeechOutputBrowser.tsx`, `SpeechOutputBrowser.tsx`, `SpeechOutputBrowser.tsx`, `SpeechOutputBrowser.tsx`, `SpeechOutputBrowser.tsx`, `startOrStopSpeech()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 36`** (15 nodes): `ClearChatButton.tsx`, `ClearChatButton.tsx`, `ClearChatButton.tsx`, `ClearChatButton.tsx`, `ClearChatButton.tsx`, `ClearChatButton.tsx`, `ClearChatButton.tsx`, `ClearChatButton.tsx`, `ClearChatButton.tsx`, `ClearChatButton.tsx`, `ClearChatButton.tsx`, `ClearChatButton.tsx`, `ClearChatButton.tsx`, `ClearChatButton.tsx`, `ClearChatButton()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 37`** (15 nodes): `HistoryButton.tsx`, `HistoryButton.tsx`, `HistoryButton.tsx`, `HistoryButton.tsx`, `HistoryButton.tsx`, `HistoryButton.tsx`, `HistoryButton.tsx`, `HistoryButton.tsx`, `HistoryButton.tsx`, `HistoryButton.tsx`, `HistoryButton.tsx`, `HistoryButton.tsx`, `HistoryButton.tsx`, `HistoryButton.tsx`, `HistoryButton()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 38`** (15 nodes): `HistoryItem.tsx`, `HistoryItem.tsx`, `HistoryItem.tsx`, `HistoryItem.tsx`, `HistoryItem.tsx`, `HistoryItem.tsx`, `HistoryItem.tsx`, `HistoryItem.tsx`, `HistoryItem.tsx`, `HistoryItem.tsx`, `HistoryItem.tsx`, `HistoryItem.tsx`, `HistoryItem.tsx`, `HistoryItem.tsx`, `HistoryItem()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 39`** (15 nodes): `LoginButton.tsx`, `LoginButton.tsx`, `LoginButton.tsx`, `LoginButton.tsx`, `LoginButton.tsx`, `LoginButton.tsx`, `LoginButton.tsx`, `LoginButton.tsx`, `LoginButton.tsx`, `LoginButton.tsx`, `LoginButton.tsx`, `LoginButton.tsx`, `LoginButton.tsx`, `LoginButton.tsx`, `LoginButton()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 40`** (15 nodes): `SpeechInput.tsx`, `SpeechInput.tsx`, `SpeechInput.tsx`, `SpeechInput.tsx`, `SpeechInput.tsx`, `SpeechInput.tsx`, `SpeechInput.tsx`, `SpeechInput.tsx`, `SpeechInput.tsx`, `SpeechInput.tsx`, `SpeechInput.tsx`, `SpeechInput.tsx`, `SpeechInput.tsx`, `SpeechInput.tsx`, `SpeechInput()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 41`** (15 nodes): `SettingsButton.tsx`, `SettingsButton.tsx`, `SettingsButton.tsx`, `SettingsButton.tsx`, `SettingsButton.tsx`, `SettingsButton.tsx`, `SettingsButton.tsx`, `SettingsButton.tsx`, `SettingsButton.tsx`, `SettingsButton.tsx`, `SettingsButton.tsx`, `SettingsButton.tsx`, `SettingsButton.tsx`, `SettingsButton.tsx`, `SettingsButton()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 42`** (15 nodes): `SupportingContentParser.ts`, `SupportingContentParser.ts`, `SupportingContentParser.ts`, `SupportingContentParser.ts`, `SupportingContentParser.ts`, `SupportingContentParser.ts`, `SupportingContentParser.ts`, `SupportingContentParser.ts`, `SupportingContentParser.ts`, `SupportingContentParser.ts`, `SupportingContentParser.ts`, `SupportingContentParser.ts`, `SupportingContentParser.ts`, `SupportingContentParser.ts`, `parseSupportingContentItem()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 43`** (15 nodes): `UserChatMessage.tsx`, `UserChatMessage.tsx`, `UserChatMessage.tsx`, `UserChatMessage.tsx`, `UserChatMessage.tsx`, `UserChatMessage.tsx`, `UserChatMessage.tsx`, `UserChatMessage.tsx`, `UserChatMessage.tsx`, `UserChatMessage.tsx`, `UserChatMessage.tsx`, `UserChatMessage.tsx`, `UserChatMessage.tsx`, `UserChatMessage.tsx`, `UserChatMessage()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 44`** (15 nodes): `LanguagePicker.tsx`, `LanguagePicker.tsx`, `LanguagePicker.tsx`, `LanguagePicker.tsx`, `LanguagePicker.tsx`, `LanguagePicker.tsx`, `LanguagePicker.tsx`, `LanguagePicker.tsx`, `LanguagePicker.tsx`, `LanguagePicker.tsx`, `LanguagePicker.tsx`, `LanguagePicker.tsx`, `LanguagePicker.tsx`, `LanguagePicker.tsx`, `LanguagePicker()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 45`** (14 nodes): `getStepLabel()`, `agentPlanUtils.ts`, `agentPlanUtils.ts`, `agentPlanUtils.ts`, `agentPlanUtils.ts`, `agentPlanUtils.ts`, `agentPlanUtils.ts`, `agentPlanUtils.ts`, `agentPlanUtils.ts`, `agentPlanUtils.ts`, `agentPlanUtils.ts`, `agentPlanUtils.ts`, `agentPlanUtils.ts`, `agentPlanUtils.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 46`** (14 nodes): `ThoughtProcess.tsx`, `ThoughtProcess.tsx`, `ThoughtProcess.tsx`, `ThoughtProcess.tsx`, `ThoughtProcess.tsx`, `ThoughtProcess.tsx`, `ThoughtProcess.tsx`, `ThoughtProcess.tsx`, `ThoughtProcess.tsx`, `ThoughtProcess.tsx`, `ThoughtProcess.tsx`, `ThoughtProcess.tsx`, `ThoughtProcess.tsx`, `truncateImageUrl()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 57`** (2 nodes): `__init__.py`, `Knoll chatbot prompt package.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 59`** (2 nodes): `AnalysisPanelTabs enum`, `AnalysisPanel barrel (demo)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 60`** (2 nodes): `ThoughtProcess component (demo)`, `truncateImageUrl helper`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 70`** (2 nodes): `Graphify Integration Rules`, `CLAUDE.md - Claude Agent Rules`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 71`** (2 nodes): `Simple Figure expected content (figure extraction fixture)`, `Simple Figure PDF (figure extraction fixture)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 72`** (2 nodes): `Simple HTML Table expected content (table extraction fixture)`, `Simple Table PDF (table extraction fixture)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 73`** (1 nodes): `Answer component (demo)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 75`** (1 nodes): `internal_admin_required decorator`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 76`** (1 nodes): `app/backend/delete_documents_by_category.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 77`** (1 nodes): `Error Response Module`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 680`** (1 nodes): `Make requests to provided url until it responds without error.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 681`** (1 nodes): `Returns a free port for the test server to bind.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 682`** (1 nodes): `Test that the stop button feature works without breaking the chat flow.      N`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 683`** (1 nodes): `Test that when streaming returns no content, the question is restored to input.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 684`** (1 nodes): `Test that selecting 'Minimal' effort deselects and disables the web source check`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 685`** (1 nodes): `Return a dict of chatbot_name → ChatbotConfig for all bots that have a config.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 686`** (1 nodes): `Test that selecting 'Minimal' effort deselects and disables the web source check`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 687`** (1 nodes): `Test that selecting 'Minimal' effort deselects and disables the web source check`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 688`** (1 nodes): `Get path to current azd env file and load file using python-dotenv`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 689`** (1 nodes): `Return a dict of chatbot_name → ChatbotConfig for all bots that have a config.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 690`** (1 nodes): `Builds OpenAI chat completion messages from Jinja2 templates.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 691`** (1 nodes): `Build a single system message. Use for simple prompts like query rewrite.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 692`** (1 nodes): `Build a single user message with optional images.          Args:`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 693`** (1 nodes): `Build a full conversation with system, history, and user message.          Arg`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 694`** (1 nodes): `Load tools from a JSON file.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 698`** (1 nodes): `safety_results.json output`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 700`** (1 nodes): `app/backend/requirements.txt`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 701`** (1 nodes): `SECURITY.md - Microsoft Security Policy`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 702`** (1 nodes): `requirements-dev.txt (ruff, black, pytest, playwright)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 703`** (1 nodes): `app/backend/requirements.txt (backend deps)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 704`** (1 nodes): `document_extractor function requirements`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 705`** (1 nodes): `figure_processor function requirements`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 706`** (1 nodes): `moodle_auto_indexer function requirements`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 707`** (1 nodes): `text_processor function requirements`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 708`** (1 nodes): `Text Splitter Sections Snapshot (sentence splitter list parse)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 709`** (1 nodes): `Arabic PDF fixture - Tribute to Michael Hart (RTL/Arabic multilingual test)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 710`** (1 nodes): `English PDF fixture - An Occurrence at Owl Creek Bridge (literature sample)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 711`** (1 nodes): `Financial Market Analysis Report 2023 (technical doc fixture)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 712`** (1 nodes): `Japanese RTL Top-To-Bottom layout test PDF fixture`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 713`** (1 nodes): `Japanese PDF fixture - 悪魔 (Akuma) literature sample`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 714`** (1 nodes): `Korean PDF fixture - 도시로 간 쥐 (City Mouse) literature sample`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 715`** (1 nodes): `Chinese PDF fixture - You Xue Qiong Lin (幼學瓊林) literature sample`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 716`** (1 nodes): `agindo-chatbot.png asset`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `set()` connect `Community 3` to `Community 0`, `Community 1`, `Community 2`, `Community 4`, `Community 6`, `Community 7`, `Community 8`, `Community 10`, `Community 14`, `Community 15`?**
  _High betweenness centrality (0.080) - this node is a cross-community bridge._
- **Why does `update()` connect `Community 4` to `Community 0`, `Community 1`, `Community 5`, `Community 7`?**
  _High betweenness centrality (0.029) - this node is a cross-community bridge._
- **Why does `vB()` connect `Community 3` to `Community 0`, `Community 2`?**
  _High betweenness centrality (0.026) - this node is a cross-community bridge._
- **Are the 84 inferred relationships involving `nT` (e.g. with `zw()` and `ix()`) actually correct?**
  _`nT` has 84 INFERRED edges - model-reasoned connections that need verification._
- **Are the 72 inferred relationships involving `set()` (e.g. with `save_internal_admin_prompt()` and `delete_internal_admin_prompt()`) actually correct?**
  _`set()` has 72 INFERRED edges - model-reasoned connections that need verification._
- **Are the 117 inferred relationships involving `BlobManager` (e.g. with `StorageUrlMigration` and `AutoBlobIndexerConfig`) actually correct?**
  _`BlobManager` has 117 INFERRED edges - model-reasoned connections that need verification._
- **Are the 121 inferred relationships involving `SentenceTextSplitter` (e.g. with `FhgPreparedDocument` and `FhgPreparedDataset`) actually correct?**
  _`SentenceTextSplitter` has 121 INFERRED edges - model-reasoned connections that need verification._