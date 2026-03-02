import type { ComponentType } from "react";
import type { i18n as I18nInstance } from "i18next";

import { nerilioChatbot } from "./nerilio";
import { steuertippsChatbot } from "./steuertipps";

export interface ChatbotDefinition {
    name: string;
    LayoutWrapper: ComponentType;
    Chat: ComponentType;
    NoPage: ComponentType;
    i18n: I18nInstance;
}

export const chatbotDefinitions: ChatbotDefinition[] = [nerilioChatbot, steuertippsChatbot];
