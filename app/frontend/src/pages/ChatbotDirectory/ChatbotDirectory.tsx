import { useEffect, useMemo, useState } from "react";
import { Helmet } from "react-helmet-async";
import { Link } from "react-router-dom";

import { chatbotDefinitions, type ChatbotMode } from "../../chatbots/registry";
import { formatChatbotLabel } from "../shared/chatbotDisplay";
import EmbedSnippetModal from "./EmbedSnippetModal";
import { listBuiltinChatbotsApi, type BuiltinChatbotEntry } from "./builtinChatbotsApi";
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
    // `/internal` runs on whichever source bot the user selects, so it has no single model to name.
    llmVaries?: boolean;
    mode: ChatbotMode;
    agenticRetrievalDefault: boolean;
    provisioned: boolean;
    active: boolean;
    canEmbed: boolean;
};

// Compiled fallback only. The registry's `llm`/`reasoningEffort` literals are hand-mirrored from the
// deployment, so they are replaced by the effective values from /internal-admin/builtin-chatbots as
// soon as it answers. `mode` and `agenticRetrievalDefault` always come from here — they describe this
// frontend's own prompt and toggle behavior, and no backend setting corresponds to them.
const compiledBuiltInEntries: DirectoryEntry[] = chatbotDefinitions.map(chatbot => ({
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
    const [builtinSettings, setBuiltinSettings] = useState<Map<string, BuiltinChatbotEntry> | null>(null);
    const [builtinSettingsError, setBuiltinSettingsError] = useState<string | null>(null);

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
                        // Provisioned bots retrieve with classic search: the generic frontend sets
                        // setUseAgenticRetrieval(false) (see chatbots/generic/pages/chat/Chat.tsx).
                        // This card mirrors that default, so it must be changed with it — there is no
                        // per-bot agentic field on the registry record to read it from.
                        agenticRetrievalDefault: false,
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

    // Effective built-in model/effort from the running backend, read off the same approach objects
    // /chat resolves. Failing is non-fatal: the compiled literals still render and the warning above
    // the grid says they may be stale, so the directory never silently presents a guess as fact.
    useEffect(() => {
        const controller = new AbortController();
        listBuiltinChatbotsApi(controller.signal)
            .then(chatbots => {
                setBuiltinSettings(new Map(chatbots.map(chatbot => [chatbot.name, chatbot])));
                setBuiltinSettingsError(null);
            })
            .catch((error: unknown) => {
                if (controller.signal.aborted) {
                    return;
                }
                setBuiltinSettingsError(error instanceof Error ? error.message : "Could not load built-in chatbot settings.");
            });
        return () => controller.abort();
    }, []);

    const builtInEntries = useMemo(() => {
        if (!builtinSettings) {
            return compiledBuiltInEntries;
        }
        return compiledBuiltInEntries.map(entry => {
            const effective = builtinSettings.get(entry.name);
            if (!effective) {
                return entry;
            }
            return {
                ...entry,
                llm: effective.llm || entry.llm,
                // null means the effective model has no reasoning effort (e.g. gpt-4.1), so the card
                // drops the row rather than showing a literal the backend would ignore.
                reasoningEffort: effective.reasoningEffort ?? undefined,
                llmVaries: effective.variesBySourceBot === true
            };
        });
    }, [builtinSettings]);

    const sortedChatbots = useMemo(
        () => [...builtInEntries, ...dynamicEntries].sort((a, b) => a.name.localeCompare(b.name)),
        [builtInEntries, dynamicEntries]
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

                    {/* Never let a compiled literal pass for the live setting without saying so. */}
                    {builtinSettingsError ? (
                        <p className={styles.listWarning} role="status">
                            Showing compiled defaults for built-in chatbots — their live settings could not be loaded, so LLM and
                            reasoning effort may be stale. {builtinSettingsError}
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
                                                <span className={styles.cardMetaValue}>
                                                    {chatbot.llmVaries ? "per source bot" : chatbot.llm}
                                                </span>
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
