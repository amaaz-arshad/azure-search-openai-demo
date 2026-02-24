import { useMemo, useState } from "react";
import { Stack, IconButton } from "@fluentui/react";
import { useTranslation } from "react-i18next";
import DOMPurify from "dompurify";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";

import styles from "./Answer.module.css";
import { ChatAppResponse, getCitationFilePath, SpeechConfig } from "../../api";
import { parseAnswerToHtml } from "./AnswerParser";
import { AnswerIcon } from "./AnswerIcon";
import { SpeechOutputBrowser } from "./SpeechOutputBrowser";
import { SpeechOutputAzure } from "./SpeechOutputAzure";
import knollLogo from "../../assets/knoll.png";
import rehypeSlug from "rehype-slug";
import rehypeAutolinkHeadings from "rehype-autolink-headings";
import supersub from "remark-supersub";

const cleanSpeechText = (rawText: string): string => {
    let cleaned = rawText;

    cleaned = cleaned.replace(/```[\s\S]*?```/g, " ");
    cleaned = cleaned.replace(/`([^`]+)`/g, "$1");
    cleaned = cleaned.replace(/!\[([^\]]*)\]\([^)]+\)/g, "$1");
    cleaned = cleaned.replace(/\[([^\]]+)\]\([^)]+\)/g, "$1");
    cleaned = cleaned.replace(/<((?:https?:\/\/|mailto:)[^>]+)>/g, "$1");
    cleaned = cleaned.replace(/^\s{0,3}#{1,6}\s+/gm, "");
    cleaned = cleaned.replace(/^\s{0,3}>\s?/gm, "");
    cleaned = cleaned.replace(/^\s*[-*+]\s+/gm, "");
    cleaned = cleaned.replace(/^\s*\d+\.\s+/gm, "");
    cleaned = cleaned.replace(/(\*\*|__)(.*?)\1/g, "$2");
    cleaned = cleaned.replace(/(\*|_)(.*?)\1/g, "$2");
    cleaned = cleaned.replace(/~~(.*?)~~/g, "$1");
    cleaned = cleaned.replace(/^\s*\|?[-:\s|]+\|?\s*$/gm, " ");
    cleaned = cleaned.replace(/\|/g, " ");
    cleaned = cleaned.replace(/\[\^?\d+\]/g, " ");
    cleaned = cleaned.replace(/\s*\n+\s*/g, ". ");
    cleaned = cleaned.replace(/\s{2,}/g, " ");

    return cleaned.trim();
};

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

export const Answer = ({
    answer,
    index,
    speechConfig,
    isSelected,
    isStreaming,
    onCitationClicked,
    onThoughtProcessClicked,
    onSupportingContentClicked,
    onFollowupQuestionClicked,
    showFollowupQuestions,
    showSpeechOutputAzure,
    showSpeechOutputBrowser
}: Props) => {
    const followupQuestions = answer.context?.followup_questions;
    const parsedAnswer = useMemo(() => parseAnswerToHtml(answer, isStreaming, onCitationClicked), [answer, isStreaming, onCitationClicked]);
    const { t } = useTranslation();
    const sanitizedAnswerHtml = DOMPurify.sanitize(parsedAnswer.answerHtml);
    const [copied, setCopied] = useState(false);

    const handleCopy = () => {
        const tempElement = document.createElement("div");
        tempElement.innerHTML = sanitizedAnswerHtml;
        tempElement.querySelectorAll("sup").forEach(node => node.remove());
        tempElement.querySelectorAll(".citationStepBadge").forEach(node => node.remove());
        const textToCopy = tempElement.textContent ?? "";

        navigator.clipboard
            .writeText(textToCopy)
            .then(() => {
                setCopied(true);
                setTimeout(() => setCopied(false), 2000);
            })
            .catch(err => console.error("Failed to copy text: ", err));
    };

    const answerForSpeech = useMemo(() => {
        const temp = document.createElement("div");
        temp.innerHTML = sanitizedAnswerHtml;
        temp.querySelectorAll("sup, .citationStepBadge, .citationBadgeContainer").forEach(node => node.remove());
        const plainText = temp.textContent ?? "";
        return cleanSpeechText(plainText);
    }, [sanitizedAnswerHtml]);

    return (
        <Stack className={`${styles.answerContainer} ${isSelected && styles.selected}`} verticalAlign="space-between">
            <Stack.Item>
                <Stack horizontal horizontalAlign="space-between">
                    {/* <AnswerIcon /> */}
                    <div className={styles.assistantHeader}>
                        <img src={knollLogo} alt="KNOLL logo" className={styles.assistantAvatar} />
                        <div className={styles.assistantName}>{t("headerTitle")}</div>
                    </div>
                    <div>
                        <IconButton
                            style={{ color: "black" }}
                            iconProps={{ iconName: copied ? "CheckMark" : "Copy" }}
                            title={copied ? t("tooltips.copied") : t("tooltips.copy")}
                            ariaLabel={copied ? t("tooltips.copied") : t("tooltips.copy")}
                            onClick={handleCopy}
                        />
                        {/* <IconButton
                            style={{ color: "black" }}
                            iconProps={{ iconName: "Lightbulb" }}
                            title={t("tooltips.showThoughtProcess")}
                            ariaLabel={t("tooltips.showThoughtProcess")}
                            onClick={() => onThoughtProcessClicked()}
                            disabled={!answer.context?.thoughts?.length || isStreaming}
                        />
                        <IconButton
                            style={{ color: "black" }}
                            iconProps={{ iconName: "ClipboardList" }}
                            title={t("tooltips.showSupportingContent")}
                            ariaLabel={t("tooltips.showSupportingContent")}
                            onClick={() => onSupportingContentClicked()}
                            disabled={!answer.context?.data_points || isStreaming}
                        /> */}
                        {showSpeechOutputAzure && <SpeechOutputAzure answer={answerForSpeech} isStreaming={isStreaming} />}
                        {showSpeechOutputBrowser && <SpeechOutputBrowser answer={sanitizedAnswerHtml} />}
                    </div>
                </Stack>
            </Stack.Item>

            <Stack.Item grow>
                <ReactMarkdown children={sanitizedAnswerHtml} rehypePlugins={[rehypeRaw]} remarkPlugins={[remarkGfm, supersub]} />
            </Stack.Item>

            {!!parsedAnswer.citations.length && !isStreaming && (
                <Stack.Item>
                    <Stack horizontal wrap tokens={{ childrenGap: 5 }}>
                        <span className={styles.citationLearnMore}>{t("citationWithColon")}</span>
                        {parsedAnswer.citations.map(citation => {
                            const isWeb = citation.isWeb;
                            const displayIndex = citation.index;
                            const reference = citation.reference;
                            if (isWeb) {
                                // Attempt to find the matching web data point to retrieve its title
                                const webEntry = answer.context?.data_points.external_results_metadata?.find(w => w.url === reference);
                                const titleOrUrl = webEntry?.title?.trim() ? webEntry.title : reference;
                                return (
                                    <span key={`${reference}-${displayIndex}`} className={styles.citationEntry}>
                                        <a className={styles.citation} title={reference} href={reference} target="_blank" rel="noopener noreferrer">
                                            {`${displayIndex}. ${titleOrUrl}`}
                                        </a>
                                    </span>
                                );
                            } else {
                                const path = getCitationFilePath(reference);
                                return (
                                    <span key={`${reference}-${displayIndex}`} className={styles.citationEntry}>
                                        <a
                                            className={styles.citation}
                                            title={reference}
                                            onClick={e => {
                                                e.preventDefault();
                                                onCitationClicked(path);
                                            }}
                                        >
                                            {`${displayIndex}. ${reference}`}
                                        </a>
                                    </span>
                                );
                            }
                        })}
                    </Stack>
                </Stack.Item>
            )}

            {!!followupQuestions?.length && showFollowupQuestions && onFollowupQuestionClicked && (
                <Stack.Item>
                    <Stack horizontal wrap className={`${!!parsedAnswer.citations.length ? styles.followupQuestionsList : ""}`} tokens={{ childrenGap: 6 }}>
                        <span className={styles.followupQuestionLearnMore}>{t("followupQuestions")}</span>
                        {followupQuestions.map((x, i) => {
                            return (
                                <a key={i} className={styles.followupQuestion} title={x} onClick={() => onFollowupQuestionClicked(x)}>
                                    {`${x}`}
                                </a>
                            );
                        })}
                    </Stack>
                </Stack.Item>
            )}
        </Stack>
    );
};
