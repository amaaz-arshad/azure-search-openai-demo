import React from "react";
import ReactDOM from "react-dom/client";
import { Navigate, RouterProvider, createBrowserRouter } from "react-router-dom";
import { HelmetProvider } from "react-helmet-async";
import { initializeIcons } from "@fluentui/react";
import { MsalProvider } from "@azure/msal-react";
import { AuthenticationResult, EventType, PublicClientApplication } from "@azure/msal-browser";
import { I18nextProvider } from "react-i18next";

import "./index.css";

import { chatbotDefinitions } from "./chatbots/registry";
import { Component as SharedNoPage } from "./chatbots/shared/noPage/NoPage";
import { ChatbotThemeRoot } from "./chatbots/shared/theme/ChatbotThemeRoot";
import i18n from "./chatbots/nerilio/i18n/config";
import ChatbotDirectory from "./pages/ChatbotDirectory";
import ManagePromptsPage from "./pages/ManagePromptsPage";
import PublicTestUsersPage from "./pages/PublicTestUsersPage";
import UploadFilesPage from "./pages/UploadFilesPage";
import { msalConfig, useLogin } from "./authConfig";

initializeIcons();

const wrapChatbotElement = (chatbot: (typeof chatbotDefinitions)[number], element: React.ReactNode) => (
    <ChatbotThemeRoot chatbotName={chatbot.name}>
        <I18nextProvider i18n={chatbot.i18n}>{element}</I18nextProvider>
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
        path: "/",
        element: (
            <I18nextProvider i18n={i18n}>
                <SharedNoPage />
            </I18nextProvider>
        )
    },
    {
        path: "/chatbots",
        element: <ChatbotDirectory />
    },
    {
        path: "/upload-files",
        element: <UploadFilesPage />
    },
    {
        path: "/public-test-users",
        element: <PublicTestUsersPage />
    },
    {
        path: "/manage-prompts",
        element: <ManagePromptsPage />
    },
    ...chatbotRoutes,
    {
        path: "*",
        element: <Navigate to="/" replace />
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
