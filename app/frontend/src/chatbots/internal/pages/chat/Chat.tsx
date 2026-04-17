import { useRef, useState, useEffect, useContext } from "react";
import { useTranslation } from "react-i18next";
import { Helmet } from "react-helmet-async";
import { useOutletContext } from "react-router-dom";
import { Panel, DefaultButton } from "@fluentui/react";
import appLogo from "../../../lemon/assets/applogo.svg";
import styles from "../../../lemon/pages/chat/Chat.module.css";

import { chatApi, configApi, RetrievalMode, ChatAppResponse, ChatAppResponseOrError, ChatAppRequest, ResponseMessage, SpeechConfig } from "../../api";
import { Answer, AnswerError, AnswerLoading } from "../../components/Answer";
import { QuestionInput } from "../../../lemon/components/QuestionInput";
import { ExampleList } from "../../../lemon/components/Example";
import { UserChatMessage } from "../../../lemon/components/UserChatMessage";
import { AnalysisPanel, AnalysisPanelTabs } from "../../../lemon/components/AnalysisPanel";
import { HistoryPanel } from "../../../lemon/components/HistoryPanel";
import { HistoryProviderOptions, useHistoryManager } from "../../../lemon/components/HistoryProviders";
import { HistoryButton } from "../../../lemon/components/HistoryButton";
import { SettingsButton } from "../../../lemon/components/SettingsButton";
import { ClearChatButton } from "../../../lemon/components/ClearChatButton";
import { UploadFile } from "../../../lemon/components/UploadFile";
import { useLogin, getToken, requireAccessControl } from "../../authConfig";
import { useMsal } from "@azure/msal-react";
import { TokenClaimsDisplay } from "../../../lemon/components/TokenClaimsDisplay";
import { LoginContext } from "../../loginContext";
import { LanguagePicker } from "../../../lemon/i18n/LanguagePicker";
import { Settings } from "../../components/Settings/Settings";
import { setGlobalClearChat, type InternalLayoutOutletContext } from "../layout/Layout";
import { applyChatbotSpeechFeatureFlags } from "../../../shared/speech/chatbotSpeechFeatureFlags";
import { ChatbotDisclaimerBanner } from "../../../shared/disclaimer/ChatbotDisclaimerBanner";

const INITIAL_ASSISTANT_SENTINEL_USER_MESSAGE = "__initial_assistant__";
const DEFAULT_CHAT_MODEL = "gpt-4.1-mini";
const GPT_5_REASONING_EFFORT_OPTIONS = ["minimal", "low", "medium", "high"];
const GPT_5_4_REASONING_EFFORT_OPTIONS = ["none", "low", "medium", "high", "xhigh"];
const EMPTY_REASONING_EFFORT_OPTIONS: string[] = [];

const getLegacyReasoningEffortOptions = (chatModel: string, reasoningCapableChatModels: string[]) => {
    if (!reasoningCapableChatModels.includes(chatModel)) {
        return EMPTY_REASONING_EFFORT_OPTIONS;
    }

    if (chatModel.startsWith("gpt-5.4")) {
        return GPT_5_4_REASONING_EFFORT_OPTIONS;
    }

    return GPT_5_REASONING_EFFORT_OPTIONS;
};

const createClientSessionId = () => {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
        return crypto.randomUUID();
    }

    return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
};

