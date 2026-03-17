import type { ComponentType } from "react";
import type { i18n as I18nInstance } from "i18next";

import { demoChatbot } from "./demo";
import { fbnChatbot } from "./fbn";
import { fhgChatbot } from "./fhg";
import { knollChatbot } from "./knoll";
import { lemonChatbot } from "./lemon";
import { nerilioChatbot } from "./nerilio";
import { publishoneChatbot } from "./publishone";
import { steuertippsChatbot } from "./steuertipps";
import { vjoonk4Chatbot } from "./vjoonk4";

export interface ChatbotDefinition {
    name: string;
    LayoutWrapper: ComponentType;
    Chat: ComponentType;
    NoPage: ComponentType;
    i18n: I18nInstance;
}

export const chatbotDefinitions: ChatbotDefinition[] = [
    nerilioChatbot,
    steuertippsChatbot,
    knollChatbot,
    lemonChatbot,
    publishoneChatbot,
    fbnChatbot,
    demoChatbot,
    fhgChatbot,
    vjoonk4Chatbot
];
