import { useEffect, useMemo, useState } from "react";

import { formatChatbotLabel } from "./chatbotDisplay";
import { EmbedConfigEntry, getEmbedConfigApi, saveEmbedConfigApi } from "./embedAdminApi";
import styles from "./EmbedSnippetModal.module.css";

interface EmbedSnippetModalProps {
    chatbotName: string;
    onClose: () => void;
}

const linesToRules = (text: string): string[] =>
    text
        .split("\n")
        .map(line => line.trim())
        .filter(line => line.length > 0);

const EmbedSnippetModal = ({ chatbotName, onClose }: EmbedSnippetModalProps) => {
    const [copied, setCopied] = useState(false);
    const origin = typeof window !== "undefined" ? window.location.origin : "https://chat.nerilio.ai";

    const [publicId, setPublicId] = useState<string | null>(null);
    const [rulesText, setRulesText] = useState("");
    const [loadError, setLoadError] = useState<string | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [isSaving, setIsSaving] = useState(false);
    const [saveStatus, setSaveStatus] = useState<{ kind: "ok" | "error"; message: string } | null>(null);

    useEffect(() => {
        const controller = new AbortController();
        setIsLoading(true);
        setLoadError(null);
        getEmbedConfigApi(chatbotName, controller.signal)
            .then((config: EmbedConfigEntry) => {
                setPublicId(config.publicId);
                setRulesText(config.allowedRules.join("\n"));
            })
            .catch((error: unknown) => {
                if (controller.signal.aborted) {
                    return;
                }
                setLoadError(error instanceof Error ? error.message : "Could not load embed config.");
            })
            .finally(() => {
                if (!controller.signal.aborted) {
                    setIsLoading(false);
                }
            });
        return () => controller.abort();
    }, [chatbotName]);

    const snippet = useMemo(
        () =>
            publicId
                ? `<script async src="${origin}/widget.js" data-chatbot-id="${publicId}"></script>`
                : "",
        [origin, publicId]
    );

    const programmaticSnippet = useMemo(
        () =>
            publicId
                ? `<script async src="${origin}/widget.js"></script>\n` +
                  `<script>\n` +
                  `  window.chatbot = window.chatbot || { q: [], init(o){this.q.push(["init",o])},\n` +
                  `    open(){this.q.push(["open"])}, close(){this.q.push(["close"])} };\n` +
                  `  chatbot.init({ chatbotId: "${publicId}" });\n` +
                  `</script>`
                : "",
        [origin, publicId]
    );

    const previewSrc = publicId ? `${origin}/embed/${encodeURIComponent(publicId)}?embed=1` : "";

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
        if (!snippet) {
            return;
        }
        try {
            await navigator.clipboard.writeText(snippet);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1800);
        } catch {
            setCopied(false);
        }
    };

    const handleSaveWhitelist = async () => {
        setIsSaving(true);
        setSaveStatus(null);
        try {
            const config = await saveEmbedConfigApi(chatbotName, linesToRules(rulesText));
            setRulesText(config.allowedRules.join("\n"));
            setSaveStatus({
                kind: "ok",
                message: config.allowedRules.length === 0 ? "Whitelist cleared — widget allowed on any site." : "Whitelist saved."
            });
        } catch (error: unknown) {
            setSaveStatus({ kind: "error", message: error instanceof Error ? error.message : "Saving failed." });
        } finally {
            setIsSaving(false);
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
                    Paste this snippet before the closing <code>&lt;/body&gt;</code> tag on any whitelisted page. The chat bubble
                    renders itself — no other HTML, CSS, or code required, and updates roll out automatically. The{" "}
                    <code>data-chatbot-id</code> is an anonymous public identifier; it does not reveal the chatbot name.
                </p>

                {isLoading ? (
                    <p className={styles.statusMuted}>Loading embed details…</p>
                ) : loadError ? (
                    <p className={styles.statusError}>{loadError}</p>
                ) : (
                    <>
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

                        <section className={styles.section}>
                            <h3 className={styles.sectionTitle}>Allowed domains</h3>
                            <p className={styles.sectionHint}>
                                One rule per line. The widget only renders on matching pages; an empty list allows any site.
                                Wildcards: <code>*.snap.de</code> (subdomains), <code>help.example.com/*</code> (any path).
                                Examples: <code>publishone.snap.de</code>, <code>publishone.snap.de/preise.html</code>.
                            </p>
                            <textarea
                                className={styles.textarea}
                                value={rulesText}
                                onChange={event => {
                                    setRulesText(event.target.value);
                                    setSaveStatus(null);
                                }}
                                spellCheck={false}
                                rows={5}
                                placeholder={"*.snap.de\npublishone.snap.de/preise.html\nhelp.customer-website.com/*"}
                                aria-label="Allowed domains, one per line"
                            />
                            <div className={styles.saveRow}>
                                <button type="button" className={styles.saveButton} onClick={handleSaveWhitelist} disabled={isSaving}>
                                    {isSaving ? "Saving…" : "Save whitelist"}
                                </button>
                                {saveStatus ? (
                                    <span className={saveStatus.kind === "ok" ? styles.statusOk : styles.statusError} role="status">
                                        {saveStatus.message}
                                    </span>
                                ) : null}
                            </div>
                        </section>

                        <div className={styles.previewSection}>
                            <span className={styles.previewLabel}>Live preview</span>
                            <div className={styles.previewFrameWrap}>
                                <iframe className={styles.previewFrame} src={previewSrc} title={`Preview ${chatbotName}`} />
                            </div>
                        </div>
                    </>
                )}
            </div>
        </div>
    );
};

export default EmbedSnippetModal;
