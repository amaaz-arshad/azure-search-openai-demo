import React from "react";
import ReactDOM from "react-dom/client";
import { Navigate, Outlet, RouterProvider, createBrowserRouter } from "react-router-dom";
import { HelmetProvider } from "react-helmet-async";
import { initializeIcons } from "@fluentui/react";
import { MsalProvider } from "@azure/msal-react";
import { AuthenticationResult, EventType, PublicClientApplication } from "@azure/msal-browser";
import { I18nextProvider } from "react-i18next";

import "./index.css";

import { chatbotDefinitions } from "./chatbots/registry";
import { GenericChatbotRoute } from "./chatbots/generic";
import { Component as SharedNoPage } from "./chatbots/shared/noPage/NoPage";
import { ChatbotThemeRoot } from "./chatbots/shared/theme/ChatbotThemeRoot";
import { EmbedBridge } from "./chatbots/shared/embed/EmbedBridge";
import { RouteErrorBoundary } from "./chatbots/shared/error/RouteErrorBoundary";
import { isEmbedMode } from "./chatbots/shared/embed/embedMode";
import i18n from "./chatbots/nerilio/i18n/config";
import ChatbotDirectory from "./pages/ChatbotDirectory";
import ManagePromptsPage from "./pages/ManagePrompts";
import FreeUsersPage from "./pages/FreeUsers";
import HyroxVisitsPage from "./pages/HyroxVisits";
import UploadFilesPage from "./pages/UploadFiles";
import { AdminLayout, EmbedDemoTab } from "./pages/admin";
import { msalConfig, useLogin } from "./authConfig";

initializeIcons();

declare global {
    interface Window {
        // Injected by the backend's anonymized /embed/<publicId> route so the SPA knows which bot to
        // mount without the readable name appearing in the URL. Lives inside the cross-origin iframe.
        __EMBED_CHATBOT_NAME__?: string;
    }
}

const embedMode = isEmbedMode();

// The anonymized embed route (/embed/<publicId>?embed=1) resolves the public ID server-side and
// injects the resolved chatbot name. Resolve it to a chatbot definition at startup.
const embedChatbotName = typeof window !== "undefined" ? window.__EMBED_CHATBOT_NAME__ : undefined;
const embedChatbot = embedChatbotName ? chatbotDefinitions.find(chatbot => chatbot.name === embedChatbotName) : undefined;

const wrapChatbotElement = (chatbot: (typeof chatbotDefinitions)[number], element: React.ReactNode) => (
    <ChatbotThemeRoot chatbotName={chatbot.name} embed={embedMode}>
        <I18nextProvider i18n={chatbot.i18n}>{element}</I18nextProvider>
        {embedMode && <EmbedBridge />}
    </ChatbotThemeRoot>
);

const chatbotRoutes = chatbotDefinitions.flatMap(chatbot => [
    {
        path: chatbot.name,
        element: wrapChatbotElement(chatbot, <chatbot.LayoutWrapper />),
        children: [
            {
                index: true,
                element: <chatbot.Chat />
            }
        ]
    },
    {
        path: `${chatbot.name}/*`,
        element: wrapChatbotElement(chatbot, <chatbot.NoPage />)
    }
]);

