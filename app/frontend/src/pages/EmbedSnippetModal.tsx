import { useEffect, useMemo, useState } from "react";

import { formatChatbotLabel } from "./chatbotDisplay";
import styles from "./EmbedSnippetModal.module.css";

interface EmbedSnippetModalProps {
    chatbotName: string;
    onClose: () => void;
}

const EmbedSnippetModal = ({ chatbotName, onClose }: EmbedSnippetModalProps) => {
    const [copied, setCopied] = useState(false);
    const origin = typeof window !== "undefined" ? window.location.origin : "https://chat.nerilio.ai";

    const snippet = useMemo(
        () => `<script async src="${origin}/widget.js" data-chatbot-id="${chatbotName}"></script>`,
        [origin, chatbotName]
    );

    const programmaticSnippet = useMemo(
        () =>
            `<script async src="${origin}/widget.js"></script>\n` +
            `<script>\n` +
            `  window.chatbot = window.chatbot || { q: [], init(o){this.q.push(["init",o])},\n` +
            `    open(){this.q.push(["open"])}, close(){this.q.push(["close"])} };\n` +
            `  chatbot.init({ chatbotId: "${chatbotName}" });\n` +
            `</script>`,
        [origin, chatbotName]
    );

    const previewSrc = `${origin}/${encodeURIComponent(chatbotName)}?embed=1`;

    useEffect(() => {
        const onKey = (event: KeyboardEvent) => {
            if (event.key === "Escape") {
                onClose();
            }
        };
        document.addEventListener("keydown", onKey);
        return () => document.removeEventListener("keydown", onKey);
    }, [onClose]);

    const handleCopy = async () => {
        try {
            await navigator.clipboard.writeText(snippet);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1800);
        } catch {
            setCopied(false);
        }
    };

    return (
        <div
            className={styles.overlay}
            role="dialog"
            aria-modal="true"
            aria-label={`Embed ${formatChatbotLabel(chatbotName)}`}
            onClick={onClose}
        >
            <div className={styles.dialog} onClick={event => event.stopPropagation()}>
                <header className={styles.header}>
                    <div>
                        <span className={styles.badge}>Embed code</span>
                        <h2 className={styles.title}>{formatChatbotLabel(chatbotName)}</h2>
                    </div>
                    <button type="button" className={styles.closeButton} aria-label="Close" onClick={onClose}>
                        ×
                    </button>
                </header>

                <p className={styles.lead}>
                    Paste this snippet before the closing <code>&lt;/body&gt;</code> tag on any page. The chat bubble renders itself — no
                    other HTML, CSS, or code required, and updates roll out automatically.
                </p>

                <div className={styles.codeBlock}>
                    <pre className={styles.code}>{snippet}</pre>
                    <button type="button" className={styles.copyButton} onClick={handleCopy}>
                        {copied ? "Copied!" : "Copy"}
                    </button>
                </div>

                <details className={styles.advanced}>
                    <summary className={styles.advancedSummary}>Programmatic alternative (SPAs / open on demand)</summary>
                    <pre className={styles.code}>{programmaticSnippet}</pre>
                    <p className={styles.advancedHint}>
                        Optional data attributes: <code>data-position</code> (left/right), <code>data-primary-color</code>,{" "}
                        <code>data-launcher-text</code>, <code>data-locale</code>, <code>data-auto-open</code>.
                    </p>
                </details>

                <div className={styles.previewSection}>
                    <span className={styles.previewLabel}>Live preview</span>
                    <div className={styles.previewFrameWrap}>
                        <iframe className={styles.previewFrame} src={previewSrc} title={`Preview ${chatbotName}`} />
                    </div>
                </div>
            </div>
        </div>
    );
};

export default EmbedSnippetModal;
