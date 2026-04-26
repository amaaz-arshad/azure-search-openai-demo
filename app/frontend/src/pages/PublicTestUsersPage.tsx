import { FormEvent, useEffect, useMemo, useState } from "react";
import { Helmet } from "react-helmet-async";
import { Link } from "react-router-dom";
import { Icon } from "@fluentui/react";

import {
    PublicTestAdminUser,
    deletePublicTestUserApi,
    listPublicTestUsersApi,
    resetPublicTestUserPasswordApi
} from "./publicTestUsersApi";
import { useInternalAdminAccess } from "./useInternalAdminAccess";
import styles from "./PublicTestUsersPage.module.css";

const FREE_BOT_PASSWORD_MIN_LENGTH = 8;

const formatTimestamp = (timestamp: string) => {
    const parsedDate = new Date(timestamp);
    if (Number.isNaN(parsedDate.getTime())) {
        return "Unknown";
    }
    return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(parsedDate);
};

const PublicTestUsersPage = () => {
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
    const [users, setUsers] = useState<PublicTestAdminUser[]>([]);
    const [isLoading, setIsLoading] = useState(false);
    const [statusMessage, setStatusMessage] = useState("");
    const [deletingEmail, setDeletingEmail] = useState<string | null>(null);
    const [passwordResetEmail, setPasswordResetEmail] = useState<string | null>(null);
    const [newPassword, setNewPassword] = useState("");
    const [confirmNewPassword, setConfirmNewPassword] = useState("");
    const [isNewPasswordVisible, setIsNewPasswordVisible] = useState(false);
    const [isConfirmPasswordVisible, setIsConfirmPasswordVisible] = useState(false);
    const [resettingEmail, setResettingEmail] = useState<string | null>(null);

    const filteredUsers = useMemo(() => {
        const normalizedQuery = query.trim().toLowerCase();
        if (!normalizedQuery) {
            return users;
        }

        return users.filter(
            user =>
                user.email.toLowerCase().includes(normalizedQuery) ||
                user.displayName.toLowerCase().includes(normalizedQuery) ||
                user.uploadedFiles.some(filename => filename.toLowerCase().includes(normalizedQuery))
        );
    }, [query, users]);

    const loadUsers = async () => {
        setIsLoading(true);
        setStatusMessage("");
        try {
            const response = await listPublicTestUsersApi();
            setUsers(response.users);
        } catch (error) {
            if (handleUnauthorizedError(error)) {
                setUsers([]);
                setPasswordResetEmail(null);
                setNewPassword("");
                setConfirmNewPassword("");
                setIsNewPasswordVisible(false);
                setIsConfirmPasswordVisible(false);
                setResettingEmail(null);
                setDeletingEmail(null);
                setQuery("");
                return;
            }
            setStatusMessage(error instanceof Error ? error.message : "Could not load Nerilio Bot users.");
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        if (!isAuthenticated) {
            return;
        }
        void loadUsers();
    }, [isAuthenticated]);

    const handleUnlock = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();

        if (await login(password)) {
            setPassword("");
            setIsPasswordVisible(false);
            return;
        }
    };

    const handleLockPage = () => {
        setPassword("");
        setQuery("");
        setUsers([]);
        setStatusMessage("");
        setIsPasswordVisible(false);
        setDeletingEmail(null);
        setPasswordResetEmail(null);
        setNewPassword("");
        setConfirmNewPassword("");
        setIsNewPasswordVisible(false);
        setIsConfirmPasswordVisible(false);
        setResettingEmail(null);
        void logout();
    };

    const handleDeleteUser = async (user: PublicTestAdminUser) => {
        const confirmed = window.confirm(
            `Delete the Nerilio Bot user ${user.email}? This will also remove ${user.uploadCount} uploaded file(s).`
        );
        if (!confirmed) {
            return;
        }

        setDeletingEmail(user.email);
        setStatusMessage("");
        try {
            const response = await deletePublicTestUserApi(user.email);
            setUsers(currentUsers => currentUsers.filter(currentUser => currentUser.email !== user.email));
            const deletedUploadCount = response.deletedUploadCount ?? 0;
            setStatusMessage(`Deleted ${user.email} and removed ${deletedUploadCount} uploaded file(s).`);
        } catch (error) {
            if (handleUnauthorizedError(error)) {
                setUsers([]);
                setDeletingEmail(null);
                return;
            }
            setStatusMessage(error instanceof Error ? error.message : "Could not delete Nerilio Bot user.");
        } finally {
            setDeletingEmail(null);
        }
    };

    const toggleResetForm = (email: string) => {
        setStatusMessage("");
        if (passwordResetEmail === email) {
            setPasswordResetEmail(null);
            setNewPassword("");
            setConfirmNewPassword("");
            setIsNewPasswordVisible(false);
            setIsConfirmPasswordVisible(false);
            return;
        }

        setPasswordResetEmail(email);
        setNewPassword("");
        setConfirmNewPassword("");
        setIsNewPasswordVisible(false);
        setIsConfirmPasswordVisible(false);
    };

    const handleResetPassword = async (event: FormEvent<HTMLFormElement>, user: PublicTestAdminUser) => {
        event.preventDefault();
        if (newPassword.length < FREE_BOT_PASSWORD_MIN_LENGTH) {
            setStatusMessage(`Passwords must be at least ${FREE_BOT_PASSWORD_MIN_LENGTH} characters.`);
            return;
        }
        setResettingEmail(user.email);
        setStatusMessage("");
        try {
            const response = await resetPublicTestUserPasswordApi(user.email, newPassword, confirmNewPassword);
            setUsers(currentUsers =>
                currentUsers.map(currentUser =>
                    currentUser.email === user.email
                        ? { ...currentUser, updatedAt: response.updatedAt ?? currentUser.updatedAt }
                        : currentUser
                )
            );
            setStatusMessage(`Password updated for ${user.email}.`);
            setPasswordResetEmail(null);
            setNewPassword("");
            setConfirmNewPassword("");
            setIsNewPasswordVisible(false);
            setIsConfirmPasswordVisible(false);
        } catch (error) {
            if (handleUnauthorizedError(error)) {
                setUsers([]);
                setPasswordResetEmail(null);
                setNewPassword("");
                setConfirmNewPassword("");
                setIsNewPasswordVisible(false);
                setIsConfirmPasswordVisible(false);
                return;
            }
            setStatusMessage(error instanceof Error ? error.message : "Could not reset the Nerilio Bot password.");
        } finally {
            setResettingEmail(null);
        }
    };

    return (
        <main className={styles.page}>
            <Helmet>
                <title>Nerilio Bot Users</title>
            </Helmet>

            <div className={styles.glowOne} aria-hidden="true" />
            <div className={styles.glowTwo} aria-hidden="true" />

            <section className={styles.shell}>
                <header className={styles.header}>
                    <div>
                        <span className={styles.badge}>Internal tool</span>
                        <h1 className={styles.title}>Nerilio Bot Users</h1>
                        <p className={styles.subtitle}>Review registered users, their uploads, and remove accounts when needed.</p>
                    </div>
                    <div className={styles.headerActions}>
                        <span className={styles.countPill}>{isAuthenticated ? `${users.length} registered users` : "Protected page"}</span>
                        {isAuthenticated ? (
                            <>
                                <Link className={styles.secondaryButton} to="/chatbots">
                                    Directory
                                </Link>
                                <Link className={styles.secondaryButton} to="/upload-files">
                                    Uploads
                                </Link>
                                <Link className={styles.secondaryButton} to="/manage-prompts">
                                    Prompts
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
                                <h2 className={styles.sectionTitle}>Unlock user admin</h2>
                            </div>

                            <form className={styles.form} onSubmit={handleUnlock} autoComplete="off">
                                <label className={styles.label} htmlFor="free-users-password">
                                    Password
                                </label>
                                <div className={styles.inputWrap}>
                                    <input
                                        id="free-users-password"
                                        className={styles.input}
                                        type={isPasswordVisible ? "text" : "password"}
                                        name="free-user-admin-password"
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
                                    {isCheckingAuthentication ? "Unlocking..." : "Unlock user admin"}
                                </button>

                                <p className={styles.errorMessage} role="alert" aria-live="polite">
                                    {authError}
                                </p>
                            </form>
                        </div>
                    ) : (
                        <>
                            <div className={styles.toolbar}>
                                <input
                                    className={styles.searchInput}
                                    type="search"
                                    value={query}
                                    onChange={event => setQuery(event.target.value)}
                                    placeholder="Search by name, email, or uploaded file"
                                    aria-label="Search Nerilio Bot users"
                                />
                                <button className={styles.primaryButton} type="button" onClick={() => void loadUsers()} disabled={isLoading}>
                                    {isLoading ? "Refreshing..." : "Refresh"}
                                </button>
                            </div>

                            <p className={styles.statusMessage} role="status" aria-live="polite">
                                {statusMessage}
                            </p>

                            {filteredUsers.length === 0 ? (
                                <div className={styles.emptyState}>
                                    <strong className={styles.emptyTitle}>
                                        {users.length === 0 ? "No registered users" : "No matching users"}
                                    </strong>
                                    <span className={styles.emptyText}>
                                        {users.length === 0
                                            ? "Once users verify their signup, they will appear here."
                                            : "Try a different search term."}
                                    </span>
                                </div>
                            ) : (
                                <div className={styles.list}>
                                    {filteredUsers.map(user => (
                                        <article key={user.email} className={styles.userCard}>
                                            <div className={styles.userHeader}>
                                                <div>
                                                    <h2 className={styles.userTitle}>{user.displayName}</h2>
                                                    <p className={styles.userEmail}>{user.email}</p>
                                                </div>
                                                <div className={styles.actionGroup}>
                                                    <button
                                                        className={styles.secondaryButton}
                                                        type="button"
                                                        onClick={() => toggleResetForm(user.email)}
                                                        disabled={deletingEmail === user.email || resettingEmail === user.email}
                                                    >
                                                        {passwordResetEmail === user.email ? "Cancel reset" : "Reset password"}
                                                    </button>
                                                    <button
                                                        className={styles.deleteButton}
                                                        type="button"
                                                        onClick={() => void handleDeleteUser(user)}
                                                        disabled={deletingEmail === user.email || resettingEmail === user.email}
                                                    >
                                                        {deletingEmail === user.email ? "Deleting..." : "Delete account"}
                                                    </button>
                                                </div>
                                            </div>

                                            <dl className={styles.metaGrid}>
                                                <div className={styles.metaItem}>
                                                    <dt>Created</dt>
                                                    <dd>{formatTimestamp(user.createdAt)}</dd>
                                                </div>
                                                <div className={styles.metaItem}>
                                                    <dt>Updated</dt>
                                                    <dd>{formatTimestamp(user.updatedAt)}</dd>
                                                </div>
                                                <div className={styles.metaItem}>
                                                    <dt>Uploads</dt>
                                                    <dd>{user.uploadCount}</dd>
                                                </div>
                                            </dl>

                                            <details className={styles.uploadDetails}>
                                                <summary className={styles.uploadSummary}>Uploaded files</summary>
                                                {user.uploadedFiles.length > 0 ? (
                                                    <ul className={styles.uploadList}>
                                                        {user.uploadedFiles.map(filename => (
                                                            <li key={filename} className={styles.uploadListItem}>
                                                                {filename}
                                                            </li>
                                                        ))}
                                                    </ul>
                                                ) : (
                                                    <p className={styles.emptyUploads}>No uploaded files.</p>
                                                )}
                                            </details>

                                            {passwordResetEmail === user.email ? (
                                                <form className={styles.resetForm} onSubmit={event => void handleResetPassword(event, user)}>
                                                    <label className={styles.label} htmlFor={`reset-password-${user.email}`}>
                                                        New password
                                                    </label>
                                                    <div className={styles.inputWrap}>
                                                        <input
                                                            id={`reset-password-${user.email}`}
                                                            className={styles.input}
                                                            type={isNewPasswordVisible ? "text" : "password"}
                                                            value={newPassword}
                                                            onChange={event => setNewPassword(event.target.value)}
                                                            placeholder="Enter new password"
                                                            minLength={FREE_BOT_PASSWORD_MIN_LENGTH}
                                                            autoComplete="off"
                                                            spellCheck={false}
                                                        />
                                                        <button
                                                            className={styles.visibilityToggle}
                                                            type="button"
                                                            aria-label={isNewPasswordVisible ? "Hide password" : "Show password"}
                                                            aria-pressed={isNewPasswordVisible}
                                                            onClick={() => setIsNewPasswordVisible(current => !current)}
                                                        >
                                                            <Icon iconName={isNewPasswordVisible ? "Hide3" : "RedEye"} />
                                                        </button>
                                                    </div>

                                                    <label className={styles.label} htmlFor={`reset-password-confirm-${user.email}`}>
                                                        Confirm password
                                                    </label>
                                                    <div className={styles.inputWrap}>
                                                        <input
                                                            id={`reset-password-confirm-${user.email}`}
                                                            className={styles.input}
                                                            type={isConfirmPasswordVisible ? "text" : "password"}
                                                            value={confirmNewPassword}
                                                            onChange={event => setConfirmNewPassword(event.target.value)}
                                                            placeholder="Confirm new password"
                                                            minLength={FREE_BOT_PASSWORD_MIN_LENGTH}
                                                            autoComplete="off"
                                                            spellCheck={false}
                                                        />
                                                        <button
                                                            className={styles.visibilityToggle}
                                                            type="button"
                                                            aria-label={isConfirmPasswordVisible ? "Hide password" : "Show password"}
                                                            aria-pressed={isConfirmPasswordVisible}
                                                            onClick={() => setIsConfirmPasswordVisible(current => !current)}
                                                        >
                                                            <Icon iconName={isConfirmPasswordVisible ? "Hide3" : "RedEye"} />
                                                        </button>
                                                    </div>

                                                    <button
                                                        className={styles.primaryButton}
                                                        type="submit"
                                                        disabled={resettingEmail === user.email}
                                                    >
                                                        {resettingEmail === user.email ? "Updating..." : "Save new password"}
                                                    </button>
                                                </form>
                                            ) : null}
                                        </article>
                                    ))}
                                </div>
                            )}
                        </>
                    )}
                </section>
            </section>
        </main>
    );
};

export default PublicTestUsersPage;

