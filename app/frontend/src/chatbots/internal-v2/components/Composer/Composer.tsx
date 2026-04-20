import { useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Send24Filled, Stop24Filled } from "@fluentui/react-icons";

import { SpeechInput } from "../../../lemon/components/QuestionInput/SpeechInput";
import { LoginContext } from "../../loginContext";
import { requireLogin } from "../../authConfig";
import styles from "./Composer.module.css";

interface Props {
    onSend: (question: string) => void;
    onStop: () => void;
    disabled: boolean;
    isStreaming: boolean;
    isLoading: boolean;
    placeholder?: string;
    clearOnSend?: boolean;
    initQuestion?: string;
    showSpeechInput?: boolean;
}

export const Composer = ({
    onSend,
    onStop,
    disabled,
    isStreaming,
    isLoading,
    placeholder,
    clearOnSend,
    initQuestion,
    showSpeechInput
}: Props) => {
    const [question, setQuestion] = useState<string>("");
    const [isComposing, setIsComposing] = useState(false);
    const textareaRef = useRef<HTMLTextAreaElement | null>(null);
    const { loggedIn } = useContext(LoginContext);
    const { t } = useTranslation();

    useEffect(() => {
        if (initQuestion !== undefined) {
            setQuestion(initQuestion);
        }
    }, [initQuestion]);

    useEffect(() => {
        const el = textareaRef.current;
        if (!el) return;
        el.style.height = "auto";
        el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
    }, [question]);

    const disableAccess = requireLogin && !loggedIn;
    const effectivePlaceholder = disableAccess ? "Please login to continue..." : placeholder;
    const sendDisabled = disabled || !question.trim() || disableAccess;

    const sendQuestion = () => {
        if (sendDisabled) return;
        onSend(question);
        if (clearOnSend) setQuestion("");
    };

    const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
        if (isComposing) return;
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendQuestion();
        }
    };

    return (
        <div className={styles.wrapper}>
            <div className={styles.inner}>
                <div className={styles.composer}>
                    <textarea
                        ref={textareaRef}
                        className={styles.textarea}
                        placeholder={effectivePlaceholder}
                        value={question}
                        onChange={e => setQuestion(e.target.value)}
                        onKeyDown={onKeyDown}
                        onCompositionStart={() => setIsComposing(true)}
                        onCompositionEnd={() => setIsComposing(false)}
                        disabled={disableAccess}
                        rows={1}
                    />

                    {showSpeechInput && (
                        <div className={styles.speechWrap}>
                            <SpeechInput updateQuestion={setQuestion} />
                        </div>
                    )}

                    {isStreaming || isLoading ? (
                        <button
                            type="button"
                            className={styles.stopButton}
                            onClick={onStop}
                            aria-label={t("tooltips.stopStreaming")}
                            title={t("tooltips.stopStreaming")}
                        >
                            <Stop24Filled />
                        </button>
                    ) : (
                        <button
                            type="button"
                            className={styles.sendButton}
                            onClick={sendQuestion}
                            disabled={sendDisabled}
                            aria-label={t("tooltips.submitQuestion")}
                            title={t("tooltips.submitQuestion")}
                        >
                            <Send24Filled />
                        </button>
                    )}
                </div>

                <p className={styles.hint}>
                    Press <kbd>Enter</kbd> to send · <kbd>Shift + Enter</kbd> for new line
                </p>
            </div>
        </div>
    );
};
