import { useMemo } from "react";
import { IconButton } from "@fluentui/react";
import { useTranslation } from "react-i18next";

import appLogo from "../../../../assets/applogo.svg";
import { buildOptionTexts, ChatbotAnswer } from "../../../shared/answer";
import { ChatAppResponse, SpeechConfig } from "../../api";
import { SpeechOutputBrowser } from "../../../lemon/components/Answer/SpeechOutputBrowser";
import { SpeechOutputAzure } from "../../../lemon/components/Answer/SpeechOutputAzure";

interface Props {
    answer: ChatAppResponse;
    index: number;
    speechConfig: SpeechConfig;
    assistantName: string;
    buildCitationPath: (reference: string) => string;
    isSelected?: boolean;
    isStreaming: boolean;
    onCitationClicked: (filePath: string) => void;
    onThoughtProcessClicked: () => void;
    onSupportingContentClicked: () => void;
    onFollowupQuestionClicked?: (question: string) => void;
    showFollowupQuestions?: boolean;
    showSpeechOutputBrowser?: boolean;
    showSpeechOutputAzure?: boolean;
    optionSelectedValue?: string;
    optionsLocked?: boolean;
    onOptionSelected?: (value: string) => void;
    onOptionOther?: () => void;
}

export const Answer = (props: Props) => {
    const { t } = useTranslation();
    const optionTexts = useMemo(() => buildOptionTexts(t), [t]);
    const hasThoughtProcess = Array.isArray(props.answer.context?.thoughts) && props.answer.context.thoughts.length > 0;

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
            optionTexts={optionTexts}
            optionSelectedValue={props.optionSelectedValue}
            optionsLocked={props.optionsLocked}
            onOptionSelected={props.onOptionSelected}
            onOptionOther={props.onOptionOther}
            assistantLogoSrc={appLogo}
            assistantLogoAlt={`${props.assistantName} logo`}
            assistantName={props.assistantName}
            copyLabel={t("tooltips.copy")}
            copiedLabel={t("tooltips.copied")}
            citationLabel={t("citationWithColon")}
            followupQuestionsLabel={t("followupQuestions")}
            buildCitationPath={props.buildCitationPath}
            extraHeaderActions={
                <IconButton
                    style={{ color: "black" }}
                    iconProps={{ iconName: "Lightbulb" }}
                    title={t("tooltips.showThoughtProcess")}
                    ariaLabel={t("tooltips.showThoughtProcess")}
                    onClick={props.onThoughtProcessClicked}
                    disabled={!hasThoughtProcess || props.isStreaming}
                />
            }
            SpeechOutputBrowserComponent={SpeechOutputBrowser}
            SpeechOutputAzureComponent={SpeechOutputAzure}
        />
    );
};
