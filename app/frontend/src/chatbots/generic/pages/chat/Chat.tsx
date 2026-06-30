import { useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import { Helmet } from "react-helmet-async";
import { IconButton, type IContextualMenuItem } from "@fluentui/react";
import { Send28Filled } from "@fluentui/react-icons";

import appLogo from "../../../../assets/applogo.svg";
import { Answer } from "../../components/Answer";
import { LanguagePicker } from "../../i18n/LanguagePicker";
import { HistoryPanel } from "../../components/HistoryPanel/HistoryPanel";
import { HistoryProviderOptions, useHistoryManager, type Answers } from "../../components/HistoryProviders";
import { Example } from "../../../shared/components/Example/Example";
import { ChatbotDisclaimerBanner } from "../../../shared/disclaimer/ChatbotDisclaimerBanner";
import { readActiveSessionId, writeActiveSessionId, clearActiveSessionId } from "../../../shared/history/activeSession";
import { chatApi } from "../../../../api";
import type {
    BotConfig,
    ChatAppRequest,
    ChatAppRequestOverrides,
    ChatAppResponse,
    ChatAppResponseOrError,
    ResponseMessage,
    SpeechConfig
} from "../../../../api/models";

type Exchange = [user: string, response: ChatAppResponse];

const noop = () => {};

// Client-side session id used to key this conversation in browser history (IndexedDB) and the
// active-session pointer. It is unrelated to backend quota counting, which keys off message count.
function createClientSessionId(): string {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
        return crypto.randomUUID();
    }
    return `sid-${new Date().getTime()}-${Math.random().toString(36).slice(2)}`;
}

/**
 * Q&A chat for a dynamically provisioned bot. Mirrors the built-in bots' chrome: themed navbar with a
 * logo, title and a header menu (New chat), an empty state with examples + a language picker, the shared
 * answer factory, and an icon composer. Identity (greeting, disclaimer, title, theme) + the active
 * language come from the runtime i18n instance + theme seed provided by GenericChatbotRoute.
 */
