import { FormEvent, useEffect, useMemo, useState } from "react";
import { Helmet } from "react-helmet-async";
import { Icon } from "@fluentui/react";

import { FreeAdminUser, deleteFreeUserApi, listFreeUsersApi, reactivateFreeUserApi, resetFreeUserPasswordApi } from "./freeUsersApi";
import { useAdminShell } from "../admin/AdminShellContext";
import styles from "./FreeUsersPage.module.css";

const FREE_BOT_PASSWORD_MIN_LENGTH = 8;
const FREE_ACCOUNT_LIFETIME_DAYS = 30;
// Highlight an account that is about to lose access, matching the Free Bot's own expiry banner.
const FREE_EXPIRY_WARNING_DAYS = 7;

type UserTab = "active" | "archive";

const formatTimestamp = (timestamp: string) => {
    const parsedDate = new Date(timestamp);
    if (Number.isNaN(parsedDate.getTime())) {
        return "Unknown";
    }
    return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(parsedDate);
};

const formatDaysRemaining = (daysRemaining: number) => (daysRemaining === 1 ? "1 day left" : `${daysRemaining} days left`);

const formatDaysExpired = (daysExpired: number) => {
    if (daysExpired <= 0) {
        return "Expired today";
    }
    return daysExpired === 1 ? "Expired 1 day ago" : `Expired ${daysExpired} days ago`;
};

