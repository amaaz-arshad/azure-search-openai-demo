import { useTranslation } from "react-i18next";

import { ChatbotAnswer, type CitationDetail } from "../../../shared/answer";
import { ChatAppResponse, getCitationFilePath, SpeechConfig } from "../../api";
import { SpeechOutputBrowser } from "./SpeechOutputBrowser";
import { SpeechOutputAzure } from "./SpeechOutputAzure";
import fbnLogo from "../../assets/fbn.png";

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

const buildPublishOneUrl = (reference: string): string | null => {
    const documentId = reference.match(/\.([0-9]+)\.md$/)?.[1];
    return documentId ? `https://fbn.publishone.nl/document/${documentId}/content` : null;
};

const getCitationLabel = (detail: CitationDetail): string => detail.reference.replace(/\.\d+\.md$/, "");

export const Answer = (props: Props) => {
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
            assistantLogoSrc={fbnLogo}
            assistantLogoAlt={`${t("headerTitle")} logo`}
            assistantName={t("headerTitle")}
            copyLabel={t("tooltips.copy")}
            copiedLabel={t("tooltips.copied")}
            citationLabel={t("citationWithColon")}
            followupQuestionsLabel={t("followupQuestions")}
            buildCitationPath={reference => getCitationFilePath(reference)}
            getNonWebCitationAction={detail => ({
                label: getCitationLabel(detail),
                onClick: () => {
                    const publishOneUrl = buildPublishOneUrl(detail.reference);
                    if (publishOneUrl) {
                        window.open(publishOneUrl, "_blank", "noopener,noreferrer");
                        return;
                    }

                    props.onCitationClicked(getCitationFilePath(detail.reference));
                }
            })}
            getCitationListAction={detail => {
                const publishOneUrl = buildPublishOneUrl(detail.reference);
                if (!publishOneUrl) {
                    return {
                        label: detail.reference,
                        onClick: () => props.onCitationClicked(getCitationFilePath(detail.reference))
                    };
                }

                return {
                    label: getCitationLabel(detail),
                    title: detail.reference,
                    onClick: () => window.open(publishOneUrl, "_blank", "noopener,noreferrer")
                };
            }}
            SpeechOutputBrowserComponent={SpeechOutputBrowser}
            SpeechOutputAzureComponent={SpeechOutputAzure}
        />
    );
};
