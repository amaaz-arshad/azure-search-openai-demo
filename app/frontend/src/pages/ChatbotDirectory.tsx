import { FormEvent, useState } from "react";
import { Helmet } from "react-helmet-async";
import { Link } from "react-router-dom";
import { Icon } from "@fluentui/react";

import { chatbotDefinitions } from "../chatbots/registry";
import styles from "./ChatbotDirectory.module.css";

const DIRECTORY_PASSWORD = (import.meta.env.VITE_CHATBOT_DIRECTORY_PASSWORD as string | undefined) || "chatbot123";
const DIRECTORY_SESSION_KEY = "chatbotDirectoryAuthenticated";

const sortedChatbots = [...chatbotDefinitions].sort((a, b) => a.name.localeCompare(b.name));

const formatChatbotLabel = (name: string) => name.replace(/[-_]+/g, " ");

const getInitialAuthenticationState = () => {
    if (typeof window === "undefined") {
        return false;
    }

    return window.sessionStorage.getItem(DIRECTORY_SESSION_KEY) === "true";
};

const ChatbotDirectory = () => {
    const [isAuthenticated, setIsAuthenticated] = useState<boolean>(getInitialAuthenticationState);
    const [password, setPassword] = useState("");
    const [errorMessage, setErrorMessage] = useState("");
    const [isPasswordVisible, setIsPasswordVisible] = useState(false);
    const [query, setQuery] = useState("");

    const normalizedQuery = query.trim().toLowerCase();
    const filteredChatbots = sortedChatbots.filter(chatbot => chatbot.name.toLowerCase().includes(normalizedQuery));

    const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();

        if (password === DIRECTORY_PASSWORD) {
            window.sessionStorage.setItem(DIRECTORY_SESSION_KEY, "true");
            setIsAuthenticated(true);
            setPassword("");
            setErrorMessage("");
            setIsPasswordVisible(false);
            return;
        }

        setErrorMessage("Incorrect password. Please try again.");
    };

    const handleLockDirectory = () => {
        window.sessionStorage.removeItem(DIRECTORY_SESSION_KEY);
        setIsAuthenticated(false);
        setPassword("");
        setQuery("");
        setErrorMessage("");
        setIsPasswordVisible(false);
    };

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
                            {isAuthenticated && normalizedQuery
                                ? `${filteredChatbots.length} of ${sortedChatbots.length}`
                                : `${sortedChatbots.length} routes`}
                        </span>

                        {isAuthenticated ? (
                            <button className={styles.secondaryButton} type="button" onClick={handleLockDirectory}>
                                Lock directory
                            </button>
                        ) : null}
                    </div>
                </header>

                <section className={`${styles.panel} ${!isAuthenticated ? styles.panelLocked : ""}`}>
                    {!isAuthenticated ? (
                        <div className={styles.accessState}>
                            <div className={styles.accessHeader}>
                                <span className={styles.badge}>Protected</span>
                                <h2 className={styles.sectionTitle}>Unlock directory</h2>
                            </div>

                            <form className={styles.form} onSubmit={handleSubmit} autoComplete="off">
                                <label className={styles.label} htmlFor="directory-password">
                                    Password
                                </label>
                                <div className={styles.inputWrap}>
                                    <input
                                        id="directory-password"
                                        className={`${styles.input} ${!isPasswordVisible ? styles.maskedInput : ""}`}
                                        type="text"
                                        name="directory-access-code"
                                        value={password}
                                        onChange={event => {
                                            setPassword(event.target.value);
                                            setErrorMessage("");
                                        }}
                                        placeholder="Enter password"
                                        autoComplete="off"
                                        spellCheck={false}
                                        autoCapitalize="none"
                                        autoCorrect="off"
                                        data-lpignore="true"
                                        data-1p-ignore="true"
                                        data-form-type="other"
                                    />
                                    <button
                                        className={styles.visibilityToggle}
                                        type="button"
                                        aria-label={isPasswordVisible ? "Hide password" : "Show password"}
                                        aria-pressed={isPasswordVisible}
                                        onClick={() => setIsPasswordVisible(current => !current)}
                                    >
                                        <Icon iconName={isPasswordVisible ? "Hide3" : "RedEye"} />
                                    </button>
                                </div>

                                <button className={styles.primaryButton} type="submit">
                                    Unlock directory
                                </button>

                                <p className={styles.errorMessage} role="alert" aria-live="polite">
                                    {errorMessage}
                                </p>
                            </form>
                        </div>
                    ) : (
                        <>
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
                                                    <span className={styles.cardAction}>Open</span>
                                                </div>
                                                <strong className={styles.cardTitle}>{formatChatbotLabel(chatbot.name)}</strong>
                                                <span className={styles.cardRoute}>/{chatbot.name}</span>
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
                        </>
                    )}
                </section>
            </section>
        </main>
    );
};

export default ChatbotDirectory;
