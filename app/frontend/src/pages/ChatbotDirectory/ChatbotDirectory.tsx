import { useEffect, useMemo, useState } from "react";
import { Helmet } from "react-helmet-async";
import { Link } from "react-router-dom";

import { chatbotDefinitions, type ChatbotMode } from "../../chatbots/registry";
import { formatChatbotLabel } from "../shared/chatbotDisplay";
import EmbedSnippetModal from "./EmbedSnippetModal";
import { listDynamicChatbotsApi } from "./dynamicChatbotsApi";
import styles from "./ChatbotDirectory.module.css";

/**
 * A directory card, from either of the two chatbot worlds: the 18 built-in bots compiled into the
 * frontend registry, and the provisioned ("dynamic") bots that live in the backend registry and are
 * created through the provisioning API. They are merged for display only — nothing else about the
 * isolation between them changes.
 */
type DirectoryEntry = {
    name: string;
    label: string;
    llm: string;
    reasoningEffort?: string;
    mode: ChatbotMode;
    agenticRetrievalDefault: boolean;
    provisioned: boolean;
    active: boolean;
    canEmbed: boolean;
};

const builtInEntries: DirectoryEntry[] = chatbotDefinitions.map(chatbot => ({
    name: chatbot.name,
    label: formatChatbotLabel(chatbot.name),
    llm: chatbot.llm,
    reasoningEffort: chatbot.reasoningEffort,
    mode: chatbot.mode,
    agenticRetrievalDefault: chatbot.agenticRetrievalDefault,
    provisioned: false,
    active: true,
    canEmbed: true
}));

