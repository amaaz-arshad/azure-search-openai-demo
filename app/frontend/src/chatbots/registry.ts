import type { ComponentType } from "react";
import type { i18n as I18nInstance } from "i18next";

import { agindoChatbot } from "./agindo";
import { demoChatbot } from "./demo";
import { fbnChatbot } from "./fbn";
import { fhgChatbot } from "./fhg";
import { knollChatbot } from "./knoll";
import { lemonChatbot } from "./lemon";
import { moodleChatbot } from "./moodle";
import { nerilioChatbot } from "./nerilio";
import { publicTestChatbot } from "./public-test";
import { publishoneChatbot } from "./publishone";
import { rakChatbot } from "./rak";
import { sartoriusChatbot } from "./sartorius";
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
    agindoChatbot,
    nerilioChatbot,
    publicTestChatbot,
    rakChatbot,
    steuertippsChatbot,
    knollChatbot,
    lemonChatbot,
    moodleChatbot,
    publishoneChatbot,
    sartoriusChatbot,
    fbnChatbot,
    demoChatbot,
    fhgChatbot,
    vjoonk4Chatbot
];