const router = createBrowserRouter([
    {
        // Pathless layout route: its errorElement catches any render/commit error bubbling up from ANY
        // child route (built-in bots, the dynamic /:botName generic bot, admin, embed) and renders a
        // friendly fallback instead of React Router's raw developer error page — so one stray error
        // (e.g. a browser extension tampering with the page) never white-screens the whole SPA. The
        // <Outlet/> just renders the matched child; it adds no path segment. See CHANGES.md 2026-07-09.
        element: <Outlet />,
        errorElement: <RouteErrorBoundary />,
        children: [
            {
                path: "/",
                element: (
                    <I18nextProvider i18n={i18n}>
                        <SharedNoPage />
                    </I18nextProvider>
                )
            },
            {
                // Consolidated internal admin shell: one password gate + tab bar over the former standalone
                // /chatbots, /manage-prompts, /upload-files, /free-users pages plus the embed-demo iframe.
                path: "/admin",
                element: <AdminLayout />,
                children: [
                    { index: true, element: <Navigate to="/admin/chatbots" replace /> },
                    { path: "chatbots", element: <ChatbotDirectory /> },
                    { path: "prompts", element: <ManagePromptsPage /> },
                    { path: "uploads", element: <UploadFilesPage /> },
                    { path: "users", element: <FreeUsersPage /> },
                    { path: "hyrox-visits", element: <HyroxVisitsPage /> },
                    { path: "embed", element: <EmbedDemoTab /> }
                ]
            },
            // Legacy admin URLs redirect into the matching /admin tab so existing bookmarks keep working.
            { path: "/chatbots", element: <Navigate to="/admin/chatbots" replace /> },
            { path: "/manage-prompts", element: <Navigate to="/admin/prompts" replace /> },
            { path: "/upload-files", element: <Navigate to="/admin/uploads" replace /> },
            { path: "/free-users", element: <Navigate to="/admin/users" replace /> },
            { path: "/public-test-users", element: <Navigate to="/admin/users" replace /> },
            ...chatbotRoutes,
            {
                // Anonymized embed target. The bot is chosen from the backend-injected name, never the URL.
                // A name with no built-in definition is a dynamic (provisioned) bot: mount it through the
                // generic route, which resolves it from /bot-config exactly as `/:botName` does.
                path: "/embed/:publicId",
                element: embedChatbot ? (
                    wrapChatbotElement(embedChatbot, <embedChatbot.LayoutWrapper />)
                ) : embedChatbotName ? (
                    <GenericChatbotRoute embedMode={embedMode} botName={embedChatbotName} />
                ) : (
                    <Navigate to="/" replace />
                ),
                children: embedChatbot ? [{ index: true, element: <embedChatbot.Chat /> }] : undefined
            },
            {
                // Dynamic (provisioned) bots resolved at runtime from /bot-config. Built-in bots and all
                // literal top-level routes rank higher, so only names not matched statically reach here; an
                // unknown/inactive name 404s and redirects home (same UX as the "*" fallback below).
                path: "/:botName",
                element: <GenericChatbotRoute embedMode={embedMode} />
            },
            {
                path: "/:botName/*",
                element: <GenericChatbotRoute embedMode={embedMode} />
            },
            {
                path: "*",
                element: <Navigate to="/" replace />
            }
        ]
    }
]);

const root = ReactDOM.createRoot(document.getElementById("root") as HTMLElement);

// Bootstrap the app once; conditionally wrap with MsalProvider when login is enabled
(async () => {
    let msalInstance: PublicClientApplication | undefined;

    if (useLogin) {
        msalInstance = new PublicClientApplication(msalConfig);
        try {
            await msalInstance.initialize();

            // Default active account to the first one if none is set
            if (!msalInstance.getActiveAccount() && msalInstance.getAllAccounts().length > 0) {
                msalInstance.setActiveAccount(msalInstance.getAllAccounts()[0]);
            }

            // Keep active account in sync on login success
            msalInstance.addEventCallback(event => {
                if (event.eventType === EventType.LOGIN_SUCCESS && event.payload) {
                    const result = event.payload as AuthenticationResult;
                    if (result.account) {
                        msalInstance!.setActiveAccount(result.account);
                    }
                }
            });
        } catch (e) {
            // Non-fatal: render the app even if MSAL initialization fails
            // eslint-disable-next-line no-console
            console.error("MSAL initialize failed", e);
            msalInstance = undefined;
        }
    }

    const appTree = (
        <React.StrictMode>
            <HelmetProvider>
                {useLogin && msalInstance ? (
                    <MsalProvider instance={msalInstance}>
                        <RouterProvider router={router} />
                    </MsalProvider>
                ) : (
                    <RouterProvider router={router} />
                )}
            </HelmetProvider>
        </React.StrictMode>
    );

    root.render(appTree);
})();
