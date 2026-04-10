import type { ComponentType } from "react";
import { useTranslation } from "react-i18next";

import { ChatbotAnswer } from "./ChatbotAnswer";
import { ChatAppResponse, getCitationFilePath, SpeechConfig } from "../../../api";

interface AnswerProps {
    answer: ChatAppResponse;
    index: number;
    speechConfig: SpeechConfig;
    isSelected?: boolean;
    isStreaming: boolean;
    onCitationClicked: (filePath: string) => void;
    onThoughtProcessClicked: () => void;
    onSupportingContentClicked: () => void;
    onFollowupQuestionClicked?: (question: string) => void;
    showFollowupQuestions?: boolean;
    showSpeechOutputBrowser?: boolean;
    showSpeechOutputAzure?: boolean;
}

type SpeechOutputBrowserComponent = ComponentType<{ answer: string }>;
type SpeechOutputAzureComponent = ComponentType<{ answer: string; isStreaming: boolean }>;

interface BotAnswerOptions {
    showAssistantName?: boolean;
    showCopyButton?: boolean;
    assistantLogoVariant?: "avatar" | "wordmark";
    assistantLogoClassName?: string;
    assistantLogoPlacement?: "inside" | "outside-left";
}

/**
 * Factory that creates a bot-specific Answer component.
 * Each bot only needs to provide its logo asset and optional display overrides.
 */
export function createBotAnswer(
    logoSrc: string,
    SpeechOutputBrowserComponent: SpeechOutputBrowserComponent,
    SpeechOutputAzureComponent: SpeechOutputAzureComponent,
    options: BotAnswerOptions = {}
) {
    return function Answer(props: AnswerProps) {
        const { t } = useTranslation();

        return (
            <ChatbotAnswer
                answer={props.answer}
                isSelected={props.isSelected}
                isStreaming={props.isStreaming}
                onCitationClicked={props.onCitationClicked}
                onFollowupQuestionClicked={props.onFollowupQuestionClicked}
                showFollowupQuestions={props.showFollowupQuestions}
                showSpeechOutputBrowser={props.showSpeechOutputBrowser}
                showSpeechOutputAzure={props.showSpeechOutputAzure}
                assistantLogoSrc={logoSrc}
                assistantLogoAlt={`${t("headerTitle")} logo`}
                assistantLogoVariant={options.assistantLogoVariant}
                assistantLogoClassName={options.assistantLogoClassName}
                assistantLogoPlacement={options.assistantLogoPlacement}
                assistantName={t("headerTitle")}
                showAssistantName={options.showAssistantName}
                showCopyButton={options.showCopyButton}
                copyLabel={t("tooltips.copy")}
                copiedLabel={t("tooltips.copied")}
                citationLabel={t("citationWithColon")}
                followupQuestionsLabel={t("followupQuestions")}
                buildCitationPath={reference => getCitationFilePath(reference)}
                SpeechOutputBrowserComponent={SpeechOutputBrowserComponent}
                SpeechOutputAzureComponent={SpeechOutputAzureComponent}
            />
        );
    };
}
