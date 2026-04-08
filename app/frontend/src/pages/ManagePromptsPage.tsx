import { FormEvent, MouseEvent, useEffect, useMemo, useRef, useState } from "react";
import { Helmet } from "react-helmet-async";
import { Link } from "react-router-dom";
import { Icon } from "@fluentui/react";

import { PromptAdminEntry, listPromptAdminEntriesApi, resetPromptAdminEntryApi, savePromptAdminEntryApi } from "./promptAdminApi";
import { useInternalAdminAccess } from "./useInternalAdminAccess";
import styles from "./ManagePromptsPage.module.css";

type StatusState =
    | {
          tone: "success" | "warning" | "error";
          message: string;
      }
    | undefined;

const formatChatbotLabel = (name: string) => name.replace(/[-_]+/g, " ");

const formatTimestamp = (timestamp?: string | null) => {
    if (!timestamp) {
        return "Default prompt from source file";
    }

    const parsedDate = new Date(timestamp);
    if (Number.isNaN(parsedDate.getTime())) {
        return "Updated recently";
    }

    return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(parsedDate);
};

const sortPromptEntries = (entries: PromptAdminEntry[]) =>
    [...entries].sort((left, right) => left.chatbotName.localeCompare(right.chatbotName));

const ManagePromptsPage = () => {
    const {
        isAuthenticated,
        isCheckingAuthentication,
        authError,
        clearAuthError,
        handleUnauthorizedError,
        login,
        logout
    } = useInternalAdminAccess();
    const [password, setPassword] = useState("");
    const [isPasswordVisible, setIsPasswordVisible] = useState(false);
    const [query, setQuery] = useState("");
    const [prompts, setPrompts] = useState<PromptAdminEntry[]>([]);
    const [selectedChatbotName, setSelectedChatbotName] = useState("");
    const [draftPrompt, setDraftPrompt] = useState("");
    const [isLoading, setIsLoading] = useState(false);
    const [isSaving, setIsSaving] = useState(false);
    const [isResetting, setIsResetting] = useState(false);
    const [status, setStatus] = useState<StatusState>();
    const loadAbortRef = useRef<AbortController | null>(null);

    const filteredPrompts = useMemo(() => {
        const normalizedQuery = query.trim().toLowerCase();
        if (!normalizedQuery) {
            return prompts;
        }

        return prompts.filter(prompt => prompt.chatbotName.toLowerCase().includes(normalizedQuery));
    }, [prompts, query]);

    const selectedPrompt = prompts.find(prompt => prompt.chatbotName === selectedChatbotName) || null;
    const isDirty = selectedPrompt !== null && draftPrompt !== selectedPrompt.currentPrompt;

    const resetLocalState = () => {
        setPassword("");
        setIsPasswordVisible(false);
        setQuery("");
        setPrompts([]);
        setSelectedChatbotName("");
        setDraftPrompt("");
        setStatus(undefined);
        setIsSaving(false);
        setIsResetting(false);
        setIsLoading(false);
        loadAbortRef.current?.abort();
    };

    const handleAuthFailure = (error: unknown) => {
        if (!handleUnauthorizedError(error)) {
            return false;
        }

        resetLocalState();
        return true;
    };

    const loadPrompts = async () => {
        loadAbortRef.current?.abort();
        const controller = new AbortController();
        loadAbortRef.current = controller;
        setIsLoading(true);
        setStatus(undefined);

        try {
            const response = await listPromptAdminEntriesApi(controller.signal);
            const nextPrompts = sortPromptEntries(response.prompts);
            setPrompts(nextPrompts);

            const nextSelectedPrompt =
                nextPrompts.find(prompt => prompt.chatbotName === selectedChatbotName) || nextPrompts[0] || null;
            setSelectedChatbotName(nextSelectedPrompt?.chatbotName || "");
            setDraftPrompt(nextSelectedPrompt?.currentPrompt || "");
        } catch (error) {
            if (controller.signal.aborted || handleAuthFailure(error)) {
                return;
            }
            setStatus({
                tone: "error",
                message: error instanceof Error ? error.message : "Could not load prompts."
            });
        } finally {
            if (!controller.signal.aborted) {
                setIsLoading(false);
            }
        }
    };

    const setSelectedPromptEntry = (nextPrompt: PromptAdminEntry) => {
        setSelectedChatbotName(nextPrompt.chatbotName);
        setDraftPrompt(nextPrompt.currentPrompt);
    };

    const confirmDiscardChanges = () => {
        if (!isDirty) {
            return true;
        }

        return window.confirm("Discard unsaved prompt changes?");
    };

    const applyUpdatedPrompt = (nextPrompt: PromptAdminEntry) => {
        setPrompts(currentPrompts =>
            sortPromptEntries(
                currentPrompts.map(prompt => (prompt.chatbotName === nextPrompt.chatbotName ? nextPrompt : prompt))
            )
        );
        setSelectedPromptEntry(nextPrompt);
    };

    useEffect(() => {
        if (!isAuthenticated) {
            return;
        }

        void loadPrompts();

        return () => {
            loadAbortRef.current?.abort();
        };
    }, [isAuthenticated]);

    useEffect(() => {
        if (!isDirty) {
            return;
        }

        const handleBeforeUnload = (event: BeforeUnloadEvent) => {
            event.preventDefault();
            event.returnValue = "";
        };

        window.addEventListener("beforeunload", handleBeforeUnload);
        return () => window.removeEventListener("beforeunload", handleBeforeUnload);
    }, [isDirty]);

    const handleUnlock = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();

        const authenticated = await login(password);
        if (!authenticated) {
            return;
        }

        setPassword("");
        setIsPasswordVisible(false);
    };

    const handleLockPage = () => {
        if (!confirmDiscardChanges()) {
            return;
        }

        resetLocalState();
        void logout();
    };

    const handleGuardedNavigation = (event: MouseEvent<HTMLAnchorElement>) => {
        if (confirmDiscardChanges()) {
            return;
        }

        event.preventDefault();
    };

    const handleSelectChatbot = (nextChatbotName: string) => {
        if (nextChatbotName === selectedChatbotName) {
            return;
        }
        if (!confirmDiscardChanges()) {
            return;
        }

        const nextPrompt = prompts.find(prompt => prompt.chatbotName === nextChatbotName);
        if (!nextPrompt) {
            return;
        }

        setSelectedPromptEntry(nextPrompt);
        setStatus(undefined);
    };

    const handleSave = async () => {
        if (!selectedPrompt || !isDirty || isSaving) {
            return;
        }

        setIsSaving(true);
        setStatus(undefined);
        try {
            const response = await savePromptAdminEntryApi(selectedPrompt.chatbotName, draftPrompt);
            applyUpdatedPrompt(response.prompt);
            setStatus({
                tone: response.prompt.source === "override" ? "success" : "warning",
                message: response.message || "Prompt saved."
            });
        } catch (error) {
            if (handleAuthFailure(error)) {
                return;
            }
            setStatus({
                tone: "error",
                message: error instanceof Error ? error.message : "Could not save prompt."
            });
        } finally {
            setIsSaving(false);
        }
    };

    const handleReset = async () => {
        if (!selectedPrompt || selectedPrompt.source === "default" || isResetting) {
            return;
        }
        if (!window.confirm(`Reset ${formatChatbotLabel(selectedPrompt.chatbotName)} to its default prompt?`)) {
            return;
        }

        setIsResetting(true);
        setStatus(undefined);
        try {
            const response = await resetPromptAdminEntryApi(selectedPrompt.chatbotName);
            applyUpdatedPrompt(response.prompt);
            setStatus({
                tone: "warning",
                message: response.message || "Prompt reset to default."
            });
        } catch (error) {
            if (handleAuthFailure(error)) {
                return;
            }
            setStatus({
                tone: "error",
                message: error instanceof Error ? error.message : "Could not reset prompt."
            });
        } finally {
            setIsResetting(false);
        }
    };

    return (
        <main className={styles.page}>
            <Helmet>
                <title>Manage Prompts</title>
            </Helmet>

            <div className={styles.glowOne} aria-hidden="true" />
            <div className={styles.glowTwo} aria-hidden="true" />

            <section className={styles.shell}>
                <header className={styles.header}>
                    <div>
                        <span className={styles.badge}>Internal tool</span>
                        <h1 className={styles.title}>Manage Prompts</h1>
                        <p className={styles.subtitle}>Review every chatbot prompt, save runtime overrides, or reset a bot back to its source file.</p>
                    </div>

                    <div className={styles.headerActions}>
                        <span className={styles.countPill}>
                            {isAuthenticated ? `${prompts.length} chatbot prompts` : "Protected page"}
                        </span>
                        {isAuthenticated ? (
                            <>
                                <Link className={styles.secondaryButton} to="/chatbots" onClick={handleGuardedNavigation}>
                                    Directory
                                </Link>
                                <Link className={styles.secondaryButton} to="/upload-files" onClick={handleGuardedNavigation}>
                                    Uploads
                                </Link>
                                <Link
                                    className={styles.secondaryButton}
                                    to="/public-test-users"
                                    onClick={handleGuardedNavigation}
                                >
                                    Public-test users
                                </Link>
                                <button className={styles.secondaryButton} type="button" onClick={handleLockPage}>
                                    Lock page
                                </button>
                            </>
                        ) : null}
                    </div>
                </header>

                <section className={`${styles.panel} ${!isAuthenticated ? styles.panelLocked : ""}`}>
                    {!isAuthenticated ? (
                        <div className={styles.accessState}>
                            <div className={styles.accessHeader}>
                                <span className={styles.badge}>Protected</span>
                                <h2 className={styles.sectionTitle}>Unlock prompt admin</h2>
                                <p className={styles.accessDescription}>
                                    Sign in with the shared internal admin password to load and update saved chatbot prompts.
                                </p>
                            </div>

                            <form className={styles.form} onSubmit={handleUnlock} autoComplete="off">
                                <label className={styles.label} htmlFor="manage-prompts-password">
                                    Password
                                </label>
                                <div className={styles.inputWrap}>
                                    <input
                                        id="manage-prompts-password"
                                        className={`${styles.input} ${!isPasswordVisible ? styles.maskedInput : ""}`}
                                        type="text"
                                        name="manage-prompts-password"
                                        value={password}
                                        onChange={event => {
                                            setPassword(event.target.value);
                                            clearAuthError();
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

                                <button className={styles.primaryButton} type="submit" disabled={isCheckingAuthentication}>
                                    {isCheckingAuthentication ? "Unlocking..." : "Unlock prompt admin"}
                                </button>

                                <p className={styles.errorMessage} role="alert" aria-live="polite">
                                    {authError}
                                </p>
                            </form>
                        </div>
                    ) : (
                        <>
                            {status ? (
                                <div
                                    className={`${styles.statusMessage} ${
                                        status.tone === "success"
                                            ? styles.statusSuccess
                                            : status.tone === "warning"
                                              ? styles.statusWarning
                                              : styles.statusError
                                    }`}
                                    role="status"
                                >
                                    {status.message}
                                </div>
                            ) : null}

                            <div className={styles.layoutGrid}>
                                <aside className={styles.sidebar}>
                                    <div className={styles.sidebarHeader}>
                                        <div>
                                            <span className={styles.sectionLabel}>Chatbots</span>
                                            <h2 className={styles.sectionTitle}>Prompt list</h2>
                                        </div>
                                        <span className={styles.sidebarCount}>
                                            {filteredPrompts.length} of {prompts.length}
                                        </span>
                                    </div>

                                    <input
                                        className={styles.searchInput}
                                        type="search"
                                        value={query}
                                        onChange={event => setQuery(event.target.value)}
                                        placeholder="Search chatbots"
                                        aria-label="Search chatbot prompts"
                                    />

                                    <div className={styles.chatbotList}>
                                        {filteredPrompts.length > 0 ? (
                                            filteredPrompts.map(prompt => (
                                                <button
                                                    key={prompt.chatbotName}
                                                    className={`${styles.chatbotButton} ${
                                                        prompt.chatbotName === selectedChatbotName ? styles.chatbotButtonActive : ""
                                                    }`}
                                                    type="button"
                                                    onClick={() => handleSelectChatbot(prompt.chatbotName)}
                                                >
                                                    <div className={styles.chatbotRow}>
                                                        <strong className={styles.chatbotTitle}>
                                                            {formatChatbotLabel(prompt.chatbotName)}
                                                        </strong>
                                                        <span
                                                            className={`${styles.sourcePill} ${
                                                                prompt.source === "override"
                                                                    ? styles.sourceOverride
                                                                    : styles.sourceDefault
                                                            }`}
                                                        >
                                                            {prompt.source === "override" ? "Override" : "Default"}
                                                        </span>
                                                    </div>
                                                    <span className={styles.chatbotMeta}>/{prompt.chatbotName}</span>
                                                </button>
                                            ))
                                        ) : (
                                            <div className={styles.emptyState}>
                                                <strong className={styles.emptyTitle}>No matching chatbots</strong>
                                                <span className={styles.emptyText}>Try a different search term.</span>
                                            </div>
                                        )}
                                    </div>
                                </aside>

                                <section className={styles.editor}>
                                    {selectedPrompt ? (
                                        <>
                                            <div className={styles.editorHeader}>
                                                <div>
                                                    <div className={styles.editorTitleRow}>
                                                        <h2 className={styles.editorTitle}>
                                                            {formatChatbotLabel(selectedPrompt.chatbotName)}
                                                        </h2>
                                                        <span
                                                            className={`${styles.sourcePill} ${
                                                                selectedPrompt.source === "override"
                                                                    ? styles.sourceOverride
                                                                    : styles.sourceDefault
                                                            }`}
                                                        >
                                                            {selectedPrompt.source === "override" ? "Override" : "Default"}
                                                        </span>
                                                        {isDirty ? <span className={styles.dirtyPill}>Unsaved changes</span> : null}
                                                    </div>
                                                    <p className={styles.timestamp}>{formatTimestamp(selectedPrompt.updatedAt)}</p>
                                                </div>

                                                <div className={styles.editorActions}>
                                                    <button
                                                        className={styles.secondaryButton}
                                                        type="button"
                                                        onClick={handleReset}
                                                        disabled={selectedPrompt.source === "default" || isResetting || isSaving}
                                                    >
                                                        {isResetting ? "Resetting..." : "Reset to default"}
                                                    </button>
                                                    <button
                                                        className={styles.primaryButton}
                                                        type="button"
                                                        onClick={handleSave}
                                                        disabled={!isDirty || isSaving || isResetting}
                                                    >
                                                        {isSaving ? "Saving..." : "Save prompt"}
                                                    </button>
                                                </div>
                                            </div>

                                            <label className={styles.label} htmlFor="prompt-editor">
                                                Raw prompt
                                            </label>
                                            <textarea
                                                id="prompt-editor"
                                                className={styles.textarea}
                                                value={draftPrompt}
                                                onChange={event => {
                                                    setDraftPrompt(event.target.value);
                                                    setStatus(undefined);
                                                }}
                                                spellCheck={false}
                                            />

                                            <div className={styles.helperRow}>
                                                <span className={styles.helperText}>
                                                    Saved overrides are stored in private blob storage and applied on the next chat request.
                                                </span>
                                                <span className={styles.promptStats}>{draftPrompt.length} characters</span>
                                            </div>
                                        </>
                                    ) : (
                                        <div className={styles.emptyEditor}>
                                            <strong className={styles.emptyTitle}>
                                                {isLoading ? "Loading prompts..." : "No prompt selected"}
                                            </strong>
                                            <span className={styles.emptyText}>
                                                {isLoading
                                                    ? "Prompt data is loading from the backend."
                                                    : "Choose a chatbot from the list to edit its prompt."}
                                            </span>
                                        </div>
                                    )}
                                </section>
                            </div>
                        </>
                    )}
                </section>
            </section>
        </main>
    );
};

export default ManagePromptsPage;