// Rendered inside the /admin shell (see pages/admin/AdminLayout). The shell owns the single auth
// gate and the tab bar, so this page only renders the directory content.
const ChatbotDirectory = () => {
    const [query, setQuery] = useState("");
    const [embedFor, setEmbedFor] = useState<string | null>(null);
    const [dynamicEntries, setDynamicEntries] = useState<DirectoryEntry[]>([]);
    const [dynamicError, setDynamicError] = useState<string | null>(null);

    useEffect(() => {
        const controller = new AbortController();
        listDynamicChatbotsApi(controller.signal)
            .then(chatbots => {
                setDynamicEntries(
                    chatbots.map(chatbot => ({
                        name: chatbot.botName,
                        label: chatbot.displayName || formatChatbotLabel(chatbot.botName),
                        llm: chatbot.llm,
                        reasoningEffort: chatbot.reasoningEffort ?? undefined,
                        mode: chatbot.mode,
                        // The generic frontend mirrors lemon: it auto-checks agentic retrieval whenever
                        // the deployment offers it (see chatbots/generic/pages/chat/Chat.tsx).
                        agenticRetrievalDefault: true,
                        provisioned: true,
                        active: chatbot.active,
                        // A stopped bot's route redirects home, so an embed of it would load a broken
                        // iframe — never hand out a snippet for one.
                        canEmbed: chatbot.active && Boolean(chatbot.publicId)
                    }))
                );
                setDynamicError(null);
            })
            .catch((error: unknown) => {
                if (controller.signal.aborted) {
                    return;
                }
                setDynamicError(error instanceof Error ? error.message : "Could not load provisioned chatbots.");
            });
        return () => controller.abort();
    }, []);

    const sortedChatbots = useMemo(
        () => [...builtInEntries, ...dynamicEntries].sort((a, b) => a.name.localeCompare(b.name)),
        [dynamicEntries]
    );

    const normalizedQuery = query.trim().toLowerCase();
    const filteredChatbots = sortedChatbots.filter(
        chatbot => chatbot.name.toLowerCase().includes(normalizedQuery) || chatbot.label.toLowerCase().includes(normalizedQuery)
    );

    return (
        <main className={styles.page}>
            <Helmet>
                <title>Chatbot Directory</title>
            </Helmet>

            <div className={styles.glowOne} aria-hidden="true" />
            <div className={styles.glowTwo} aria-hidden="true" />

            <section className={styles.shell}>
                <header className={styles.header}>
                    <div>
                        <span className={styles.badge}>Internal directory</span>
                        <h1 className={styles.title}>Chatbot Directory</h1>
                    </div>

                    <div className={styles.headerActions}>
                        <span className={styles.countPill}>
                            {normalizedQuery ? `${filteredChatbots.length} of ${sortedChatbots.length}` : `${sortedChatbots.length} routes`}
                        </span>
                    </div>
                </header>

                <section className={styles.panel}>
                    <div className={styles.controls}>
                        <input
                            className={styles.searchInput}
                            type="search"
                            value={query}
                            onChange={event => setQuery(event.target.value)}
                            placeholder="Search chatbots"
                            aria-label="Search chatbots"
                        />

                        {query ? (
                            <button className={styles.tertiaryButton} type="button" onClick={() => setQuery("")}>
                                Clear
                            </button>
                        ) : null}
                    </div>

                    {/* Built-in bots are compiled in and always render; say so explicitly when the
                        provisioned half of the list could not be fetched. */}
                    {dynamicError ? (
                        <p className={styles.listWarning} role="status">
                            Built-in chatbots only — provisioned chatbots could not be loaded. {dynamicError}
                        </p>
                    ) : null}

                    <div className={styles.directoryViewport}>
                        {filteredChatbots.length > 0 ? (
                            <div className={styles.directoryGrid}>
                                {filteredChatbots.map((chatbot, index) => (
                                    <Link key={chatbot.name} className={styles.chatbotCard} to={`/${chatbot.name}`}>
                                        <div className={styles.cardHeader}>
                                            <span className={styles.cardIndex}>{String(index + 1).padStart(2, "0")}</span>
                                            <div className={styles.cardHeaderActions}>
                                                {chatbot.canEmbed ? (
                                                    <button
                                                        type="button"
                                                        className={styles.embedButton}
                                                        onClick={event => {
                                                            event.preventDefault();
                                                            event.stopPropagation();
                                                            setEmbedFor(chatbot.name);
                                                        }}
                                                    >
                                                        Embed
                                                    </button>
                                                ) : null}
                                                <span className={styles.cardAction}>Open</span>
                                            </div>
                                        </div>
                                        <strong className={styles.cardTitle}>{chatbot.label}</strong>
                                        <span className={styles.cardRoute}>/{chatbot.name}</span>
                                        {chatbot.provisioned ? (
                                            <div className={styles.cardTags}>
                                                <span className={styles.cardTag}>Provisioned</span>
                                                {chatbot.active ? null : <span className={styles.cardTagStopped}>Stopped</span>}
                                            </div>
                                        ) : null}
                                        <ul className={styles.cardMeta}>
                                            <li className={styles.cardMetaItem}>
                                                <span className={styles.cardMetaLabel}>LLM</span>
                                                <span className={styles.cardMetaValue}>{chatbot.llm}</span>
                                            </li>
                                            {chatbot.reasoningEffort ? (
                                                <li className={styles.cardMetaItem}>
                                                    <span className={styles.cardMetaLabel}>Reasoning</span>
                                                    <span className={styles.cardMetaValue}>{chatbot.reasoningEffort}</span>
                                                </li>
                                            ) : null}
                                            <li className={styles.cardMetaItem}>
                                                <span className={styles.cardMetaLabel}>Mode</span>
                                                <span className={styles.cardMetaValue}>
                                                    {chatbot.mode === "tutor-qna" ? "Tutor + Q&A" : chatbot.mode === "assessment" ? "Assessment" : "Q&A"}
                                                </span>
                                            </li>
                                            <li className={styles.cardMetaItem}>
                                                <span className={styles.cardMetaLabel}>Agentic retrieval</span>
                                                <span
                                                    className={`${styles.cardMetaValue} ${
                                                        chatbot.agenticRetrievalDefault ? styles.cardMetaOn : styles.cardMetaOff
                                                    }`}
                                                >
                                                    {chatbot.agenticRetrievalDefault ? "On" : "Off"}
                                                </span>
                                            </li>
                                        </ul>
                                    </Link>
                                ))}
                            </div>
                        ) : (
                            <div className={styles.emptyState}>
                                <strong className={styles.emptyTitle}>No matching chatbots</strong>
                                <span className={styles.emptyText}>Try a different search term.</span>
                            </div>
                        )}
                    </div>
                </section>
            </section>

            {embedFor ? <EmbedSnippetModal chatbotName={embedFor} onClose={() => setEmbedFor(null)} /> : null}
        </main>
    );
};

export default ChatbotDirectory;
