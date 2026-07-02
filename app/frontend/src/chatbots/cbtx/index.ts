import Chat from "./pages/chat/Chat";
import i18n from "./i18n/config";
import LayoutWrapper from "./layoutWrapper";
import { Component as NoPage } from "./pages/NoPage";

export const cbtxChatbot = {
    name: "cbtx",
    LayoutWrapper,
    Chat,
    NoPage,
    i18n
} as const;