export function GenericChat({ config }: { config: BotConfig }) {
    const { t, i18n } = useTranslation();
    const [exchanges, setExchanges] = useState<Exchange[]>([]);
    const [question, setQuestion] = useState("");
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [isHistoryPanelOpen, setIsHistoryPanelOpen] = useState(false);
    const abortRef = useRef<AbortController | null>(null);

    // Browser-only chat history (IndexedDB), enabled unless the bot was provisioned with features.history
    // === false. The session id keys the current conversation in storage; the active-session pointer lets
    // the chat reappear after a reload/navigation, exactly like the built-in bots.
    const historyEnabled = config.features?.history !== false;
    const historyProvider = historyEnabled ? HistoryProviderOptions.IndexedDB : HistoryProviderOptions.None;
    const historyManager = useHistoryManager(historyProvider);
    const sessionIdRef = useRef<string | null>(null);
    const hasRestoredRef = useRef(false);

    const speechConfig: SpeechConfig = useMemo(
        () => ({ speechUrls: [], setSpeechUrls: noop, audio: new Audio(), isPlaying: false, setIsPlaying: noop }),
        []
    );

    const submit = async (rawText: string) => {
        const text = rawText.trim();
        if (!text || isLoading) {
            return;
        }
        setError(null);
        setIsLoading(true);

        const history: ResponseMessage[] = exchanges.flatMap(([userText, response]) => [
            { role: "user", content: userText },
            { role: "assistant", content: response.message.content }
        ]);
        const overrides: ChatAppRequestOverrides = {
            include_category: config.botName,
            language: i18n.language,
            send_text_sources: true,
            send_image_sources: false,
            search_text_embeddings: true,
            search_image_embeddings: false,
            use_agentic_knowledgebase: false
        };
        const request: ChatAppRequest = {
            messages: [...history, { role: "user", content: text }],
            context: { overrides },
            session_state: null
        };

        const controller = new AbortController();
        abortRef.current = controller;
        try {
            const response = await chatApi(request, false, undefined, controller.signal);
            const data = (await response.json()) as ChatAppResponseOrError;
            if (!response.ok || data.error) {
                setError(data.error || t("errorMessage"));
            } else {
                const updated: Exchange[] = [...exchanges, [text, data as ChatAppResponse]];
                setExchanges(updated);
                if (historyEnabled) {
                    if (!sessionIdRef.current) {
                        sessionIdRef.current = createClientSessionId();
                    }
                    const sessionId = sessionIdRef.current;
                    void historyManager.addItem(sessionId, updated as Answers);
                    writeActiveSessionId(sessionId);
                }
            }
        } catch {
            setError(t("errorMessage"));
        } finally {
            setIsLoading(false);
            abortRef.current = null;
        }
    };

    const submitComposer = () => {
        const text = question;
        setQuestion("");
        void submit(text);
    };

    const handleNewChat = () => {
        sessionIdRef.current = null;
        clearActiveSessionId();
        setExchanges([]);
        setError(null);
        setQuestion("");
    };

    // Load a stored conversation (history panel click) into the chat and make it the active session.
    const onChatSelected = (id: string, answers: Answers) => {
        sessionIdRef.current = id;
        writeActiveSessionId(id);
        setExchanges(answers as Exchange[]);
        setError(null);
        setIsHistoryPanelOpen(false);
    };

    // Restore the last active session on load so the chat "follows" the user across navigation/tabs.
    // Runs once; skips if the user has already started chatting so an in-flight conversation is kept.
    useEffect(() => {
        if (hasRestoredRef.current || !historyEnabled) {
            return;
        }
        hasRestoredRef.current = true;
        const activeSessionId = readActiveSessionId();
        if (!activeSessionId) {
            return;
        }
        let cancelled = false;
        (async () => {
            const storedAnswers = await historyManager.getItem(activeSessionId);
            if (cancelled || !storedAnswers || exchanges.length > 0) {
                return;
            }
            sessionIdRef.current = activeSessionId;
            setExchanges(storedAnswers as Exchange[]);
        })();
        return () => {
            cancelled = true;
        };
    }, [historyEnabled, historyManager]);

    const onCitationClicked = (filePath: string) => {
        window.open(filePath, "_blank", "noopener");
    };

    const onKeyDown = (event: ReactKeyboardEvent<HTMLTextAreaElement>) => {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            submitComposer();
        }
    };

    const isEmpty = exchanges.length === 0;
    const canSend = !isLoading && question.trim().length > 0;

    const menuItems: IContextualMenuItem[] = [
        {
            key: "newChat",
            text: t("newChat"),
            iconProps: { iconName: "Add" },
            onClick: () => {
                handleNewChat();
            }
        }
    ];
    if (historyEnabled) {
        menuItems.push({
            key: "chatHistory",
            text: t("history.openChatHistory"),
            iconProps: { iconName: "History" },
            onClick: () => {
                setIsHistoryPanelOpen(true);
            }
        });
    }

    return (
        <div style={pageStyle}>
            <Helmet>
                <title>{t("pageTitle")}</title>
            </Helmet>
            <header style={headerStyle}>
                <div style={logoCircleStyle}>
                    <img src={appLogo} alt="" style={logoImgStyle} />
                </div>
                <span style={titleStyle}>{config.displayName}</span>
                <div style={headerRightStyle}>
                    <IconButton
                        ariaLabel={t("labels.openMenu")}
                        iconProps={{ iconName: "More", styles: { root: { fontSize: "20px" } } }}
                        styles={menuButtonStyles}
                        menuProps={{ items: menuItems }}
                        menuIconProps={{ styles: { root: { display: "none" } } }}
                    />
                </div>
            </header>
            {config.features.disclaimer ? <ChatbotDisclaimerBanner isLoggedIn={true} /> : null}
            <main style={mainStyle}>
                <div style={assistantBubbleStyle}>{t("initialAssistantMsg")}</div>
                {isEmpty ? (
                    <div style={emptyStateStyle}>
                        <ul style={examplesListStyle}>
                            {["defaultExamples.1", "defaultExamples.2", "defaultExamples.3"].map(key => {
                                const example = t(key);
                                return (
                                    <li key={key} style={exampleItemStyle}>
                                        <Example text={example} value={example} onClick={value => void submit(value)} />
                                    </li>
                                );
                            })}
                        </ul>
                        <LanguagePicker />
                    </div>
                ) : null}
                {exchanges.map(([userText, response], index) => (
                    <div key={index} style={exchangeStyle}>
                        <div style={userBubbleStyle}>{userText}</div>
                        <Answer
                            answer={response}
                            index={index}
                            speechConfig={speechConfig}
                            isStreaming={false}
                            onCitationClicked={onCitationClicked}
                            onThoughtProcessClicked={noop}
                            onSupportingContentClicked={noop}
                            showCitations={config.features?.sources !== false}
                        />
                    </div>
                ))}
                {isLoading ? <div style={loadingStyle}>{t("generatingAnswer")}…</div> : null}
                {error ? (
                    <div role="alert" style={errorStyle}>
                        {error}
                    </div>
                ) : null}
            </main>
            <footer style={composerStyle}>
                <div style={composerInnerStyle}>
                    <textarea
                        value={question}
                        onChange={event => setQuestion(event.target.value)}
                        onKeyDown={onKeyDown}
                        placeholder={t("composerPlaceholder")}
                        aria-label={t("composerPlaceholder")}
                        rows={1}
                        style={textareaStyle}
                    />
                    <button
                        type="button"
                        onClick={submitComposer}
                        disabled={!canSend}
                        aria-label={t("tooltips.submitQuestion")}
                        title={t("tooltips.submitQuestion")}
                        style={{ ...sendButtonStyle, opacity: canSend ? 1 : 0.4, cursor: canSend ? "pointer" : "default" }}
                    >
                        <Send28Filled />
                    </button>
                </div>
            </footer>
            {historyEnabled ? (
                <HistoryPanel
                    provider={historyProvider}
                    isOpen={isHistoryPanelOpen}
                    notify={!isLoading}
                    onClose={() => setIsHistoryPanelOpen(false)}
                    onChatSelected={onChatSelected}
                />
            ) : null}
        </div>
    );
}

