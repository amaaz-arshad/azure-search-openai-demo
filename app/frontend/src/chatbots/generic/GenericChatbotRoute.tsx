import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { Navigate, useParams } from "react-router-dom";
import { I18nextProvider } from "react-i18next";

import { botConfigApi } from "../../api";
import type { BotConfig } from "../../api/models";
import { ChatbotThemeRoot } from "../shared/theme/ChatbotThemeRoot";
import { EmbedBridge } from "../shared/embed/EmbedBridge";
import { createGenericI18n } from "./createGenericI18n";
import { BotConfigContext } from "./botConfigContext";
import Layout from "./pages/layout/Layout";
import Chat from "./pages/chat/Chat";

const DEFAULT_PRIMARY = "#4b5563";

type Status = "loading" | "ready" | "notfound";

/**
 * Route element for `/:botName`. Resolves a dynamic (provisioned) bot at runtime from /bot-config and
 * renders the built-in lemon bot's UI verbatim, parameterized by the runtime config: theme from the
 * provisioned color, i18n from lemon's bundles overlaid with the provisioned greeting/disclaimer/title,
 * and identity (category, welcome, history) via BotConfigContext. Built-in / inactive / unknown names
 * 404 and redirect home. Built-in bots never reach here — their static routes rank higher.
 *
 * `botName` overrides the route param, for the anonymized embed route (`/embed/<publicId>`) where the
 * bot is named by the backend-injected `window.__EMBED_CHATBOT_NAME__` and never appears in the URL.
 */
export function GenericChatbotRoute({ embedMode, botName: botNameOverride }: { embedMode?: boolean; botName?: string }) {
    const { botName: routeBotName } = useParams();
    const botName = botNameOverride ?? routeBotName;
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
                <BotConfigContext.Provider value={config}>
                    <Layout>
                        <Chat />
                    </Layout>
                </BotConfigContext.Provider>
            </I18nextProvider>
            {/* Same host handshake the built-in bots mount, so an embedded dynamic bot announces
                readiness (chatbot:ready) exactly like they do. */}
            {embedMode && <EmbedBridge />}
        </ChatbotThemeRoot>
    );
}

const loadingStyle: CSSProperties = { height: "100vh" };