const Chat = () => {
    const { t, i18n } = useTranslation();
    const chatbotCategory = "internal";
    const legacyInitialUserMessage: string = t("initialUserMsg");
    const initialAssistantMessageContent: string = t("initialAssistantMsg");
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
    const initialAssistantPair: [user: string, response: ChatAppResponse] = [
        INITIAL_ASSISTANT_SENTINEL_USER_MESSAGE,
        initialAssistantResponse
    ];
    const [isConfigPanelOpen, setIsConfigPanelOpen] = useState(false);
    const [isHistoryPanelOpen, setIsHistoryPanelOpen] = useState(false);
    const [promptTemplate, setPromptTemplate] = useState<string>("");
    const [chatModel, setChatModel] = useState<string>(DEFAULT_CHAT_MODEL);
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
    const [streamingEnabled, setStreamingEnabled] = useState<boolean>(true);
    const [shouldStream, setShouldStream] = useState<boolean>(true);
    const previousShouldStreamRef = useRef<boolean>(true);
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
    const localHistorySessionIdRef = useRef<string | null>(null);

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
    const [availableChatModels, setAvailableChatModels] = useState<string[]>([DEFAULT_CHAT_MODEL]);
    const [reasoningCapableChatModels, setReasoningCapableChatModels] = useState<string[]>([]);
    const [chatModelReasoningEfforts, setChatModelReasoningEfforts] = useState<Record<string, string[]>>({});
    const [showSemanticRankerOption, setShowSemanticRankerOption] = useState<boolean>(false);
    const [showQueryRewritingOption, setShowQueryRewritingOption] = useState<boolean>(false);
    const [showVectorOption, setShowVectorOption] = useState<boolean>(false);
    const [showUserUpload, setShowUserUpload] = useState<boolean>(false);
    const [showLanguagePicker, setshowLanguagePicker] = useState<boolean>(false);
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
    const supportedReasoningEfforts =
        chatModelReasoningEfforts[chatModel] ?? getLegacyReasoningEffortOptions(chatModel, reasoningCapableChatModels);
    const showReasoningEffortOption = supportedReasoningEfforts.length > 0;

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
            const effectiveConfig = applyChatbotSpeechFeatureFlags("internal", config);
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
            setStreamingEnabled(config.streamingEnabled);
            setAvailableChatModels(config.availableChatModels?.length ? config.availableChatModels : [DEFAULT_CHAT_MODEL]);
            setChatModel(config.defaultChatModel ?? DEFAULT_CHAT_MODEL);
            setReasoningCapableChatModels(config.reasoningCapableChatModels ?? []);
            setChatModelReasoningEfforts(config.chatModelReasoningEfforts ?? {});
            setReasoningEffort(config.defaultReasoningEffort ?? "");
            setShowVectorOption(config.showVectorOption);
            if (!config.showVectorOption) {
                setRetrievalMode(RetrievalMode.Text);
            }
            setShowUserUpload(config.showUserUpload);
            setshowLanguagePicker(config.showLanguagePicker);
            setShowSpeechInput(effectiveConfig.showSpeechInput);
            setShowSpeechOutputBrowser(effectiveConfig.showSpeechOutputBrowser);
            setShowSpeechOutputAzure(effectiveConfig.showSpeechOutputAzure);
            setShowChatHistoryBrowser(config.showChatHistoryBrowser);
            setShowChatHistoryCosmos(config.showChatHistoryCosmos);
            setShowAgenticRetrievalOption(config.showAgenticRetrievalOption);
            setUseAgenticRetrieval(config.showAgenticRetrievalOption);
            setWebSourceSupported(config.webSourceEnabled);
            setWebSourceEnabled(config.webSourceEnabled);
            setSharePointSourceSupported(config.sharepointSourceEnabled);
            setSharePointSourceEnabled(config.sharepointSourceEnabled);
            if (config.showAgenticRetrievalOption) {
                setRetrieveCount(10);
            }
            const defaultRetrievalEffort = config.defaultRetrievalReasoningEffort ?? "minimal";
            setHideMinimalRetrievalReasoningOption(config.webSourceEnabled);
            setRetrievalReasoningEffort(defaultRetrievalEffort);
        });
    };

    useEffect(() => {
        if (!showReasoningEffortOption) {
            if (reasoningEffort !== "") {
                setReasoningEffort("");
            }
            return;
        }

        if (!supportedReasoningEfforts.includes(reasoningEffort)) {
            setReasoningEffort(supportedReasoningEfforts[0]);
        }
    }, [reasoningEffort, showReasoningEffortOption, supportedReasoningEfforts]);

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
    const { setRecentChatsAction, setDeveloperOptionsAction } = useOutletContext<InternalLayoutOutletContext>();

    useEffect(() => {
        setRecentChatsAction({
            run: () => setIsHistoryPanelOpen(true)
        });
        setDeveloperOptionsAction({
            run: () => setIsConfigPanelOpen(true)
        });

        return () => {
            setRecentChatsAction(null);
            setDeveloperOptionsAction(null);
        };
    }, [setDeveloperOptionsAction, setRecentChatsAction]);

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
                        chat_model: chatModel,
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
                        reasoning_effort: showReasoningEffortOption ? reasoningEffort : undefined,
                        suggest_followup_questions: useSuggestFollowupQuestions,
                        search_text_embeddings: searchTextEmbeddings,
                        search_image_embeddings: searchImageEmbeddings,
                        send_text_sources: sendTextSources,
                        send_image_sources: sendImageSources,
                        language: i18n.language,
                        use_agentic_knowledgebase: useAgenticKnowledgeBase,
                        use_web_source: webSourceSupported ? webSourceEnabled : false,
                        use_sharepoint_source: sharePointSourceSupported ? sharePointSourceEnabled : false,
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
                        typeof sessionState === "string" && sessionState !== ""
                            ? { ...parsedResponse, session_state: sessionState }
                            : parsedResponse;
                    setAnswers([...answers, [question, normalizedResponse]]);
                    if (typeof sessionState === "string" && sessionState !== "") {
                        const token = client ? await getToken(client) : undefined;
                        historyManager.addItem(sessionState, [...conversationAnswers, [question, normalizedResponse]], token);
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
                    typeof sessionState === "string" && sessionState !== ""
                        ? { ...chatResponse, session_state: sessionState }
                        : chatResponse;
                setAnswers([...answers, [question, normalizedResponse]]);
                if (typeof sessionState === "string" && sessionState !== "") {
                    const token = client ? await getToken(client) : undefined;
                    historyManager.addItem(sessionState, [...conversationAnswers, [question, normalizedResponse]], token);
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

    // Preserve streaming preference when agentic retrieval forces streaming off.
    useEffect(() => {
        updateStreamingPreference(streamingEnabled, streamingDisabledByOverrides);
    }, [streamingDisabledByOverrides, streamingEnabled]);

    const handleSettingsChange = (field: string, value: any) => {
        switch (field) {
            case "promptTemplate":
                setPromptTemplate(value);
                break;
            case "chatModel":
                setChatModel(value);
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
            <div className={styles.chatRoot} style={{ marginLeft: isHistoryPanelOpen ? "300px" : "0" }}>
                <div className={styles.chatContainer}>
                    <ChatbotDisclaimerBanner isLoggedIn={loggedIn} />
                    {/* {!lastQuestionRef.current && answers.length === 1 && answers[0][0] === "" ? (
                        <div className={styles.chatEmptyState}>
                            <img src={appLogo} alt="App logo" width="120" height="120" />
                            <h1 className={styles.chatEmptyStateTitle}>{t("chatEmptyStateTitle")}</h1>
                            <h2 className={styles.chatEmptyStateSubtitle}>{t("chatEmptyStateSubtitle")}</h2>
                            {showLanguagePicker && <LanguagePicker onLanguageChange={newLang => i18n.changeLanguage(newLang)} />}
                            <ExampleList onExampleClicked={onExampleClicked} useMultimodalAnswering={showMultimodalOptions} />
                        </div>
                    ) : ( */}
                    <div className={styles.chatMessageStream}>
                        {isStreaming &&
                            streamedAnswers.map((streamedAnswer, index) => (
                                <div key={index}>
                                    {!isSyntheticInitialPair(streamedAnswer) && <UserChatMessage message={streamedAnswer[0]} />}
                                    <div className={styles.chatMessageGpt}>
                                        <Answer
                                            isStreaming={true}
                                            key={index}
                                            answer={streamedAnswer[1]}
                                            index={index}
                                            speechConfig={speechConfig}
                                            isSelected={false}
                                            onCitationClicked={c => onShowCitation(c, index)}
                                            onThoughtProcessClicked={() => onToggleTab(AnalysisPanelTabs.ThoughtProcessTab, index)}
                                            onSupportingContentClicked={() => onToggleTab(AnalysisPanelTabs.SupportingContentTab, index)}
                                            onFollowupQuestionClicked={q => makeApiRequest(q)}
                                            showFollowupQuestions={useSuggestFollowupQuestions && answers.length - 1 === index}
                                            showSpeechOutputAzure={showSpeechOutputAzure}
                                            showSpeechOutputBrowser={showSpeechOutputBrowser}
                                        />
                                    </div>
                                </div>
                            ))}
                        {!isStreaming &&
                            answers.map((answer, index) => (
                                <div key={index}>
                                    {!isSyntheticInitialPair(answer) && <UserChatMessage message={answer[0]} />}
                                    <div className={styles.chatMessageGpt}>
                                        <Answer
                                            isStreaming={false}
                                            key={index}
                                            answer={answer[1]}
                                            index={index}
                                            speechConfig={speechConfig}
                                            isSelected={selectedAnswer === index && activeAnalysisPanelTab !== undefined}
                                            onCitationClicked={c => onShowCitation(c, index)}
                                            onThoughtProcessClicked={() => onToggleTab(AnalysisPanelTabs.ThoughtProcessTab, index)}
                                            onSupportingContentClicked={() => onToggleTab(AnalysisPanelTabs.SupportingContentTab, index)}
                                            onFollowupQuestionClicked={q => makeApiRequest(q)}
                                            showFollowupQuestions={useSuggestFollowupQuestions && answers.length - 1 === index}
                                            showSpeechOutputAzure={showSpeechOutputAzure}
                                            showSpeechOutputBrowser={showSpeechOutputBrowser}
                                        />
                                    </div>
                                </div>
                            ))}
                        {isLoading && (
                            <>
                                <UserChatMessage message={lastQuestionRef.current} />
                                <div className={styles.chatMessageGptMinWidth}>
                                    <AnswerLoading />
                                </div>
                            </>
                        )}
                        {error ? (
                            <>
                                <UserChatMessage message={lastQuestionRef.current} />
                                <div className={styles.chatMessageGptMinWidth}>
                                    <AnswerError error={error.toString()} onRetry={() => makeApiRequest(lastQuestionRef.current)} />
                                </div>
                            </>
                        ) : null}
                        <div ref={chatMessageStreamEnd} />
                    </div>
                    {/* )} */}

                    <div className={styles.chatInput}>
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
                        onChatSelected={historyAnswers => {
                            const restoredAnswers = stripLeadingSyntheticInitialPairs(historyAnswers);
                            if (restoredAnswers.length === 0) return;
                            // Add welcome message at the beginning of the loaded history
                            const restoredConversation = [initialAssistantPair, ...restoredAnswers];
                            setAnswers(restoredConversation);
                            setStreamedAnswers(restoredConversation);
                            lastQuestionRef.current = getLastRealQuestion(restoredAnswers);
                            const restoredSessionState = restoredAnswers[restoredAnswers.length - 1][1].session_state;
                            localHistorySessionIdRef.current =
                                typeof restoredSessionState === "string" && restoredSessionState !== "" ? restoredSessionState : null;
                        }}
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
                        chatModel={chatModel}
                        promptTemplate={promptTemplate}
                        temperature={temperature}
                        retrieveCount={retrieveCount}
                        availableChatModels={availableChatModels}
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
                        reasoningEffortOptions={supportedReasoningEfforts}
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