const pageStyle: CSSProperties = { display: "flex", flexDirection: "column", height: "100vh", maxWidth: 1100, margin: "0 auto", width: "100%" };
const headerStyle: CSSProperties = {
    display: "flex",
    alignItems: "center",
    gap: 12,
    padding: "10px 20px",
    background: "var(--chatbot-navbar-background)",
    color: "var(--chatbot-navbar-text)"
};
const logoCircleStyle: CSSProperties = {
    height: 36,
    width: 36,
    borderRadius: "50%",
    background: "var(--chatbot-navbar-logo-background, #ffffff)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center"
};
const logoImgStyle: CSSProperties = { height: 22, width: 22 };
const titleStyle: CSSProperties = { fontSize: 18, fontWeight: 600 };
const headerRightStyle: CSSProperties = { marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 };
const menuButtonStyles = { root: { color: "var(--chatbot-navbar-text)" }, rootHovered: { color: "var(--chatbot-navbar-text)" } } as const;
const mainStyle: CSSProperties = { flex: 1, overflowY: "auto", padding: 20, display: "flex", flexDirection: "column", gap: 16 };
const emptyStateStyle: CSSProperties = { display: "flex", flexDirection: "column", gap: 16, alignItems: "flex-start" };
const examplesListStyle: CSSProperties = { listStyle: "none", margin: 0, padding: 0, display: "flex", flexWrap: "wrap", gap: 10 };
const exampleItemStyle: CSSProperties = { listStyle: "none" };
const exchangeStyle: CSSProperties = { display: "flex", flexDirection: "column", gap: 8 };
const assistantBubbleStyle: CSSProperties = { alignSelf: "flex-start", maxWidth: "85%", background: "#f3f4f6", color: "#182033", padding: "10px 14px", borderRadius: 12 };
const userBubbleStyle: CSSProperties = {
    marginLeft: "auto",
    width: "fit-content",
    maxWidth: "85%",
    background: "var(--chatbot-user-bubble-background)",
    color: "var(--chatbot-user-bubble-text)",
    padding: "10px 14px",
    borderRadius: 12
};
const loadingStyle: CSSProperties = { color: "#6b7280", fontStyle: "italic" };
const errorStyle: CSSProperties = { color: "#b91c1c", background: "#fee2e2", padding: "10px 14px", borderRadius: 8 };
const composerStyle: CSSProperties = { padding: 16, borderTop: "1px solid #e5e7eb" };
const composerInnerStyle: CSSProperties = {
    display: "flex",
    alignItems: "flex-end",
    gap: 8,
    border: "1px solid #d1d5db",
    borderRadius: 14,
    padding: 8,
    background: "#ffffff"
};
const textareaStyle: CSSProperties = {
    flex: 1,
    resize: "none",
    padding: "8px 10px",
    border: "none",
    outline: "none",
    fontFamily: "inherit",
    fontSize: 15,
    maxHeight: 160,
    background: "transparent"
};
const sendButtonStyle: CSSProperties = {
    flex: "0 0 auto",
    height: 40,
    width: 40,
    borderRadius: "50%",
    border: "none",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    background: "var(--chatbot-navbar-background)",
    color: "var(--chatbot-navbar-text)"
};
