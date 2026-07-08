import type { ComponentType } from "react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { ChatbotAnswer } from "./ChatbotAnswer";
import { buildOptionTexts } from "./optionMarkers";
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
    showCitations?: boolean;
    showSpeechOutputBrowser?: boolean;
    showSpeechOutputAzure?: boolean;
    // Interactive option buttons (tutor-mode bots). optionTexts is supplied by the
    // factory from the bot's i18n; the Chat page wires the rest.
    optionSelectedValue?: string;
    optionsLocked?: boolean;
    onOptionSelected?: (value: string) => void;
    onOptionOther?: () => void;
}

type SpeechOutputBrowserComponent = ComponentType<{ answer: string }>;
type SpeechOutputAzureComponent = ComponentType<{ answer: string; isStreaming: boolean }>;

interface BotAnswerOptions {
    showAssistantName?: boolean;
    showCopyButton?: boolean;
    assistantLogoVariant?: "avatar" | "wordmark";
    assistantLogoClassName?: string;
    assistantLogoPlacement?: "inside" | "outside-left";
    // Optional display-only transform applied to the answer text before rendering
    // (e.g. the HYROX assessment bot strips its hidden control markers). The stored
    // answer is left untouched so it still replays into the next request's history.
    preprocessAnswerText?: (text: string) => string;
    // Backend blob-proxy route used to resolve citation source files. Defaults to "content";
    // provisioned ("generic") bots pass "content2" because their files live in the content2
    // container and are not mirrored into content.
    citationContentRoot?: string;
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
        const optionTexts = useMemo(() => buildOptionTexts(t), [t]);

        return (
            <ChatbotAnswer
                answer={props.answer}
                isSelected={props.isSelected}
                isStreaming={props.isStreaming}
                onCitationClicked={props.onCitationClicked}
                onFollowupQuestionClicked={props.onFollowupQuestionClicked}
                showFollowupQuestions={props.showFollowupQuestions}
                showCitations={props.showCitations}
                showSpeechOutputBrowser={props.showSpeechOutputBrowser}
                showSpeechOutputAzure={props.showSpeechOutputAzure}
                optionTexts={optionTexts}
                optionSelectedValue={props.optionSelectedValue}
                optionsLocked={props.optionsLocked}
                onOptionSelected={props.onOptionSelected}
                onOptionOther={props.onOptionOther}
                assistantLogoSrc={logoSrc}
                assistantLogoAlt={`${t("headerTitle")} logo`}
                assistantLogoVariant={options.assistantLogoVariant}
                assistantLogoClassName={options.assistantLogoClassName}
                assistantLogoPlacement={options.assistantLogoPlacement}
                assistantName={t("headerTitle")}
                showAssistantName={options.showAssistantName}
                showCopyButton={options.showCopyButton}
                preprocessAnswerText={options.preprocessAnswerText}
                copyLabel={t("tooltips.copy")}
                copiedLabel={t("tooltips.copied")}
                citationLabel={t("citationWithColon")}
                followupQuestionsLabel={t("followupQuestions")}
                buildCitationPath={reference => getCitationFilePath(reference, options.citationContentRoot)}
                SpeechOutputBrowserComponent={SpeechOutputBrowserComponent}
                SpeechOutputAzureComponent={SpeechOutputAzureComponent}
            />
        );
    };
}
