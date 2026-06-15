import { useCallback, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { ComponentType, ImgHTMLAttributes, ReactNode } from "react";
import { Stack, IconButton } from "@fluentui/react";
import { PrismLight as SyntaxHighlighter } from "react-syntax-highlighter";
import type { SyntaxHighlighterProps } from "react-syntax-highlighter";
import bash from "react-syntax-highlighter/dist/esm/languages/prism/bash";
import css from "react-syntax-highlighter/dist/esm/languages/prism/css";
import javascript from "react-syntax-highlighter/dist/esm/languages/prism/javascript";
import json from "react-syntax-highlighter/dist/esm/languages/prism/json";
import jsx from "react-syntax-highlighter/dist/esm/languages/prism/jsx";
import markdown from "react-syntax-highlighter/dist/esm/languages/prism/markdown";
import markup from "react-syntax-highlighter/dist/esm/languages/prism/markup";
import python from "react-syntax-highlighter/dist/esm/languages/prism/python";
import sql from "react-syntax-highlighter/dist/esm/languages/prism/sql";
import tsx from "react-syntax-highlighter/dist/esm/languages/prism/tsx";
import typescript from "react-syntax-highlighter/dist/esm/languages/prism/typescript";
import yaml from "react-syntax-highlighter/dist/esm/languages/prism/yaml";
import { oneLight } from "react-syntax-highlighter/dist/esm/styles/prism";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkBreaks from "remark-breaks";
import supersub from "remark-supersub";

import styles from "./SharedAnswer.module.css";
import { CitationDetail, isCitationHref, parseAnswerToMarkdown, stripCitationLinks } from "./answerParsing";

SyntaxHighlighter.registerLanguage("bash", bash);
SyntaxHighlighter.registerLanguage("css", css);
SyntaxHighlighter.registerLanguage("html", markup);
SyntaxHighlighter.registerLanguage("javascript", javascript);
SyntaxHighlighter.registerLanguage("js", javascript);
SyntaxHighlighter.registerLanguage("json", json);
SyntaxHighlighter.registerLanguage("jsx", jsx);
SyntaxHighlighter.registerLanguage("markdown", markdown);
SyntaxHighlighter.registerLanguage("md", markdown);
SyntaxHighlighter.registerLanguage("markup", markup);
SyntaxHighlighter.registerLanguage("python", python);
SyntaxHighlighter.registerLanguage("py", python);
SyntaxHighlighter.registerLanguage("sql", sql);
SyntaxHighlighter.registerLanguage("tsx", tsx);
SyntaxHighlighter.registerLanguage("typescript", typescript);
SyntaxHighlighter.registerLanguage("ts", typescript);
SyntaxHighlighter.registerLanguage("xml", markup);
SyntaxHighlighter.registerLanguage("yaml", yaml);
SyntaxHighlighter.registerLanguage("yml", yaml);

type ChatAppResponseLike = Parameters<typeof parseAnswerToMarkdown>[0];

type SpeechOutputBrowserProps = {
    answer: string;
};

type SpeechOutputAzureProps = {
    answer: string;
    isStreaming: boolean;
};

type NonWebCitationAction = {
    label: string;
    onClick: () => void;
};

type CitationListAction = {
    label: string;
    title?: string;
    href?: string;
    onClick?: () => void;
};

type Props = {
    answer: ChatAppResponseLike;
    isSelected?: boolean;
    isStreaming: boolean;
    onCitationClicked: (filePath: string) => void;
    onFollowupQuestionClicked?: (question: string) => void;
    showFollowupQuestions?: boolean;
    showSpeechOutputBrowser?: boolean;
    showSpeechOutputAzure?: boolean;
    assistantLogoSrc: string;
    assistantLogoAlt: string;
    assistantLogoVariant?: "avatar" | "wordmark";
    assistantLogoClassName?: string;
    assistantLogoPlacement?: "inside" | "outside-left";
    assistantName?: string;
    showAssistantName?: boolean;
    showCopyButton?: boolean;
    copyLabel: string;
    copiedLabel: string;
    citationLabel: string;
    followupQuestionsLabel: string;
    buildCitationPath: (reference: string) => string;
    getCitationListAction?: (detail: CitationDetail) => CitationListAction;
    getNonWebCitationAction?: (detail: CitationDetail) => NonWebCitationAction;
    extraHeaderActions?: ReactNode;
    SpeechOutputBrowserComponent?: ComponentType<SpeechOutputBrowserProps>;
    SpeechOutputAzureComponent?: ComponentType<SpeechOutputAzureProps>;
    // Display-only transform applied to the answer text before parsing/rendering.
    preprocessAnswerText?: (text: string) => string;
};

const syntaxStyle = oneLight as SyntaxHighlighterProps["style"];

const allowedImageSrc = (src?: string | null) =>
    !!src && (src.startsWith("https://") || src.startsWith("http://") || src.startsWith("data:image/"));

const allowedLinkHref = (href?: string | null) =>
    !!href && (href.startsWith("https://") || href.startsWith("http://") || href.startsWith("mailto:") || href.startsWith("tel:"));

const normalizeLanguage = (language: string | undefined) => {
    if (!language) {
        return undefined;
    }

    const normalizedLanguage = language.toLowerCase();
    if (normalizedLanguage === "html" || normalizedLanguage === "xml" || normalizedLanguage === "svg") {
        return "markup";
    }
    if (normalizedLanguage === "shell" || normalizedLanguage === "sh" || normalizedLanguage === "console") {
        return "bash";
    }
    if (normalizedLanguage === "yml") {
        return "yaml";
    }
    if (normalizedLanguage === "md") {
        return "markdown";
    }

    return normalizedLanguage;
};

const buildCitationTitle = (detail: CitationDetail): string | undefined => {
    const stepBadgeLabel = detail.stepSource ?? detail.stepLabel;
    if (detail.stepNumber !== undefined) {
        return `Linked to Step ${detail.stepNumber}${detail.stepLabel ? `: ${detail.stepLabel}` : ""}${detail.stepSource ? ` (${detail.stepSource})` : ""}`;
    }
    return stepBadgeLabel ? `Linked to ${stepBadgeLabel}` : detail.reference;
};

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

const CodeBlock = ({
    code,
    language,
    copyLabel,
    copiedLabel
}: {
    code: string;
    language?: string;
    copyLabel: string;
    copiedLabel: string;
}) => {
    const [copied, setCopied] = useState(false);
    const displayLanguage = language || "text";

    const copyCode = () => {
        navigator.clipboard
            .writeText(code)
            .then(() => {
                setCopied(true);
                setTimeout(() => setCopied(false), 2000);
            })
            .catch(err => console.error("Failed to copy code: ", err));
    };

    return (
        <div className={styles.codeBlockShell}>
            <div className={styles.codeBlockToolbar}>
                <span className={styles.codeBlockLanguage}>{displayLanguage}</span>
                <button type="button" className={styles.codeBlockCopyButton} onClick={copyCode}>
                    {copied ? copiedLabel : copyLabel}
                </button>
            </div>
            <SyntaxHighlighter
                language={normalizeLanguage(language)}
                style={syntaxStyle}
                wrapLongLines
                customStyle={{
                    margin: 0,
                    borderRadius: 0,
                    background: "transparent",
                    fontSize: "0.92rem",
                    lineHeight: 1.6,
                    padding: "1rem 1.1rem"
                }}
                codeTagProps={{ style: { fontFamily: "Consolas, Monaco, 'Courier New', monospace" } }}
            >
                {code}
            </SyntaxHighlighter>
        </div>
    );
};

const ScrollableTable = ({ children }: { children?: ReactNode }) => {
    const scrollRef = useRef<HTMLDivElement>(null);
    const [edges, setEdges] = useState<{ left: boolean; right: boolean }>({ left: false, right: false });

    const updateEdges = useCallback(() => {
        const el = scrollRef.current;
        if (!el) {
            return;
        }
        const maxScroll = el.scrollWidth - el.clientWidth;
        // 1px slack so sub-pixel rounding at the extremes doesn't leave a shadow stuck on.
        const left = el.scrollLeft > 1;
        const right = el.scrollLeft < maxScroll - 1;
        setEdges(prev => (prev.left === left && prev.right === right ? prev : { left, right }));
    }, []);

    useLayoutEffect(() => {
        const el = scrollRef.current;
        if (!el) {
            return;
        }
        updateEdges();
        // Re-check when the viewport or the table's own width changes (streamed
        // content growing, rotate/resize): either can flip whether the table
        // still overflows in a given direction.
        const observer = new ResizeObserver(updateEdges);
        observer.observe(el);
        const table = el.firstElementChild;
        if (table) {
            observer.observe(table);
        }
        return () => observer.disconnect();
    }, [updateEdges]);

    return (
        <div
            className={styles.tableScrollFrame}
            data-can-scroll-left={edges.left ? "1" : undefined}
            data-can-scroll-right={edges.right ? "1" : undefined}
        >
            <div className={styles.tableScroll} ref={scrollRef} onScroll={updateEdges}>
                <table className={styles.answerTable}>{children}</table>
            </div>
        </div>
    );
};

export const ChatbotAnswer = ({
    answer,
    isSelected,
    isStreaming,
    onCitationClicked,
    onFollowupQuestionClicked,
    showFollowupQuestions,
    showSpeechOutputBrowser,
    showSpeechOutputAzure,
    assistantLogoSrc,
    assistantLogoAlt,
    assistantLogoVariant = "avatar",
    assistantLogoClassName,
    assistantLogoPlacement = "inside",
    assistantName,
    showAssistantName = true,
    showCopyButton = true,
    copyLabel,
    copiedLabel,
    citationLabel,
    followupQuestionsLabel,
    buildCitationPath,
    getCitationListAction,
    getNonWebCitationAction,
    extraHeaderActions,
    SpeechOutputBrowserComponent,
    SpeechOutputAzureComponent,
    preprocessAnswerText
}: Props) => {
    const followupQuestions = answer.context?.followup_questions;
    // Apply an optional display-only text transform (e.g. strip hidden markers) without
    // mutating the stored answer, so the original content still replays into history.
    const displayAnswer = useMemo(() => {
        if (!preprocessAnswerText) {
            return answer;
        }
        const content = answer.message?.content;
        if (typeof content !== "string") {
            return answer;
        }
        return { ...answer, message: { ...answer.message, content: preprocessAnswerText(content) } };
    }, [answer, preprocessAnswerText]);
    const parsedAnswer = useMemo(() => parseAnswerToMarkdown(displayAnswer, isStreaming), [displayAnswer, isStreaming]);
    const [copied, setCopied] = useState(false);
    const assistantLogoClasses = [assistantLogoVariant === "wordmark" ? styles.assistantWordmark : styles.assistantAvatar, assistantLogoClassName]
        .filter(Boolean)
        .join(" ");
    const useOutsideLeftAvatar = assistantLogoPlacement === "outside-left" && assistantLogoVariant === "avatar";
    const showHeaderActions =
        Boolean(extraHeaderActions) ||
        showCopyButton ||
        Boolean(showSpeechOutputAzure && SpeechOutputAzureComponent) ||
        Boolean(showSpeechOutputBrowser && SpeechOutputBrowserComponent);
    const showInsideAssistantHeader = !useOutsideLeftAvatar;
    const renderHeaderRow = (showInsideAssistantHeader && (assistantLogoSrc || (showAssistantName && assistantName))) || showHeaderActions;

    const copyableMarkdown = useMemo(() => stripCitationLinks(parsedAnswer.markdown), [parsedAnswer.markdown]);
    const answerForSpeech = useMemo(() => cleanSpeechText(copyableMarkdown), [copyableMarkdown]);

    const openNonWebCitation = (detail: CitationDetail) => {
        const customAction = getNonWebCitationAction?.(detail);
        if (customAction) {
            customAction.onClick();
            return;
        }

        onCitationClicked(buildCitationPath(detail.reference));
    };

    const handleCopy = () => {
        navigator.clipboard
            .writeText(copyableMarkdown)
            .then(() => {
                setCopied(true);
                setTimeout(() => setCopied(false), 2000);
            })
            .catch(err => console.error("Failed to copy answer: ", err));
    };

    const markdownComponents = {
        a: ({ href, children }: { href?: string; children?: ReactNode }) => {
            if (isCitationHref(href)) {
                const detail = parsedAnswer.citationLinks[href];
                if (!detail) {
                    return <span>{children}</span>;
                }

                const title = buildCitationTitle(detail);
                if (detail.isWeb) {
                    return (
                        <span className={styles.citationBadgeContainer}>
                            <a
                                className={styles.inlineCitationLink}
                                title={title}
                                href={detail.reference}
                                target="_blank"
                                rel="noopener noreferrer"
                                onClick={event => event.stopPropagation()}
                            >
                                <sup className={styles.inlineCitationSup}>{detail.index}</sup>
                            </a>
                        </span>
                    );
                }

                return (
                    <span className={styles.citationBadgeContainer}>
                        <button
                            type="button"
                            className={styles.inlineCitationButton}
                            title={title}
                            onClick={event => {
                                event.preventDefault();
                                event.stopPropagation();
                                openNonWebCitation(detail);
                            }}
                        >
                            <sup className={styles.inlineCitationSup}>{detail.index}</sup>
                        </button>
                    </span>
                );
            }

            if (!allowedLinkHref(href)) {
                return <span>{children}</span>;
            }

            return (
                <a className={styles.markdownLink} href={href} target="_blank" rel="noopener noreferrer">
                    {children}
                </a>
            );
        },
        code: ({ inline, className, children }: { inline?: boolean; className?: string; children?: ReactNode }) => {
            const code = String(children ?? "").replace(/\n$/, "");
            if (inline) {
                return <code className={styles.inlineCode}>{code}</code>;
            }

            const languageMatch = /language-([\w-]+)/.exec(className || "");
            return <CodeBlock code={code} language={languageMatch?.[1]} copyLabel={copyLabel} copiedLabel={copiedLabel} />;
        },
        pre: ({ children }: { children?: ReactNode }) => <>{children}</>,
        table: ({ children }: { children?: ReactNode }) => <ScrollableTable>{children}</ScrollableTable>,
        img: ({ src, alt, ...props }: ImgHTMLAttributes<HTMLImageElement>) => {
            if (!allowedImageSrc(src)) {
                return <span>{alt || "Image omitted"}</span>;
            }

            return <img className={styles.answerImage} src={src} alt={alt || ""} loading="lazy" {...props} />;
        }
    };

    return (
        <div className={`${styles.answerShell} ${useOutsideLeftAvatar ? styles.answerShellWithOutsideAvatar : ""}`}>
            {useOutsideLeftAvatar && (
                <img
                    src={assistantLogoSrc}
                    alt={assistantLogoAlt}
                    className={`${assistantLogoClasses} ${styles.assistantAvatarOutside}`}
                    data-testid="assistant-avatar-outside"
                />
            )}
            <Stack
                className={`${styles.answerContainer} ${isSelected ? styles.selected : ""}`}
                data-testid="chatbot-answer-card"
                verticalAlign="space-between"
            >
                {renderHeaderRow && (
                    <Stack.Item>
                        <Stack horizontal className={`${styles.headerRow} ${!showInsideAssistantHeader ? styles.headerRowActionsOnly : ""}`}>
                            {showInsideAssistantHeader && (
                                <div className={styles.assistantHeader}>
                                    <img src={assistantLogoSrc} alt={assistantLogoAlt} className={assistantLogoClasses} />
                                    {showAssistantName && assistantName && <div className={styles.assistantName}>{assistantName}</div>}
                                </div>
                            )}
                            {showHeaderActions && (
                                <div className={styles.headerActions}>
                                    {extraHeaderActions}
                                    {showCopyButton && (
                                        <IconButton
                                            style={{ color: "var(--chatbot-answer-action-color, black)" }}
                                            styles={{
                                                rootHovered: { backgroundColor: "var(--chatbot-answer-action-hover-background, #f3f2f1)" },
                                                rootPressed: { backgroundColor: "var(--chatbot-answer-action-pressed-background, #edebe9)" }
                                            }}
                                            iconProps={{ iconName: copied ? "CheckMark" : "Copy" }}
                                            title={copied ? copiedLabel : copyLabel}
                                            ariaLabel={copied ? copiedLabel : copyLabel}
                                            onClick={handleCopy}
                                        />
                                    )}
                                    {showSpeechOutputAzure && SpeechOutputAzureComponent && (
                                        <SpeechOutputAzureComponent answer={answerForSpeech} isStreaming={isStreaming} />
                                    )}
                                    {showSpeechOutputBrowser && SpeechOutputBrowserComponent && <SpeechOutputBrowserComponent answer={answerForSpeech} />}
                                </div>
                            )}
                        </Stack>
                    </Stack.Item>
                )}

                <Stack.Item grow>
                    <div className={styles.answerMarkdown}>
                        <ReactMarkdown components={markdownComponents} remarkPlugins={[remarkGfm, remarkBreaks, supersub]}>
                            {parsedAnswer.markdown}
                        </ReactMarkdown>
                    </div>
                </Stack.Item>

                {!!parsedAnswer.citations.length && (
                    <Stack.Item>
                        <Stack horizontal wrap tokens={{ childrenGap: 8 }} className={styles.footerList}>
                            <span className={styles.sectionLabel}>{citationLabel}</span>
                            {parsedAnswer.citations.map(citation => {
                                const customAction = getCitationListAction?.(citation);

                                if (customAction?.href && allowedLinkHref(customAction.href)) {
                                    return (
                                        <span key={`${citation.reference}-${citation.index}`} className={styles.footerEntry}>
                                            <a
                                                className={styles.footerPill}
                                                title={customAction.title || customAction.label}
                                                href={customAction.href}
                                                target="_blank"
                                                rel="noopener noreferrer"
                                            >
                                                {`${citation.index}. ${customAction.label}`}
                                            </a>
                                        </span>
                                    );
                                }

                                if (customAction?.onClick) {
                                    return (
                                        <span key={`${citation.reference}-${citation.index}`} className={styles.footerEntry}>
                                            <button
                                                type="button"
                                                className={styles.footerPillButton}
                                                title={customAction.title || customAction.label}
                                                onClick={customAction.onClick}
                                            >
                                                {`${citation.index}. ${customAction.label}`}
                                            </button>
                                        </span>
                                    );
                                }

                                if (citation.isWeb) {
                                    const titleOrUrl = citation.displayLabel?.trim() || citation.reference;
                                    return (
                                        <span key={`${citation.reference}-${citation.index}`} className={styles.footerEntry}>
                                            <a className={styles.footerPill} title={titleOrUrl} href={citation.reference} target="_blank" rel="noopener noreferrer">
                                                {`${citation.index}. ${titleOrUrl}`}
                                            </a>
                                        </span>
                                    );
                                }

                                return (
                                    <span key={`${citation.reference}-${citation.index}`} className={styles.footerEntry}>
                                        <button
                                            type="button"
                                            className={styles.footerPillButton}
                                            title={citation.reference}
                                            onClick={() => openNonWebCitation(citation)}
                                        >
                                            {`${citation.index}. ${citation.reference}`}
                                        </button>
                                    </span>
                                );
                            })}
                        </Stack>
                    </Stack.Item>
                )}

                {!!followupQuestions?.length && showFollowupQuestions && onFollowupQuestionClicked && (
                    <Stack.Item>
                        <Stack horizontal wrap tokens={{ childrenGap: 8 }} className={styles.footerList}>
                            <span className={styles.sectionLabel}>{followupQuestionsLabel}</span>
                            {followupQuestions.map((question, index) => (
                                <button
                                    key={`${question}-${index}`}
                                    type="button"
                                    className={styles.followupPill}
                                    title={question}
                                    onClick={() => onFollowupQuestionClicked(question)}
                                >
                                    {question}
                                </button>
                            ))}
                        </Stack>
                    </Stack.Item>
                )}
            </Stack>
        </div>
    );
};
