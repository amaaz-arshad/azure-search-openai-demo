import type { ComponentType } from "react";
import type { i18n as I18nInstance } from "i18next";

import { agindoChatbot } from "./agindo";
import { bensbergChatbot } from "./bensberg";
import { demoChatbot } from "./demo";
import { fbnChatbot } from "./fbn";
import { fhgChatbot } from "./fhg";
import { hyroxAssessmentChatbot } from "./hyrox-assessment";
import { internalChatbot } from "./internal";
import { knollChatbot } from "./knoll";
import { lemonChatbot } from "./lemon";
import { moodleChatbot } from "./moodle";
import { nerilioChatbot } from "./nerilio";
import { freeChatbot } from "./free";
import { publishoneChatbot } from "./publishone";
import { rakChatbot } from "./rak";
import { sartoriusChatbot } from "./sartorius";
import { steuertippsChatbot } from "./steuertipps";
import { vjoonk4Chatbot } from "./vjoonk4";

export type ChatbotMode = "qna" | "tutor-qna" | "assessment";

export interface ChatbotMetadata {
    llm: string;
    reasoningEffort?: string;
    mode: ChatbotMode;
    agenticRetrievalDefault: boolean;
}

export interface ChatbotDefinition extends ChatbotMetadata {
    name: string;
    LayoutWrapper: ComponentType;
    Chat: ComponentType;
    NoPage: ComponentType;
    i18n: I18nInstance;
}

export const chatbotDefinitions: ChatbotDefinition[] = [
    { ...agindoChatbot, llm: "gpt-4.1", mode: "qna", agenticRetrievalDefault: false },
    { ...bensbergChatbot, llm: "gpt-5.4-mini", reasoningEffort: "medium", mode: "tutor-qna", agenticRetrievalDefault: true },
    { ...nerilioChatbot, llm: "gpt-4.1-mini", mode: "qna", agenticRetrievalDefault: false },
    { ...freeChatbot, llm: "gpt-4.1", mode: "qna", agenticRetrievalDefault: false },
    { ...rakChatbot, llm: "gpt-4.1", mode: "qna", agenticRetrievalDefault: false },
    { ...steuertippsChatbot, llm: "gpt-5.4-mini", reasoningEffort: "medium", mode: "tutor-qna", agenticRetrievalDefault: false },
    { ...knollChatbot, llm: "gpt-5.4-mini", reasoningEffort: "medium", mode: "tutor-qna", agenticRetrievalDefault: false },
    { ...lemonChatbot, llm: "gpt-5.4-mini", reasoningEffort: "medium", mode: "tutor-qna", agenticRetrievalDefault: true },
    { ...hyroxAssessmentChatbot, llm: "gpt-5.4-mini", reasoningEffort: "high", mode: "assessment", agenticRetrievalDefault: false },
    { ...internalChatbot, llm: "gpt-5.4-mini", reasoningEffort: "medium", mode: "tutor-qna", agenticRetrievalDefault: false },
    { ...moodleChatbot, llm: "gpt-5.4-mini", reasoningEffort: "medium", mode: "tutor-qna", agenticRetrievalDefault: false },
    { ...publishoneChatbot, llm: "gpt-5.4-mini", reasoningEffort: "medium", mode: "tutor-qna", agenticRetrievalDefault: false },
    { ...sartoriusChatbot, llm: "gpt-4.1", mode: "qna", agenticRetrievalDefault: false },
    { ...fbnChatbot, llm: "gpt-5.4-mini", reasoningEffort: "medium", mode: "tutor-qna", agenticRetrievalDefault: false },
    { ...demoChatbot, llm: "gpt-5.4-mini", reasoningEffort: "medium", mode: "tutor-qna", agenticRetrievalDefault: false },
    { ...fhgChatbot, llm: "gpt-4.1", mode: "qna", agenticRetrievalDefault: false },
    { ...vjoonk4Chatbot, llm: "gpt-4.1", mode: "qna", agenticRetrievalDefault: false }
];
