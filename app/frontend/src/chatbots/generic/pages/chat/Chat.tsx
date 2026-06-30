import { useMemo, useRef, useState, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import { Helmet } from "react-helmet-async";

import appLogo from "../../../../assets/applogo.svg";
import { Answer } from "../../components/Answer";
import { ChatbotDisclaimerBanner } from "../../../shared/disclaimer/ChatbotDisclaimerBanner";
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

/**
 * Slim Q&A chat for a dynamically provisioned bot. Reuses the shared answer factory + disclaimer
 * banner; no history/settings/speech/upload (v1 scope). Identity (greeting, disclaimer, title, theme)
 * comes from the runtime i18n instance + theme seed provided by GenericChatbotRoute.
 */
export function GenericChat({ config }: { config: BotConfig }) {
    const { t, i18n } = useTranslation();
    const [exchanges, setExchanges] = useState<Exchange[]>([]);
    const [question, setQuestion] = useState("");
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const abortRef = useRef<AbortController | null>(null);

    const speechConfig: SpeechConfig = useMemo(
        () => ({ speechUrls: [], setSpeechUrls: noop, audio: new Audio(), isPlaying: false, setIsPlaying: noop }),
        []
    );

    const send = async () => {
        const text = question.trim();
        if (!text || isLoading) {
            return;
        }
        setError(null);
        setIsLoading(true);
        setQuestion("");

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
                setExchanges(previous => [...previous, [text, data as ChatAppResponse]]);
            }
        } catch {
            setError(t("errorMessage"));
        } finally {
            setIsLoading(false);
            abortRef.current = null;
        }
    };

    const onCitationClicked = (filePath: string) => {
        window.open(filePath, "_blank", "noopener");
    };

    const onKeyDown = (event: ReactKeyboardEvent<HTMLTextAreaElement>) => {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            void send();
        }
    };

    return (
        <div style={pageStyle}>
            <Helmet>
                <title>{t("pageTitle")}</title>
            </Helmet>
            <header style={headerStyle}>
                <img src={appLogo} alt="" style={logoStyle} />
                <span style={titleStyle}>{config.displayName}</span>
            </header>
            {config.features.disclaimer ? <ChatbotDisclaimerBanner isLoggedIn={true} /> : null}
            <main style={mainStyle}>
                <div style={assistantBubbleStyle}>{t("initialAssistantMsg")}</div>
                {exchanges.length === 0 ? <p style={emptyHintStyle}>{t("chatEmptyStateSubtitle")}</p> : null}
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
                <textarea
                    value={question}
                    onChange={event => setQuestion(event.target.value)}
                    onKeyDown={onKeyDown}
                    placeholder={t("composerPlaceholder")}
                    aria-label={t("composerPlaceholder")}
                    rows={1}
                    style={textareaStyle}
                />
                <button type="button" onClick={() => void send()} disabled={isLoading || !question.trim()} style={sendButtonStyle}>
                    {t("send")}
                </button>
            </footer>
        </div>
    );
}

const pageStyle: CSSProperties = { display: "flex", flexDirection: "column", height: "100vh", maxWidth: 900, margin: "0 auto", width: "100%" };
const headerStyle: CSSProperties = { display: "flex", alignItems: "center", gap: 12, padding: "12px 20px", background: "var(--chatbot-navbar-background)", color: "var(--chatbot-navbar-text)" };
const logoStyle: CSSProperties = { height: 28, width: 28, borderRadius: 6, background: "var(--chatbot-navbar-logo-background)", padding: 2 };
const titleStyle: CSSProperties = { fontSize: 18, fontWeight: 600 };
const mainStyle: CSSProperties = { flex: 1, overflowY: "auto", padding: 20, display: "flex", flexDirection: "column", gap: 16 };
const exchangeStyle: CSSProperties = { display: "flex", flexDirection: "column", gap: 8 };
const assistantBubbleStyle: CSSProperties = { alignSelf: "flex-start", maxWidth: "85%", background: "#f3f4f6", color: "#182033", padding: "10px 14px", borderRadius: 12 };
const userBubbleStyle: CSSProperties = { marginLeft: "auto", width: "fit-content", maxWidth: "85%", background: "var(--chatbot-user-bubble-background)", color: "var(--chatbot-user-bubble-text)", padding: "10px 14px", borderRadius: 12 };
const emptyHintStyle: CSSProperties = { color: "#6b7280", fontSize: 14 };
const loadingStyle: CSSProperties = { color: "#6b7280", fontStyle: "italic" };
const errorStyle: CSSProperties = { color: "#b91c1c", background: "#fee2e2", padding: "10px 14px", borderRadius: 8 };
const composerStyle: CSSProperties = { display: "flex", gap: 8, padding: 16, borderTop: "1px solid #e5e7eb" };
const textareaStyle: CSSProperties = { flex: 1, resize: "none", padding: "10px 12px", borderRadius: 10, border: "1px solid #d1d5db", fontFamily: "inherit", fontSize: 15 };
const sendButtonStyle: CSSProperties = { padding: "0 18px", borderRadius: 10, border: "none", background: "var(--chatbot-navbar-background)", color: "var(--chatbot-navbar-text)", cursor: "pointer", fontWeight: 600 };
