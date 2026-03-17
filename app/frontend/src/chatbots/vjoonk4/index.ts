import Chat from "./pages/chat/Chat";
import i18n from "./i18n/config";
import LayoutWrapper from "./layoutWrapper";
import { Component as NoPage } from "./pages/NoPage";

export const vjoonk4Chatbot = {
    name: "vjoonk4",
    LayoutWrapper,
    Chat,
    NoPage,
    i18n
} as const;
