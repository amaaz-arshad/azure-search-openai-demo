import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { Navigate, useParams } from "react-router-dom";
import { I18nextProvider } from "react-i18next";

import { botConfigApi } from "../../api";
import type { BotConfig } from "../../api/models";
import { ChatbotThemeRoot } from "../shared/theme/ChatbotThemeRoot";
import { createGenericI18n } from "./i18n/createGenericI18n";
import { GenericChat } from "./pages/chat/Chat";

const DEFAULT_PRIMARY = "#4b5563";

type Status = "loading" | "ready" | "notfound";

/**
 * Route element for `/:botName`. Resolves a dynamic (provisioned) bot at runtime from /bot-config:
 * built-in / inactive / unknown names 404 and redirect home (same UX as the old unknown-name fallback);
 * an active dynamic bot mounts a runtime-themed, runtime-i18n generic chat. Built-in bots never reach
 * here — their static routes rank higher.
 */
export function GenericChatbotRoute({ embedMode }: { embedMode?: boolean }) {
    const { botName } = useParams();
    const [status, setStatus] = useState<Status>("loading");
    const [config, setConfig] = useState<BotConfig | null>(null);

    useEffect(() => {
        let cancelled = false;
        setStatus("loading");
        setConfig(null);
        if (!botName) {
            setStatus("notfound");
            return;
        }
        botConfigApi(botName)
            .then(result => {
                if (!cancelled) {
                    setConfig(result);
                    setStatus("ready");
                }
            })
            .catch(() => {
                if (!cancelled) {
                    setStatus("notfound");
                }
            });
        return () => {
            cancelled = true;
        };
    }, [botName]);

    // New i18n instance per bot; rebuilt only when the resolved bot changes.
    const i18nInstance = useMemo(() => (config ? createGenericI18n(config) : null), [config?.botName]);

    if (status === "notfound") {
        return <Navigate to="/" replace />;
    }
    if (status === "loading" || !config || !i18nInstance) {
        return (
            <ChatbotThemeRoot chatbotName="generic" seed={{ primary: DEFAULT_PRIMARY }}>
                <div style={loadingStyle} aria-busy="true" />
            </ChatbotThemeRoot>
        );
    }
    return (
        <ChatbotThemeRoot chatbotName={config.botName} seed={{ primary: config.primaryColor ?? DEFAULT_PRIMARY }} embed={embedMode}>
            <I18nextProvider i18n={i18nInstance}>
                <GenericChat config={config} />
            </I18nextProvider>
        </ChatbotThemeRoot>
    );
}

const loadingStyle: CSSProperties = { height: "100vh" };
