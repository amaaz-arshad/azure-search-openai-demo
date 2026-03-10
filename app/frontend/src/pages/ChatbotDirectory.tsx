import { FormEvent, useState } from "react";
import { Helmet } from "react-helmet-async";
import { Link } from "react-router-dom";

import { chatbotDefinitions } from "../chatbots/registry";
import styles from "./ChatbotDirectory.module.css";

const DIRECTORY_PASSWORD = (import.meta.env.VITE_CHATBOT_DIRECTORY_PASSWORD as string | undefined) || "chatbot123";
const DIRECTORY_SESSION_KEY = "chatbotDirectoryAuthenticated";

const sortedChatbots = [...chatbotDefinitions].sort((a, b) => a.name.localeCompare(b.name));

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

    const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();

        if (password === DIRECTORY_PASSWORD) {
            window.sessionStorage.setItem(DIRECTORY_SESSION_KEY, "true");
            setIsAuthenticated(true);
            setPassword("");
            setErrorMessage("");
            return;
        }

        setErrorMessage("Incorrect password. Please try again.");
    };

    const handleLockDirectory = () => {
        window.sessionStorage.removeItem(DIRECTORY_SESSION_KEY);
        setIsAuthenticated(false);
        setPassword("");
        setErrorMessage("");
    };

    return (
        <main className={styles.page}>
            <Helmet>
                <title>Chatbot Directory</title>
            </Helmet>

            <div className={styles.glowOne} aria-hidden="true" />
            <div className={styles.glowTwo} aria-hidden="true" />

            <section className={styles.shell}>
                <div className={styles.hero}>
                    <span className={styles.eyebrow}>Internal directory</span>
                    <h1 className={styles.title}>Choose the right chatbot workspace.</h1>
                    <p className={styles.subtitle}>
                        This directory collects every registered chatbot route in one place so internal users can move between
                        experiences quickly.
                    </p>

                    <div className={styles.metrics}>
                        <div className={styles.metricCard}>
                            <span className={styles.metricLabel}>Available</span>
                            <strong className={styles.metricValue}>{sortedChatbots.length}</strong>
                        </div>
                        <div className={styles.metricCard}>
                            <span className={styles.metricLabel}>Access</span>
                            <strong className={styles.metricValue}>{isAuthenticated ? "Unlocked" : "Protected"}</strong>
                        </div>
                    </div>
                </div>

                {!isAuthenticated ? (
                    <section className={styles.accessPanel}>
                        <div className={styles.panelHeader}>
                            <span className={styles.panelTag}>Step 1</span>
                            <h2 className={styles.panelTitle}>Enter directory password</h2>
                            <p className={styles.panelText}>Authentication is scoped to this browser tab and resets when you lock it again.</p>
                        </div>

                        <form className={styles.form} onSubmit={handleSubmit} autoComplete="off">
                            <label className={styles.label} htmlFor="directory-password">
                                Access code
                            </label>
                            <input
                                id="directory-password"
                                className={styles.input}
                                type="password"
                                name="directory-access-code"
                                value={password}
                                onChange={event => setPassword(event.target.value)}
                                placeholder="Enter access code"
                                autoComplete="new-password"
                                data-lpignore="true"
                                data-1p-ignore="true"
                                data-form-type="other"
                            />

                            <button className={styles.primaryButton} type="submit">
                                Unlock directory
                            </button>

                            <p className={styles.errorMessage} role="alert" aria-live="polite">
                                {errorMessage}
                            </p>
                        </form>
                    </section>
                ) : (
                    <section className={styles.directoryPanel}>
                        <div className={styles.panelHeader}>
                            <span className={styles.panelTag}>Step 2</span>
                            <div className={styles.directoryHeaderRow}>
                                <div>
                                    <h2 className={styles.panelTitle}>Available chatbots</h2>
                                    <p className={styles.panelText}>Open any chatbot below. Each card links directly to its route.</p>
                                </div>
                                <button className={styles.secondaryButton} type="button" onClick={handleLockDirectory}>
                                    Lock directory
                                </button>
                            </div>
                        </div>

                        <div className={styles.directoryGrid}>
                            {sortedChatbots.map((chatbot, index) => (
                                <Link key={chatbot.name} className={styles.chatbotCard} to={`/${chatbot.name}`}>
                                    <span className={styles.cardIndex}>{String(index + 1).padStart(2, "0")}</span>
                                    <strong className={styles.cardTitle}>{chatbot.name}</strong>
                                    <span className={styles.cardAction}>Open workspace</span>
                                </Link>
                            ))}
                        </div>
                    </section>
                )}
            </section>
        </main>
    );
};

export default ChatbotDirectory;