// Rendered inside the /admin shell (see pages/admin/AdminLayout). The shell owns the auth gate;
// this page only renders content and falls back to the shell's login on a session-expiry 401.
const FreeUsersPage = () => {
    const { handleUnauthorizedError } = useAdminShell();
    const [activeTab, setActiveTab] = useState<UserTab>("active");
    const [query, setQuery] = useState("");
    const [users, setUsers] = useState<FreeAdminUser[]>([]);
    const [isLoading, setIsLoading] = useState(false);
    const [statusMessage, setStatusMessage] = useState("");
    const [deletingEmail, setDeletingEmail] = useState<string | null>(null);
    const [reactivatingEmail, setReactivatingEmail] = useState<string | null>(null);
    const [passwordResetEmail, setPasswordResetEmail] = useState<string | null>(null);
    const [newPassword, setNewPassword] = useState("");
    const [confirmNewPassword, setConfirmNewPassword] = useState("");
    const [isNewPasswordVisible, setIsNewPasswordVisible] = useState(false);
    const [isConfirmPasswordVisible, setIsConfirmPasswordVisible] = useState(false);
    const [resettingEmail, setResettingEmail] = useState<string | null>(null);

    const activeUsers = useMemo(() => users.filter(user => !user.isExpired), [users]);
    const archivedUsers = useMemo(() => users.filter(user => user.isExpired), [users]);

    const visibleUsers = activeTab === "active" ? activeUsers : archivedUsers;

    const filteredUsers = useMemo(() => {
        const normalizedQuery = query.trim().toLowerCase();
        if (!normalizedQuery) {
            return visibleUsers;
        }

        return visibleUsers.filter(
            user =>
                user.email.toLowerCase().includes(normalizedQuery) ||
                user.displayName.toLowerCase().includes(normalizedQuery) ||
                user.uploadedFiles.some(filename => filename.toLowerCase().includes(normalizedQuery))
        );
    }, [query, visibleUsers]);

    const closeResetForm = () => {
        setPasswordResetEmail(null);
        setNewPassword("");
        setConfirmNewPassword("");
        setIsNewPasswordVisible(false);
        setIsConfirmPasswordVisible(false);
    };

    const loadUsers = async () => {
        setIsLoading(true);
        setStatusMessage("");
        try {
            const response = await listFreeUsersApi();
            setUsers(response.users);
        } catch (error) {
            if (handleUnauthorizedError(error)) {
                setUsers([]);
                closeResetForm();
                setResettingEmail(null);
                setDeletingEmail(null);
                setReactivatingEmail(null);
                setQuery("");
                return;
            }
            setStatusMessage(error instanceof Error ? error.message : "Could not load nerilio users.");
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        void loadUsers();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const handleSwitchTab = (tab: UserTab) => {
        if (tab === activeTab) {
            return;
        }
        setActiveTab(tab);
        setStatusMessage("");
        closeResetForm();
    };

    const handleDeleteUser = async (user: FreeAdminUser) => {
        const confirmed = window.confirm(`Delete the nerilio user ${user.email}? This will also remove ${user.uploadCount} uploaded file(s).`);
        if (!confirmed) {
            return;
        }

        setDeletingEmail(user.email);
        setStatusMessage("");
        try {
            const response = await deleteFreeUserApi(user.email);
            setUsers(currentUsers => currentUsers.filter(currentUser => currentUser.email !== user.email));
            const deletedUploadCount = response.deletedUploadCount ?? 0;
            setStatusMessage(`Deleted ${user.email} and removed ${deletedUploadCount} uploaded file(s).`);
        } catch (error) {
            if (handleUnauthorizedError(error)) {
                setUsers([]);
                setDeletingEmail(null);
                return;
            }
            setStatusMessage(error instanceof Error ? error.message : "Could not delete nerilio user.");
        } finally {
            setDeletingEmail(null);
        }
    };

    // Reactivation is the only way back from the archive: the expired account keeps its blob so its
    // email cannot be re-registered, so without this an expired user would be locked out for good.
    const handleReactivateUser = async (user: FreeAdminUser) => {
        const confirmed = window.confirm(
            `Give ${user.email} another ${FREE_ACCOUNT_LIFETIME_DAYS} days of nerilio access? The account moves back to the active list with its uploads intact.`
        );
        if (!confirmed) {
            return;
        }

        setReactivatingEmail(user.email);
        setStatusMessage("");
        try {
            const response = await reactivateFreeUserApi(user.email);
            setUsers(currentUsers =>
                currentUsers.map(currentUser =>
                    currentUser.email === user.email
                        ? {
                              ...currentUser,
                              updatedAt: response.updatedAt ?? currentUser.updatedAt,
                              expiresAt: response.expiresAt ?? currentUser.expiresAt,
                              isExpired: response.isExpired ?? false,
                              daysRemaining: response.daysRemaining ?? FREE_ACCOUNT_LIFETIME_DAYS,
                              daysExpired: response.daysExpired ?? 0
                          }
                        : currentUser
                )
            );
            setStatusMessage(`Reactivated ${user.email} for ${response.daysRemaining ?? FREE_ACCOUNT_LIFETIME_DAYS} more day(s).`);
        } catch (error) {
            if (handleUnauthorizedError(error)) {
                setUsers([]);
                setReactivatingEmail(null);
                return;
            }
            setStatusMessage(error instanceof Error ? error.message : "Could not reactivate nerilio user.");
        } finally {
            setReactivatingEmail(null);
        }
    };

    const toggleResetForm = (email: string) => {
        setStatusMessage("");
        if (passwordResetEmail === email) {
            closeResetForm();
            return;
        }

        setPasswordResetEmail(email);
        setNewPassword("");
        setConfirmNewPassword("");
        setIsNewPasswordVisible(false);
        setIsConfirmPasswordVisible(false);
    };

    const handleResetPassword = async (event: FormEvent<HTMLFormElement>, user: FreeAdminUser) => {
        event.preventDefault();
        if (newPassword.length < FREE_BOT_PASSWORD_MIN_LENGTH) {
            setStatusMessage(`Passwords must be at least ${FREE_BOT_PASSWORD_MIN_LENGTH} characters.`);
            return;
        }
        setResettingEmail(user.email);
        setStatusMessage("");
        try {
            const response = await resetFreeUserPasswordApi(user.email, newPassword, confirmNewPassword);
            setUsers(currentUsers =>
                currentUsers.map(currentUser =>
                    currentUser.email === user.email ? { ...currentUser, updatedAt: response.updatedAt ?? currentUser.updatedAt } : currentUser
                )
            );
            setStatusMessage(`Password updated for ${user.email}.`);
            closeResetForm();
        } catch (error) {
            if (handleUnauthorizedError(error)) {
                setUsers([]);
                closeResetForm();
                return;
            }
            setStatusMessage(error instanceof Error ? error.message : "Could not reset the nerilio password.");
        } finally {
            setResettingEmail(null);
        }
    };

    const renderExpiryPill = (user: FreeAdminUser) => {
        if (user.isExpired) {
            return <span className={`${styles.expiryPill} ${styles.expiryPillExpired}`}>{formatDaysExpired(user.daysExpired)}</span>;
        }
        const isWarning = user.daysRemaining <= FREE_EXPIRY_WARNING_DAYS;
        return <span className={`${styles.expiryPill} ${isWarning ? styles.expiryPillWarning : ""}`}>{formatDaysRemaining(user.daysRemaining)}</span>;
    };

    const emptyStateTitle = () => {
        if (visibleUsers.length > 0) {
            return "No matching users";
        }
        return activeTab === "active" ? "No active users" : "No archived users";
    };

    const emptyStateText = () => {
        if (visibleUsers.length > 0) {
            return "Try a different search term.";
        }
        return activeTab === "active"
            ? "Once users verify their signup, they will appear here."
            : `Accounts land here automatically ${FREE_ACCOUNT_LIFETIME_DAYS} days after they were registered.`;
    };

    return (
        <main className={styles.page}>
            <Helmet>
                <title>nerilio users</title>
            </Helmet>

            <div className={styles.glowOne} aria-hidden="true" />
            <div className={styles.glowTwo} aria-hidden="true" />

            <section className={styles.shell}>
                <header className={styles.header}>
                    <div>
                        <span className={styles.badge}>Internal tool</span>
                        <h1 className={styles.title}>nerilio users</h1>
                        <p className={styles.subtitle}>
                            Review registered users and their uploads. Access lasts {FREE_ACCOUNT_LIFETIME_DAYS} days from registration — expired accounts move
                            to the archive, where you can grant another {FREE_ACCOUNT_LIFETIME_DAYS} days or delete them.
                        </p>
                    </div>
                    <div className={styles.headerActions}>
                        <span className={styles.countPill}>{`${activeUsers.length} active`}</span>
                        <span className={styles.countPill}>{`${archivedUsers.length} archived`}</span>
                    </div>
                </header>

                <section className={styles.panel}>
                    <div className={styles.tabBar} role="tablist" aria-label="nerilio user groups">
                        <button
                            className={`${styles.tab} ${activeTab === "active" ? styles.tabActive : ""}`}
                            type="button"
                            role="tab"
                            aria-selected={activeTab === "active"}
                            onClick={() => handleSwitchTab("active")}
                        >
                            Active<span className={styles.tabCount}>{activeUsers.length}</span>
                        </button>
                        <button
                            className={`${styles.tab} ${activeTab === "archive" ? styles.tabActive : ""}`}
                            type="button"
                            role="tab"
                            aria-selected={activeTab === "archive"}
                            onClick={() => handleSwitchTab("archive")}
                        >
                            Archive<span className={styles.tabCount}>{archivedUsers.length}</span>
                        </button>
                    </div>

                    <div className={styles.toolbar}>
                        <input
                            className={styles.searchInput}
                            type="search"
                            value={query}
                            onChange={event => setQuery(event.target.value)}
                            placeholder="Search by name, email, or uploaded file"
                            aria-label="Search nerilio users"
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
                            <strong className={styles.emptyTitle}>{emptyStateTitle()}</strong>
                            <span className={styles.emptyText}>{emptyStateText()}</span>
                        </div>
                    ) : (
                        <div className={styles.list}>
                            {filteredUsers.map(user => (
                                <article key={user.email} className={`${styles.userCard} ${user.isExpired ? styles.userCardExpired : ""}`}>
                                    <div className={styles.userHeader}>
                                        <div>
                                            <h2 className={styles.userTitle}>{user.displayName}</h2>
                                            <p className={styles.userEmail}>{user.email}</p>
                                            {renderExpiryPill(user)}
                                        </div>
                                        <div className={styles.actionGroup}>
                                            {user.isExpired ? (
                                                <button
                                                    className={styles.primaryButton}
                                                    type="button"
                                                    onClick={() => void handleReactivateUser(user)}
                                                    disabled={deletingEmail === user.email || reactivatingEmail === user.email}
                                                >
                                                    {reactivatingEmail === user.email ? "Reactivating..." : `Reactivate +${FREE_ACCOUNT_LIFETIME_DAYS} days`}
                                                </button>
                                            ) : (
                                                <button
                                                    className={styles.secondaryButton}
                                                    type="button"
                                                    onClick={() => toggleResetForm(user.email)}
                                                    disabled={deletingEmail === user.email || resettingEmail === user.email}
                                                >
                                                    {passwordResetEmail === user.email ? "Cancel reset" : "Reset password"}
                                                </button>
                                            )}
                                            <button
                                                className={styles.deleteButton}
                                                type="button"
                                                onClick={() => void handleDeleteUser(user)}
                                                disabled={deletingEmail === user.email || resettingEmail === user.email || reactivatingEmail === user.email}
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
                                            <dt>{user.isExpired ? "Expired" : "Expires"}</dt>
                                            <dd>
                                                {formatTimestamp(user.expiresAt)}
                                                <span className={styles.metaHint}>
                                                    {user.isExpired ? formatDaysExpired(user.daysExpired) : formatDaysRemaining(user.daysRemaining)}
                                                </span>
                                            </dd>
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

                                            <button className={styles.primaryButton} type="submit" disabled={resettingEmail === user.email}>
                                                {resettingEmail === user.email ? "Updating..." : "Save new password"}
                                            </button>
                                        </form>
                                    ) : null}
                                </article>
                            ))}
                        </div>
                    )}
                </section>
            </section>
        </main>
    );
};

export default FreeUsersPage;
