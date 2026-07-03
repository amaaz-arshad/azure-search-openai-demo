import { useState } from "react";
import { Helmet } from "react-helmet-async";
import { Link } from "react-router-dom";

import { chatbotDefinitions } from "../../chatbots/registry";
import { formatChatbotLabel } from "../shared/chatbotDisplay";
import EmbedSnippetModal from "./EmbedSnippetModal";
import styles from "./ChatbotDirectory.module.css";

const sortedChatbots = [...chatbotDefinitions].sort((a, b) => a.name.localeCompare(b.name));

// Rendered inside the /admin shell (see pages/admin/AdminLayout). The shell owns the single auth
// gate and the tab bar, so this page only renders the directory content.
const ChatbotDirectory = () => {
    const [query, setQuery] = useState("");
    const [embedFor, setEmbedFor] = useState<string | null>(null);

    const normalizedQuery = query.trim().toLowerCase();
    const filteredChatbots = sortedChatbots.filter(
        chatbot =>
            chatbot.name.toLowerCase().includes(normalizedQuery) ||
            formatChatbotLabel(chatbot.name).toLowerCase().includes(normalizedQuery)
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

                    <div className={styles.directoryViewport}>
                        {filteredChatbots.length > 0 ? (
                            <div className={styles.directoryGrid}>
                                {filteredChatbots.map((chatbot, index) => (
                                    <Link key={chatbot.name} className={styles.chatbotCard} to={`/${chatbot.name}`}>
                                        <div className={styles.cardHeader}>
                                            <span className={styles.cardIndex}>{String(index + 1).padStart(2, "0")}</span>
                                            <div className={styles.cardHeaderActions}>
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
                                                <span className={styles.cardAction}>Open</span>
                                            </div>
                                        </div>
                                        <strong className={styles.cardTitle}>{formatChatbotLabel(chatbot.name)}</strong>
                                        <span className={styles.cardRoute}>/{chatbot.name}</span>
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
