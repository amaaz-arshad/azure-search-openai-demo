import { useRef, useState, useEffect, useContext } from "react";
import { ScrollToBottomButton } from "../../../shared/scroll/ScrollToBottomButton";
import { useTranslation } from "react-i18next";
import { Helmet } from "react-helmet-async";
import { useOutletContext } from "react-router-dom";
import { Panel, DefaultButton } from "@fluentui/react";
import hyroxLogo from "../../assets/HYROX.svg";
import styles from "./Chat.module.css";

import { chatApi, configApi, RetrievalMode, ChatAppResponse, ChatAppResponseOrError, ChatAppRequest, ResponseMessage, SpeechConfig } from "../../api";
import {
    Answer,
    AnswerError,
    AnswerLoading,
    splitAssessmentBubbles,
    parseProgressValue,
    hasAssessmentDoneMarker,
    hasModulePassMarker,
    hasModuleFailMarker
} from "../../components/Answer";
import { QuestionInput } from "../../components/QuestionInput";
import { ExampleList } from "../../components/Example";
import { UserChatMessage } from "../../components/UserChatMessage";
import { AnalysisPanel, AnalysisPanelTabs } from "../../components/AnalysisPanel";
import { HistoryPanel } from "../../components/HistoryPanel";
import { HistoryProviderOptions, useHistoryManager } from "../../components/HistoryProviders";
import { HistoryButton } from "../../components/HistoryButton";
import { SettingsButton } from "../../components/SettingsButton";
import { ClearChatButton } from "../../components/ClearChatButton";
import { UploadFile } from "../../components/UploadFile";
import { useLogin, getToken, requireAccessControl } from "../../authConfig";
import { useMsal } from "@azure/msal-react";
import { TokenClaimsDisplay } from "../../components/TokenClaimsDisplay";
import { LoginContext } from "../../loginContext";
import { Settings } from "../../components/Settings/Settings";
import { setGlobalClearChat } from "../layout/Layout";
import { applyChatbotSpeechFeatureFlags } from "../../../shared/speech/chatbotSpeechFeatureFlags";
import { getLemonUserScope, readLemonAccount, reportLemonProgress, reportWebFrontendCompletion } from "../../lemonBridge";
import { readActiveSessionId, writeActiveSessionId, clearActiveSessionId } from "../../../shared/history/activeSession";

const INITIAL_ASSISTANT_SENTINEL_USER_MESSAGE = "__initial_assistant__";
const HYROX_ASSESSMENT_LANGUAGE = "en";

const createClientSessionId = () => {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
        return crypto.randomUUID();
    }

    return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
};

