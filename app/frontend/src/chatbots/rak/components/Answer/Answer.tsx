import { useContext } from "react";
import { useTranslation } from "react-i18next";

import { ChatbotAnswer } from "../../../shared/answer";
import { ChatAppResponse, getCitationFilePath, SpeechConfig } from "../../api";
import { LoginContext } from "../../loginContext";
import { SpeechOutputBrowser } from "./SpeechOutputBrowser";
import { SpeechOutputAzure } from "./SpeechOutputAzure";
import rakLogo from "../../../../assets/rak-round.png";

interface Props {
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

export const Answer = (props: Props) => {
    const { currentUser } = useContext(LoginContext);
    const { t } = useTranslation();

    const buildCitationPath = (reference: string) =>
        getCitationFilePath(reference, {
            chatbotName: "rak",
            chatbotUser: currentUser?.username
        });

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
            assistantLogoSrc={rakLogo}
            assistantLogoAlt={`${t("headerTitle")} logo`}
            assistantName={t("headerTitle")}
            copyLabel={t("tooltips.copy")}
            copiedLabel={t("tooltips.copied")}
            citationLabel={t("citationWithColon")}
            followupQuestionsLabel={t("followupQuestions")}
            buildCitationPath={buildCitationPath}
            SpeechOutputBrowserComponent={SpeechOutputBrowser}
            SpeechOutputAzureComponent={SpeechOutputAzure}
        />
    );
};