const Chat = () => {
    const { t } = useTranslation();
    const chatbotCategory = "hyrox-assessment";
    // Learner identity handed in by the Lemon app on the launch URL
    // (?account_id=...&first_name=...&last_name=...). Read once and kept stable for the
    // component's lifetime so it is sent with every request and used to personalize the greeting.
    const lemonAccountRef = useRef(readLemonAccount());
    const lemonAccount = lemonAccountRef.current;
    // Per-learner storage scope (account_id from the launch URL) so two users on a shared computer
    // never resume each other's assessment. Missing id → "anonymous" (shared), matching the DB-name
    // scope in useHistoryManager so the active-session pointer and the IndexedDB store agree.
    const userStorageScope = getLemonUserScope(lemonAccount);
    // Fire the lemon://save_progress hand-off exactly once per session, on the freshly
    // received passed-completion response (not on history replay).
    const progressReportedRef = useRef<boolean>(false);
    const legacyInitialUserMessage: string = t("initialUserMsg");
    const baseInitialAssistantMessage: string = t("initialAssistantMsg");
    const initialAssistantMessageContent: string = lemonAccount.firstName
        ? `${t("greeting", { firstName: lemonAccount.firstName })}${baseInitialAssistantMessage}`
        : baseInitialAssistantMessage;
    const initialAssistantResponse: ChatAppResponse = {
        message: {
            content: initialAssistantMessageContent,
            role: "assistant"
        },
        delta: {
            content: initialAssistantMessageContent,
            role: "assistant"
        },
        session_state: null
    };
    const initialAssistantPair: [user: string, response: ChatAppResponse] = [INITIAL_ASSISTANT_SENTINEL_USER_MESSAGE, initialAssistantResponse];
    const [isConfigPanelOpen, setIsConfigPanelOpen] = useState(false);
    const [isHistoryPanelOpen, setIsHistoryPanelOpen] = useState(false);
    const [promptTemplate, setPromptTemplate] = useState<string>("");
    const [temperature, setTemperature] = useState<number>(0);
    const [seed, setSeed] = useState<number | null>(null);
    const [minimumRerankerScore, setMinimumRerankerScore] = useState<number>(1);
    const [minimumSearchScore, setMinimumSearchScore] = useState<number>(0);
    const [retrieveCount, setRetrieveCount] = useState<number>(5);
    const [agenticReasoningEffort, setRetrievalReasoningEffort] = useState<string>("minimal");
    const [retrievalMode, setRetrievalMode] = useState<RetrievalMode>(RetrievalMode.Hybrid);
    const [useSemanticRanker, setUseSemanticRanker] = useState<boolean>(true);
    const [useQueryRewriting, setUseQueryRewriting] = useState<boolean>(false);
    const [reasoningEffort, setReasoningEffort] = useState<string>("");
    // The assessment runs non-streaming so the backend sees each complete message in one
    // place to parse the hidden score/result markers and write the session log.
    const [streamingEnabled, setStreamingEnabled] = useState<boolean>(false);
    const [shouldStream, setShouldStream] = useState<boolean>(false);
    const previousShouldStreamRef = useRef<boolean>(false);
    const forcedStreamingRef = useRef<boolean>(false);
    const [useSemanticCaptions, setUseSemanticCaptions] = useState<boolean>(false);
    const [includeCategory, setIncludeCategory] = useState<string>("");
    const [excludeCategory, setExcludeCategory] = useState<string>("");
    const [useSuggestFollowupQuestions, setUseSuggestFollowupQuestions] = useState<boolean>(false);
    const [searchTextEmbeddings, setSearchTextEmbeddings] = useState<boolean>(true);
    const [searchImageEmbeddings, setSearchImageEmbeddings] = useState<boolean>(false);
    const [sendTextSources, setSendTextSources] = useState<boolean>(true);
    const [sendImageSources, setSendImageSources] = useState<boolean>(false);

    const lastQuestionRef = useRef<string>("");
    const chatMessageStreamEnd = useRef<HTMLDivElement | null>(null);
    const chatContainerRef = useRef<HTMLDivElement | null>(null);
    const localHistorySessionIdRef = useRef<string | null>(null);
    const hasRestoredSessionRef = useRef<boolean>(false);

    const [isLoading, setIsLoading] = useState<boolean>(false);
    const [isStreaming, setIsStreaming] = useState<boolean>(false);
    const [abortController, setAbortController] = useState<AbortController | null>(null);
    const [restoredQuestion, setRestoredQuestion] = useState<string>("");
    const [error, setError] = useState<unknown>();

    const [activeCitation, setActiveCitation] = useState<string>();
    const [activeAnalysisPanelTab, setActiveAnalysisPanelTab] = useState<AnalysisPanelTabs | undefined>(undefined);

    const [selectedAnswer, setSelectedAnswer] = useState<number>(0);
    const [answers, setAnswers] = useState<[user: string, response: ChatAppResponse][]>([initialAssistantPair]);
    const [streamedAnswers, setStreamedAnswers] = useState<[user: string, response: ChatAppResponse][]>([initialAssistantPair]);
    const [speechUrls, setSpeechUrls] = useState<(string | null)[]>([]);

    const [showMultimodalOptions, setShowMultimodalOptions] = useState<boolean>(false);
    const [showSemanticRankerOption, setShowSemanticRankerOption] = useState<boolean>(false);
    const [showQueryRewritingOption, setShowQueryRewritingOption] = useState<boolean>(false);
    const [showReasoningEffortOption, setShowReasoningEffortOption] = useState<boolean>(false);
    const [showVectorOption, setShowVectorOption] = useState<boolean>(false);
    const [showUserUpload, setShowUserUpload] = useState<boolean>(false);
    const [showSpeechInput, setShowSpeechInput] = useState<boolean>(false);
    const [showSpeechOutputBrowser, setShowSpeechOutputBrowser] = useState<boolean>(false);
    const [showSpeechOutputAzure, setShowSpeechOutputAzure] = useState<boolean>(false);
    const [showChatHistoryBrowser, setShowChatHistoryBrowser] = useState<boolean>(false);
    const [showChatHistoryCosmos, setShowChatHistoryCosmos] = useState<boolean>(false);
    const [showAgenticRetrievalOption, setShowAgenticRetrievalOption] = useState<boolean>(false);
    const [webSourceSupported, setWebSourceSupported] = useState<boolean>(false);
    const [webSourceEnabled, setWebSourceEnabled] = useState<boolean>(false);
    const [sharePointSourceSupported, setSharePointSourceSupported] = useState<boolean>(false);
    const [sharePointSourceEnabled, setSharePointSourceEnabled] = useState<boolean>(false);
    const [useAgenticKnowledgeBase, setUseAgenticRetrieval] = useState<boolean>(false);
    const [hideMinimalRetrievalReasoningOption, setHideMinimalRetrievalReasoningOption] = useState<boolean>(false);
    const streamingDisabledByOverrides = useAgenticKnowledgeBase && webSourceEnabled;

    const audio = useRef(new Audio()).current;
    const [isPlaying, setIsPlaying] = useState(false);

    const speechConfig: SpeechConfig = {
        speechUrls,
        setSpeechUrls,
        audio,
        isPlaying,
        setIsPlaying
    };

    const getConfig = async () => {
        configApi().then(config => {
            const effectiveConfig = applyChatbotSpeechFeatureFlags("hyrox-assessment", config);
            setShowMultimodalOptions(config.showMultimodalOptions);
            if (config.showMultimodalOptions) {
                // Initialize from server config so defaults match deployment settings
                setSendTextSources(config.ragSendTextSources !== undefined ? config.ragSendTextSources : true);
                setSendImageSources(config.ragSendImageSources);
                setSearchTextEmbeddings(config.ragSearchTextEmbeddings);
                setSearchImageEmbeddings(config.ragSearchImageEmbeddings);
            }
            setUseSemanticRanker(config.showSemanticRankerOption);
            setShowSemanticRankerOption(config.showSemanticRankerOption);
            setUseQueryRewriting(config.showQueryRewritingOption);
            setShowQueryRewritingOption(config.showQueryRewritingOption);
            setShowReasoningEffortOption(config.showReasoningEffortOption);
            // Force non-streaming for the assessment regardless of deployment config.
            setStreamingEnabled(false);
            if (config.showReasoningEffortOption) {
                setReasoningEffort(config.defaultReasoningEffort);
            }
            setShowVectorOption(config.showVectorOption);
            if (!config.showVectorOption) {
                setRetrievalMode(RetrievalMode.Text);
            }
            setShowUserUpload(config.showUserUpload);
            setShowSpeechInput(effectiveConfig.showSpeechInput);
            setShowSpeechOutputBrowser(effectiveConfig.showSpeechOutputBrowser);
            setShowSpeechOutputAzure(effectiveConfig.showSpeechOutputAzure);
            setShowChatHistoryBrowser(config.showChatHistoryBrowser);
            setShowChatHistoryCosmos(config.showChatHistoryCosmos);
            // The assessment grades entirely from its in-prompt rubric — no retrieval.
            setShowAgenticRetrievalOption(false);
            setUseAgenticRetrieval(false);
            setWebSourceSupported(config.webSourceEnabled);
            setWebSourceEnabled(config.webSourceEnabled);
            setSharePointSourceSupported(config.sharepointSourceEnabled);
            setSharePointSourceEnabled(config.sharepointSourceEnabled);
            // if (config.showAgenticRetrievalOption) {
            //     setRetrieveCount(10);
            // }
            const defaultRetrievalEffort = config.defaultRetrievalReasoningEffort ?? "minimal";
            setHideMinimalRetrievalReasoningOption(config.webSourceEnabled);
            setRetrievalReasoningEffort(defaultRetrievalEffort);
        });
    };

    const handleAsyncRequest = async (question: string, answers: [string, ChatAppResponse][], responseBody: ReadableStream<any>, signal: AbortSignal) => {
        let answer: string = "";
        let askResponse: ChatAppResponse = {
            message: { content: "", role: "assistant" },
            delta: { content: "", role: "assistant" },
            context: { data_points: { text: [], images: [], citations: [] }, thoughts: [], followup_questions: null },
            session_state: null
        };

        const updateState = (newContent: string) => {
            answer += newContent;
            const latestResponse: ChatAppResponse = {
                ...askResponse,
                message: { content: answer, role: askResponse.message.role }
            };
            setStreamedAnswers([...answers, [question, latestResponse]]);
        };

        const processStreamEvent = (event: Record<string, any>) => {
            if (event["context"] && event["context"]["data_points"]) {
                event["message"] = event["delta"];
                askResponse = event as ChatAppResponse;
            } else if (event["delta"] && event["delta"]["content"]) {
                setIsLoading(false);
                updateState(event["delta"]["content"]);
            } else if (event["context"]) {
                // Update context with new keys from latest event
                askResponse.context = { ...askResponse.context, ...event["context"] };
            } else if (event["error"]) {
                throw Error(event["error"]);
            }
        };
        try {
            setIsStreaming(true);
            const reader = responseBody.getReader();
            const decoder = new TextDecoder("utf-8");
            let runningText = "";

            while (true) {
                if (signal.aborted) {
                    break;
                }

                const { done, value } = await reader.read();
                if (done) {
                    break;
                }

                const text = decoder.decode(value);
                const objects = text.split("\n");

                for (const obj of objects) {
                    try {
                        if (obj !== "" && obj !== "{}") {
                            runningText += obj;
                            processStreamEvent(JSON.parse(runningText) as Record<string, any>);
                            runningText = "";
                        }
                    } catch (e) {
                        if (!(e instanceof SyntaxError)) {
                            throw e;
                        }
                    }
                }
            }

            if (runningText !== "") {
                processStreamEvent(JSON.parse(runningText) as Record<string, any>);
            }
        } catch (e) {
            if (e instanceof DOMException && e.name === "AbortError") {
                // User clicked stop - don't treat as error
                console.log("Stream aborted by user");
            } else {
                throw e; // Re-throw other errors to be caught by makeApiRequest
            }
        } finally {
            setIsStreaming(false);
        }
        const fullResponse: ChatAppResponse = {
            ...askResponse,
            message: { content: answer, role: askResponse.message.role }
        };
        return fullResponse;
    };

    const client = useLogin ? useMsal().instance : undefined;
    const { loggedIn } = useContext(LoginContext);

    const historyProvider: HistoryProviderOptions = (() => {
        if (useLogin && showChatHistoryCosmos) return HistoryProviderOptions.CosmosDB;
        if (showChatHistoryBrowser) return HistoryProviderOptions.IndexedDB;
        return HistoryProviderOptions.None;
    })();
    const historyManager = useHistoryManager(historyProvider);
    const { setRecentChatsAction } = useOutletContext<{ setRecentChatsAction: (action: { run: () => void } | null) => void }>();

    useEffect(() => {
        setRecentChatsAction({
            run: () => setIsHistoryPanelOpen(true)
        });

        return () => {
            setRecentChatsAction(null);
        };
    }, [setRecentChatsAction]);

    const isSyntheticInitialPair = ([user, response]: [user: string, response: ChatAppResponse]) =>
        response.message.role === "assistant" &&
        response.message.content === initialAssistantMessageContent &&
        (user === INITIAL_ASSISTANT_SENTINEL_USER_MESSAGE || user === legacyInitialUserMessage);

    const stripLeadingSyntheticInitialPairs = (chatAnswers: [user: string, response: ChatAppResponse][]) => {
        let startIndex = 0;

        while (startIndex < chatAnswers.length && isSyntheticInitialPair(chatAnswers[startIndex])) {
            startIndex += 1;
        }

        return chatAnswers.slice(startIndex);
    };

    const getLastRealQuestion = (chatAnswers: [user: string, response: ChatAppResponse][]) => {
        const conversationAnswers = stripLeadingSyntheticInitialPairs(chatAnswers);
        return conversationAnswers.length > 0 ? conversationAnswers[conversationAnswers.length - 1][0] : "";
    };

    // Load a stored conversation into the chat (used by the history panel and by restore-on-load).
    // `fallbackSessionId` keeps continuity when the stored answers carry no server session_state.
    const restoreConversation = (historyAnswers: [user: string, response: ChatAppResponse][], fallbackSessionId: string | null) => {
        const restoredAnswers = stripLeadingSyntheticInitialPairs(historyAnswers);
        if (restoredAnswers.length === 0) {
            return;
        }
        // Add welcome message at the beginning of the loaded history
        const restoredConversation = [initialAssistantPair, ...restoredAnswers];
        setAnswers(restoredConversation);
        setStreamedAnswers(restoredConversation);
        lastQuestionRef.current = getLastRealQuestion(restoredAnswers);
        const restoredSessionState = restoredAnswers[restoredAnswers.length - 1][1].session_state;
        const resolvedSessionId =
            typeof restoredSessionState === "string" && restoredSessionState !== "" ? restoredSessionState : fallbackSessionId;
        localHistorySessionIdRef.current = resolvedSessionId;
        if (resolvedSessionId) {
            writeActiveSessionId(resolvedSessionId, userStorageScope);
        }
    };

    const getCurrentSessionState = () => {
        const latestSessionState = answers.length ? answers[answers.length - 1][1].session_state : null;

        if (typeof latestSessionState === "string" && latestSessionState !== "") {
            localHistorySessionIdRef.current = latestSessionState;
            return latestSessionState;
        }

        if (historyProvider === HistoryProviderOptions.IndexedDB) {
            if (!localHistorySessionIdRef.current) {
                localHistorySessionIdRef.current = createClientSessionId();
            }

            return localHistorySessionIdRef.current;
        }

        return null;
    };

    const updateStreamingPreference = (isStreamingEnabledOverride: boolean, disablesStreamingOverride: boolean) => {
        if (!isStreamingEnabledOverride) {
            setShouldStream(current => {
                if (!forcedStreamingRef.current) {
                    previousShouldStreamRef.current = current;
                }
                forcedStreamingRef.current = true;
                return current ? false : current;
            });
            return;
        }

        if (disablesStreamingOverride) {
            setShouldStream(current => {
                if (!forcedStreamingRef.current) {
                    previousShouldStreamRef.current = current;
                }
                forcedStreamingRef.current = true;
                return current ? false : current;
            });
            return;
        }

        forcedStreamingRef.current = false;
        setShouldStream(current => {
            const desiredShouldStream = previousShouldStreamRef.current;
            return current === desiredShouldStream ? current : desiredShouldStream;
        });
    };

    // On a passed completion the backend appends a hidden [[PROGRESS value=N]] marker. Fire the
    // completion hand-off once when it first appears on a freshly received response. The host
    // context (set from the launch URL) picks the channel: web frontends listen for a literal
    // postMessage string; the native app uses the lemon://save_progress scheme.
    const maybeReportLemonProgress = (content: string) => {
        if (progressReportedRef.current) {
            return;
        }
        const value = parseProgressValue(content);
        if (value !== null) {
            progressReportedRef.current = true;
            if (lemonAccount.webFrontend) {
                reportWebFrontendCompletion();
            } else {
                reportLemonProgress(value);
            }
        }
    };

    const makeApiRequest = async (question: string) => {
        const controller = new AbortController();
        setAbortController(controller);
        lastQuestionRef.current = question;

        error && setError(undefined);
        setRestoredQuestion("");
        setIsLoading(true);
        setActiveCitation(undefined);
        setActiveAnalysisPanelTab(undefined);

        const token = client ? await getToken(client) : undefined;

        try {
            const conversationAnswers = stripLeadingSyntheticInitialPairs(answers);
            const messages: ResponseMessage[] = conversationAnswers.flatMap(a => [
                { content: a[0], role: "user" },
                { content: a[1].message.content, role: "assistant" }
            ]);

            const request: ChatAppRequest = {
                messages: [...messages, { content: question, role: "user" }],
                context: {
                    overrides: {
                        prompt_template: promptTemplate.length === 0 ? undefined : promptTemplate,
                        include_category: chatbotCategory,
                        exclude_category: undefined,
                        top: retrieveCount,
                        ...(useAgenticKnowledgeBase ? { retrieval_reasoning_effort: agenticReasoningEffort } : {}),
                        temperature: temperature,
                        minimum_reranker_score: minimumRerankerScore,
                        minimum_search_score: minimumSearchScore,
                        retrieval_mode: retrievalMode,
                        semantic_ranker: useSemanticRanker,
                        semantic_captions: useSemanticCaptions,
                        query_rewriting: useQueryRewriting,
                        reasoning_effort: reasoningEffort,
                        suggest_followup_questions: useSuggestFollowupQuestions,
                        search_text_embeddings: searchTextEmbeddings,
                        search_image_embeddings: searchImageEmbeddings,
                        send_text_sources: sendTextSources,
                        send_image_sources: sendImageSources,
                        language: HYROX_ASSESSMENT_LANGUAGE,
                        use_agentic_knowledgebase: useAgenticKnowledgeBase,
                        use_web_source: webSourceSupported ? webSourceEnabled : false,
                        use_sharepoint_source: sharePointSourceSupported ? sharePointSourceEnabled : false,
                        // Lemon learner identity (from the launch URL) so the result is recorded against them.
                        ...(lemonAccount.accountId ? { account_id: lemonAccount.accountId } : {}),
                        ...(lemonAccount.firstName ? { first_name: lemonAccount.firstName } : {}),
                        ...(lemonAccount.lastName ? { last_name: lemonAccount.lastName } : {}),
                        ...(seed !== null ? { seed: seed } : {})
                    }
                },
                // AI Chat Protocol: Client must pass on any session state received from the server
                session_state: getCurrentSessionState()
            };

            const response = await chatApi(request, shouldStream, token, controller.signal);
            if (!response.body) {
                throw Error("No response body");
            }
            if (response.status > 299 || !response.ok) {
                const errorResponse = (await response.json().catch(() => null)) as ChatAppResponseOrError | null;
                throw Error(errorResponse?.error || `Request failed with status ${response.status}`);
            }
            if (shouldStream) {
                const parsedResponse: ChatAppResponse = await handleAsyncRequest(question, answers, response.body, controller.signal);
                // Only add to answers if we got content, otherwise restore question to input
                if (parsedResponse.message.content) {
                    const sessionState =
                        typeof parsedResponse.session_state === "string" && parsedResponse.session_state !== ""
                            ? parsedResponse.session_state
                            : localHistorySessionIdRef.current;
                    const normalizedResponse =
                        typeof sessionState === "string" && sessionState !== "" ? { ...parsedResponse, session_state: sessionState } : parsedResponse;
                    setAnswers([...answers, [question, normalizedResponse]]);
                    maybeReportLemonProgress(normalizedResponse.message.content);
                    if (typeof sessionState === "string" && sessionState !== "") {
                        const token = client ? await getToken(client) : undefined;
                        historyManager.addItem(sessionState, [...conversationAnswers, [question, normalizedResponse]], token);
                        writeActiveSessionId(sessionState, userStorageScope);
                    }
                } else {
                    // Stopped before any content arrived - restore question to input
                    lastQuestionRef.current = getLastRealQuestion(answers);
                    setRestoredQuestion(question);
                }
            } else {
                const parsedResponse: ChatAppResponseOrError = await response.json();
                if (parsedResponse.error) {
                    throw Error(parsedResponse.error);
                }
                const chatResponse = parsedResponse as ChatAppResponse;
                const sessionState =
                    typeof chatResponse.session_state === "string" && chatResponse.session_state !== ""
                        ? chatResponse.session_state
                        : localHistorySessionIdRef.current;
                const normalizedResponse =
                    typeof sessionState === "string" && sessionState !== "" ? { ...chatResponse, session_state: sessionState } : chatResponse;
                setAnswers([...answers, [question, normalizedResponse]]);
                maybeReportLemonProgress(normalizedResponse.message.content);
                if (typeof sessionState === "string" && sessionState !== "") {
                    const token = client ? await getToken(client) : undefined;
                    historyManager.addItem(sessionState, [...conversationAnswers, [question, normalizedResponse]], token);
                    writeActiveSessionId(sessionState, userStorageScope);
                }
            }
            setSpeechUrls([...speechUrls, null]);
        } catch (e) {
            if (e instanceof DOMException && e.name === "AbortError") {
                // Stopped during loading - restore question to input
                lastQuestionRef.current = getLastRealQuestion(answers);
                setRestoredQuestion(question);
            } else {
                setError(e);
            }
        } finally {
            setIsLoading(false);
            setAbortController(null);
        }
    };

    const clearChat = () => {
        localHistorySessionIdRef.current = null;
        clearActiveSessionId(userStorageScope);
        // A fresh session may pass, so re-arm the one-shot Lemon save_progress hand-off. (After a
        // pass there is no restart, so this only matters for restart-after-fail.)
        progressReportedRef.current = false;
        lastQuestionRef.current = "";
        error && setError(undefined);
        setActiveCitation(undefined);
        setActiveAnalysisPanelTab(undefined);
        setAnswers([initialAssistantPair]); // Reset to welcome message
        setStreamedAnswers([initialAssistantPair]); // Reset to welcome message
        setSpeechUrls([null]);
        setIsLoading(false);
        setIsStreaming(false);
        setRestoredQuestion("");
    };

    useEffect(() => {
        setGlobalClearChat(clearChat);
        return () => {
            setGlobalClearChat(() => {});
        };
    }, [clearChat]);

    // Also add an effect to set initial state on component mount
    useEffect(() => {
        // Ensure welcome message is shown on initial load
        if (answers.length === 0) {
            setAnswers([initialAssistantPair]);
            setStreamedAnswers([initialAssistantPair]);
            setSpeechUrls([null]);
        }
    }, [answers.length, initialAssistantPair]);

    useEffect(() => chatMessageStreamEnd.current?.scrollIntoView({ behavior: "smooth" }), [isLoading]);
    useEffect(() => chatMessageStreamEnd.current?.scrollIntoView({ behavior: "auto" }), [streamedAnswers]);
    useEffect(() => {
        getConfig();
    }, []);

    // Restore the last active session on load so the chat "follows" the user across navigation/tabs.
    // Runs once, after getConfig() has resolved the browser-history provider. Skips if the user has
    // already started asking (lastQuestionRef) so an in-flight conversation is never overwritten.
    useEffect(() => {
        if (hasRestoredSessionRef.current) {
            return;
        }
        if (historyProvider !== HistoryProviderOptions.IndexedDB) {
            return;
        }
        const activeSessionId = readActiveSessionId(userStorageScope);
        if (!activeSessionId) {
            hasRestoredSessionRef.current = true;
            return;
        }
        hasRestoredSessionRef.current = true;
        let cancelled = false;
        (async () => {
            const storedAnswers = await historyManager.getItem(activeSessionId);
            if (cancelled || !storedAnswers || lastQuestionRef.current) {
                return;
            }
            restoreConversation(storedAnswers, activeSessionId);
            // If the restored run was already passed, the original completion hand-off may have been
            // missed (e.g. the host's message listener attached after we posted). Re-fire it once on
            // restore so a reload retries the LMS-completion signal. maybeReportLemonProgress is
            // one-shot via progressReportedRef, so at most one target message is sent per load.
            for (const [, response] of storedAnswers) {
                if (progressReportedRef.current) {
                    break;
                }
                maybeReportLemonProgress(response?.message?.content ?? "");
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [historyProvider, historyManager]);

    // Preserve streaming preference when agentic retrieval forces streaming off.
    useEffect(() => {
        updateStreamingPreference(streamingEnabled, streamingDisabledByOverrides);
    }, [streamingDisabledByOverrides, streamingEnabled]);

    const handleSettingsChange = (field: string, value: any) => {
        switch (field) {
            case "promptTemplate":
                setPromptTemplate(value);
                break;
            case "temperature":
                setTemperature(value);
                break;
            case "seed":
                setSeed(value);
                break;
            case "minimumRerankerScore":
                setMinimumRerankerScore(value);
                break;
            case "minimumSearchScore":
                setMinimumSearchScore(value);
                break;
            case "retrieveCount":
                setRetrieveCount(value);
                break;
            case "agenticReasoningEffort": {
                setRetrievalReasoningEffort(value);
                // If selecting minimal while web source is enabled, disable web source
                if (value === "minimal" && webSourceEnabled) {
                    setWebSourceEnabled(false);
                    setHideMinimalRetrievalReasoningOption(false);
                    // Web source was disabled, so restore streaming
                    updateStreamingPreference(streamingEnabled, false);
                }
                break;
            }
            case "useSemanticRanker":
                setUseSemanticRanker(value);
                break;
            case "useQueryRewriting":
                setUseQueryRewriting(value);
                break;
            case "reasoningEffort":
                setReasoningEffort(value);
                break;
            case "useSemanticCaptions":
                setUseSemanticCaptions(value);
                break;
            case "excludeCategory":
                setExcludeCategory(value);
                break;
            case "includeCategory":
                setIncludeCategory(value);
                break;
            case "shouldStream":
                {
                    const normalizedShouldStream = !!value;
                    forcedStreamingRef.current = false;
                    previousShouldStreamRef.current = normalizedShouldStream;
                    setShouldStream(normalizedShouldStream);
                }
                break;
            case "useSuggestFollowupQuestions":
                setUseSuggestFollowupQuestions(value);
                break;
            case "llmInputs":
                break;
            case "sendTextSources":
                setSendTextSources(value);
                break;
            case "sendImageSources":
                setSendImageSources(value);
                break;
            case "searchTextEmbeddings":
                setSearchTextEmbeddings(value);
                break;
            case "searchImageEmbeddings":
                setSearchImageEmbeddings(value);
                break;
            case "retrievalMode":
                setRetrievalMode(value);
                break;
            case "useAgenticKnowledgeBase": {
                setUseAgenticRetrieval(value);
                setRetrieveCount(value ? 10 : 5);
                let effectiveWebSource = webSourceEnabled;
                if (!value && webSourceEnabled) {
                    effectiveWebSource = false;
                    setWebSourceEnabled(false);
                    setHideMinimalRetrievalReasoningOption(false);
                }
                // Only web source disables streaming
                const shouldDisableStreaming = !!value && effectiveWebSource;
                updateStreamingPreference(streamingEnabled, shouldDisableStreaming);
                break;
            }
            case "useWebSource":
                if (!webSourceSupported) {
                    setWebSourceEnabled(false);
                    return;
                }
                const normalizedWebSource = !!value;
                setWebSourceEnabled(normalizedWebSource);
                setHideMinimalRetrievalReasoningOption(normalizedWebSource);
                // When enabling web source, disable follow-up questions and streaming
                if (normalizedWebSource) {
                    setUseSuggestFollowupQuestions(false);
                }
                const shouldDisableStreaming = useAgenticKnowledgeBase && normalizedWebSource;
                updateStreamingPreference(streamingEnabled, shouldDisableStreaming);
                break;
            case "useSharePointSource":
                if (!sharePointSourceSupported) {
                    setSharePointSourceEnabled(false);
                    return;
                }
                setSharePointSourceEnabled(!!value);
                break;
        }
    };

    const onExampleClicked = (example: string) => {
        makeApiRequest(example);
    };

    const isPdfCitation = (citation: string) => {
        const citationWithoutHash = citation.split("#")[0].toLowerCase();
        return citationWithoutHash.endsWith(".pdf") || citationWithoutHash.includes(".pdf?");
    };

    const onShowCitation = (citation: string, index: number) => {
        if (isPdfCitation(citation)) {
            window.open(citation, "_blank", "noopener,noreferrer");
            return;
        }

        if (activeCitation === citation && activeAnalysisPanelTab === AnalysisPanelTabs.CitationTab && selectedAnswer === index) {
            setActiveAnalysisPanelTab(undefined);
        } else {
            setActiveCitation(citation);
            setActiveAnalysisPanelTab(AnalysisPanelTabs.CitationTab);
        }

        setSelectedAnswer(index);
    };

    const onToggleTab = (tab: AnalysisPanelTabs, index: number) => {
        if (activeAnalysisPanelTab === tab && selectedAnswer === index) {
            setActiveAnalysisPanelTab(undefined);
        } else {
            setActiveAnalysisPanelTab(tab);
        }

        setSelectedAnswer(index);
    };

    const onStopClick = async () => {
        try {
            if (abortController) {
                abortController.abort();
            }
        } catch (e) {
            console.log("An error occurred trying to stop the stream: ", e);
        }
    };

    // The assessment is now module-by-module: a failed module is retaken in place, not by restarting
    // the whole assessment, so completion (the hidden [[DONE]] marker) is emitted ONLY when the final
    // module is passed — finishing always means passing everything. [[DONE]] replays from history, so a
    // restored completed session is detected too. Once it is present we remove the question input
    // entirely (the certificate flow takes over).
    const assessmentComplete = answers.some(([, response]) => hasAssessmentDoneMarker(response.message.content));
    // Module-boundary states, derived from the LATEST message only (earlier modules also carry these
    // markers in history). A passed (non-final) module shows a "Continue to next module" button; a
    // failed module shows a "Retry module" button. While loading, the latest message is the previous
    // turn, so the buttons are suppressed.
    const latestAssistantContent = answers.length > 0 ? answers[answers.length - 1][1].message.content : "";
    const awaitingModuleContinue = !assessmentComplete && !isLoading && hasModulePassMarker(latestAssistantContent);
    const awaitingModuleRetry = !assessmentComplete && !isLoading && hasModuleFailMarker(latestAssistantContent);
    // The welcome state: only the synthetic welcome message is present, no real turn yet. Here we
    // show a "Start assessment" button instead of the text input — the learner taps it to begin
    // (the backend starts the run on the first message; the button just sends "Start"), so they
    // never have to know to type "Start". Once the run has begun (or a session is restored), the
    // text input takes over for answering questions.
    const assessmentNotStarted = stripLeadingSyntheticInitialPairs(answers).length === 0;
    // Control messages the learner never types and whose user bubble is suppressed (the buttons send
    // them on the learner's behalf).
    const isControlMessage = (message: string) => message === "Start" || message === "Continue" || message === "Retry";

    return (
        <div className={styles.container}>
            {/* Setting the page title using react-helmet-async */}
            <Helmet>
                <title>{t("pageTitle")}</title>
            </Helmet>
            {/* <div className={styles.commandsSplitContainer}>
                <div className={styles.commandsContainer}>
                    {((useLogin && showChatHistoryCosmos) || showChatHistoryBrowser) && (
                        <HistoryButton className={styles.commandButton} onClick={() => setIsHistoryPanelOpen(!isHistoryPanelOpen)} />
                    )}
                </div>
                <div className={styles.commandsContainer}>
                    <ClearChatButton className={styles.commandButton} onClick={clearChat} disabled={!lastQuestionRef.current || isLoading} />
                    {showUserUpload && <UploadFile className={styles.commandButton} disabled={!loggedIn} />}
                    <SettingsButton className={styles.commandButton} onClick={() => setIsConfigPanelOpen(!isConfigPanelOpen)} />
                </div>
            </div> */}
            <div className={`${styles.chatRoot} ${isHistoryPanelOpen ? styles.chatRootHistoryOpen : ""}`}>
                <div className={styles.chatContainer} ref={chatContainerRef}>
                    {/* {!lastQuestionRef.current && answers.length === 1 && answers[0][0] === "" ? (
                        <div className={styles.chatEmptyState}>
                            <img src={hyroxLogo} alt="App logo" width="120" height="120" />
                            <h1 className={styles.chatEmptyStateTitle}>{t("chatEmptyStateTitle")}</h1>
                            <h2 className={styles.chatEmptyStateSubtitle}>{t("chatEmptyStateSubtitle")}</h2>
                            <ExampleList onExampleClicked={onExampleClicked} useMultimodalAnswering={showMultimodalOptions} />
                        </div>
                    ) : ( */}
                    <div className={styles.chatMessageStream}>
                        {isStreaming &&
                            streamedAnswers.map((streamedAnswer, index) => {
                                // The backend joins end-of-assessment sections with hidden [[BREAK]]
                                // markers; render one bubble per section. The stored answer keeps the
                                // full content so history replay is unaffected.
                                const bubbles = splitAssessmentBubbles(streamedAnswer[1].message.content);
                                return (
                                    <div key={index}>
                                        {!isSyntheticInitialPair(streamedAnswer) && !isControlMessage(streamedAnswer[0]) && (
                                            <UserChatMessage message={streamedAnswer[0]} />
                                        )}
                                        {bubbles.map((bubbleContent, bubbleIndex) => (
                                            <div className={styles.chatMessageGpt} key={`${index}-${bubbleIndex}`}>
                                                <Answer
                                                    isStreaming={true}
                                                    answer={{ ...streamedAnswer[1], message: { ...streamedAnswer[1].message, content: bubbleContent } }}
                                                    index={index}
                                                    speechConfig={speechConfig}
                                                    isSelected={false}
                                                    onCitationClicked={c => onShowCitation(c, index)}
                                                    onThoughtProcessClicked={() => onToggleTab(AnalysisPanelTabs.ThoughtProcessTab, index)}
                                                    onSupportingContentClicked={() => onToggleTab(AnalysisPanelTabs.SupportingContentTab, index)}
                                                    onFollowupQuestionClicked={q => makeApiRequest(q)}
                                                    showFollowupQuestions={
                                                        useSuggestFollowupQuestions &&
                                                        answers.length - 1 === index &&
                                                        bubbleIndex === bubbles.length - 1
                                                    }
                                                    showSpeechOutputAzure={showSpeechOutputAzure}
                                                    showSpeechOutputBrowser={showSpeechOutputBrowser}
                                                />
                                            </div>
                                        ))}
                                    </div>
                                );
                            })}
                        {!isStreaming &&
                            answers.map((answer, index) => {
                                const bubbles = splitAssessmentBubbles(answer[1].message.content);
                                return (
                                    <div key={index}>
                                        {!isSyntheticInitialPair(answer) && !isControlMessage(answer[0]) && <UserChatMessage message={answer[0]} />}
                                        {bubbles.map((bubbleContent, bubbleIndex) => (
                                            <div className={styles.chatMessageGpt} key={`${index}-${bubbleIndex}`}>
                                                <Answer
                                                    isStreaming={false}
                                                    answer={{ ...answer[1], message: { ...answer[1].message, content: bubbleContent } }}
                                                    index={index}
                                                    speechConfig={speechConfig}
                                                    isSelected={selectedAnswer === index && activeAnalysisPanelTab !== undefined}
                                                    onCitationClicked={c => onShowCitation(c, index)}
                                                    onThoughtProcessClicked={() => onToggleTab(AnalysisPanelTabs.ThoughtProcessTab, index)}
                                                    onSupportingContentClicked={() => onToggleTab(AnalysisPanelTabs.SupportingContentTab, index)}
                                                    onFollowupQuestionClicked={q => makeApiRequest(q)}
                                                    showFollowupQuestions={
                                                        useSuggestFollowupQuestions &&
                                                        answers.length - 1 === index &&
                                                        bubbleIndex === bubbles.length - 1
                                                    }
                                                    showSpeechOutputAzure={showSpeechOutputAzure}
                                                    showSpeechOutputBrowser={showSpeechOutputBrowser}
                                                />
                                            </div>
                                        ))}
                                    </div>
                                );
                            })}
                        {/* Welcome screen: the Start button sits inline, right below the welcome/rules
                            message (no transcript above it yet), so the call-to-action reads as the
                            natural next step. It taps to begin instead of typing "Start". Hidden once
                            the run begins or while it is starting. */}
                        {assessmentNotStarted && !assessmentComplete && !isLoading && (
                            <div className={styles.startInline}>
                                <button type="button" className={styles.footerActionButton} onClick={() => makeApiRequest("Start")}>
                                    {t("startAssessment")}
                                </button>
                            </div>
                        )}
                        {isLoading && (
                            <>
                                {!isControlMessage(lastQuestionRef.current) && <UserChatMessage message={lastQuestionRef.current} />}
                                <div className={styles.chatMessageGptMinWidth}>
                                    <AnswerLoading />
                                </div>
                            </>
                        )}
                        {error ? (
                            <>
                                {!isControlMessage(lastQuestionRef.current) && <UserChatMessage message={lastQuestionRef.current} />}
                                <div className={styles.chatMessageGptMinWidth}>
                                    <AnswerError error={error.toString()} onRetry={() => makeApiRequest(lastQuestionRef.current)} />
                                </div>
                            </>
                        ) : null}
                        <div ref={chatMessageStreamEnd} />
                    </div>
                    {/* )} */}

                    {/* The text input answers questions. It is hidden at a module boundary (where the only
                        action is Continue or Retry) and after completion. */}
                    {!assessmentNotStarted && !assessmentComplete && !awaitingModuleContinue && !awaitingModuleRetry && (
                        <div className={styles.chatInput}>
                            <ScrollToBottomButton containerRef={chatContainerRef} />
                            <QuestionInput
                                clearOnSend
                                placeholder={t("defaultExamples.placeholder")}
                                disabled={isLoading}
                                onSend={question => makeApiRequest(question)}
                                showSpeechInput={showSpeechInput}
                                isStreaming={isStreaming}
                                isLoading={isLoading}
                                onStop={onStopClick}
                                initQuestion={restoredQuestion}
                            />
                        </div>
                    )}
                    {/* After passing a module (not the final one) the learner taps Continue to start the
                        next one; after failing a module they tap Retry to retake it in full. Both send a
                        control message (suppressed user bubble) that the backend acts on. */}
                    {awaitingModuleContinue && (
                        <div className={styles.footerAction}>
                            <button type="button" className={styles.footerActionButton} onClick={() => makeApiRequest("Continue")}>
                                {t("continueModule")}
                            </button>
                        </div>
                    )}
                    {awaitingModuleRetry && (
                        <div className={styles.footerAction}>
                            <button type="button" className={styles.footerActionButton} onClick={() => makeApiRequest("Retry")}>
                                {t("retryModule")}
                            </button>
                        </div>
                    )}
                </div>

                {answers.length > 0 && activeAnalysisPanelTab && (
                    <AnalysisPanel
                        className={styles.chatAnalysisPanel}
                        activeCitation={activeCitation}
                        onActiveTabChanged={x => onToggleTab(x, selectedAnswer)}
                        citationHeight="810px"
                        answer={answers[selectedAnswer][1]}
                        activeTab={activeAnalysisPanelTab}
                        onCitationClicked={c => onShowCitation(c, selectedAnswer)}
                    />
                )}

                {((useLogin && showChatHistoryCosmos) || showChatHistoryBrowser) && (
                    <HistoryPanel
                        provider={historyProvider}
                        isOpen={isHistoryPanelOpen}
                        notify={!isStreaming && !isLoading}
                        onClose={() => setIsHistoryPanelOpen(false)}
                        onChatSelected={historyAnswers => restoreConversation(historyAnswers, null)}
                    />
                )}

                <Panel
                    headerText={t("labels.headerText")}
                    isOpen={isConfigPanelOpen}
                    isBlocking={false}
                    onDismiss={() => setIsConfigPanelOpen(false)}
                    closeButtonAriaLabel={t("labels.closeButton")}
                    onRenderFooterContent={() => <DefaultButton onClick={() => setIsConfigPanelOpen(false)}>{t("labels.closeButton")}</DefaultButton>}
                    isFooterAtBottom={true}
                >
                    <Settings
                        promptTemplate={promptTemplate}
                        temperature={temperature}
                        retrieveCount={retrieveCount}
                        agenticReasoningEffort={agenticReasoningEffort}
                        seed={seed}
                        minimumSearchScore={minimumSearchScore}
                        minimumRerankerScore={minimumRerankerScore}
                        useSemanticRanker={useSemanticRanker}
                        useSemanticCaptions={useSemanticCaptions}
                        useQueryRewriting={useQueryRewriting}
                        reasoningEffort={reasoningEffort}
                        excludeCategory={excludeCategory}
                        includeCategory={includeCategory}
                        retrievalMode={retrievalMode}
                        showMultimodalOptions={showMultimodalOptions}
                        sendTextSources={sendTextSources}
                        sendImageSources={sendImageSources}
                        searchTextEmbeddings={searchTextEmbeddings}
                        searchImageEmbeddings={searchImageEmbeddings}
                        showSemanticRankerOption={showSemanticRankerOption}
                        showQueryRewritingOption={showQueryRewritingOption}
                        showReasoningEffortOption={showReasoningEffortOption}
                        showVectorOption={showVectorOption}
                        useLogin={!!useLogin}
                        loggedIn={loggedIn}
                        requireAccessControl={requireAccessControl}
                        shouldStream={shouldStream}
                        streamingEnabled={streamingEnabled}
                        useSuggestFollowupQuestions={useSuggestFollowupQuestions}
                        showAgenticRetrievalOption={showAgenticRetrievalOption}
                        useAgenticKnowledgeBase={useAgenticKnowledgeBase}
                        useWebSource={webSourceEnabled}
                        showWebSourceOption={webSourceSupported}
                        useSharePointSource={sharePointSourceEnabled}
                        showSharePointSourceOption={sharePointSourceSupported}
                        hideMinimalRetrievalReasoningOption={hideMinimalRetrievalReasoningOption}
                        onChange={handleSettingsChange}
                    />
                    {useLogin && <TokenClaimsDisplay />}
                </Panel>
            </div>
        </div>
    );
};

export default Chat;
