import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Helmet } from "react-helmet-async";
import { NavLink, Outlet, useBlocker } from "react-router-dom";
import { Icon } from "@fluentui/react";

import { useInternalAdminAccess } from "../shared/useInternalAdminAccess";
import { AdminShellProvider } from "./AdminShellContext";
import styles from "./AdminLayout.module.css";

/*
 * Single password-gated shell for the internal admin tools. Replaces the four standalone pages'
 * duplicated login gates + cross-link headers with one gate, one tab bar, and one "Lock admin"
 * logout. Auth is unchanged server-side (the shared internal_tools_admin_session cookie via
 * useInternalAdminAccess); this only consolidates the frontend chrome and routing.
 *
 * Auth states:
 *   - Checking: brief loading view.
 *   - Unauthenticated: the shared login form.
 *   - Authenticated: sticky tab bar + nested-route <Outlet/>, each tab keeping its own page body.
 */
const ADMIN_TABS = [
    { to: "/admin/chatbots", label: "Chatbots" },
    { to: "/admin/prompts", label: "Prompts" },
    { to: "/admin/uploads", label: "Uploads" },
    { to: "/admin/users", label: "nerilio users" },
    { to: "/admin/hyrox-visits", label: "HYROX visits" },
    { to: "/admin/embed", label: "Embed demo" }
];

export function AdminLayout() {
    const { isAuthenticated, isCheckingAuthentication, authError, clearAuthError, handleUnauthorizedError, login, logout } =
        useInternalAdminAccess();
    const [password, setPassword] = useState("");
    const [isPasswordVisible, setIsPasswordVisible] = useState(false);

    // Guard registry. A tab registers a predicate returning a confirm message when leaving should
    // be blocked (unsaved prompt edits, active upload queue) or null when it is safe to leave. One
    // shell-level useBlocker covers all tab switches (and sidesteps React Router's single-active-
    // blocker limitation); the Lock button consults the same registry.
    const guardsRef = useRef<Map<string, () => string | null>>(new Map());

    const registerGuard = useCallback((id: string, getReason: () => string | null) => {
        guardsRef.current.set(id, getReason);
    }, []);
    const unregisterGuard = useCallback((id: string) => {
        guardsRef.current.delete(id);
    }, []);
    const activeGuardReason = useCallback(() => {
        for (const getReason of guardsRef.current.values()) {
            const reason = getReason();
            if (reason) {
                return reason;
            }
        }
        return null;
    }, []);

    const blocker = useBlocker(
        ({ currentLocation, nextLocation }) =>
            currentLocation.pathname !== nextLocation.pathname && activeGuardReason() !== null
    );

    useEffect(() => {
        if (blocker.state !== "blocked") {
            return;
        }
        const reason = activeGuardReason();
        if (!reason || window.confirm(reason)) {
            blocker.proceed();
        } else {
            blocker.reset();
        }
    }, [blocker, activeGuardReason]);

    const shellContextValue = useMemo(
        () => ({ handleUnauthorizedError, registerGuard, unregisterGuard }),
        [handleUnauthorizedError, registerGuard, unregisterGuard]
    );

    const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (await login(password)) {
            setPassword("");
            setIsPasswordVisible(false);
        }
    };

    const handleLockAdmin = () => {
        const reason = activeGuardReason();
        if (reason && !window.confirm(reason)) {
            return;
        }
        setPassword("");
        setIsPasswordVisible(false);
        void logout();
    };

    if (isCheckingAuthentication && !isAuthenticated) {
        return (
            <main className={styles.page}>
                <Helmet>
                    <title>Admin</title>
                </Helmet>
                <div className={styles.glowOne} aria-hidden="true" />
                <div className={styles.glowTwo} aria-hidden="true" />
                <div className={styles.loading}>Checking admin session…</div>
            </main>
        );
    }

    if (!isAuthenticated) {
        return (
            <main className={styles.page}>
                <Helmet>
                    <title>Admin · Sign in</title>
                </Helmet>
                <div className={styles.glowOne} aria-hidden="true" />
                <div className={styles.glowTwo} aria-hidden="true" />
                <section className={styles.loginShell}>
                    <div className={styles.loginCard}>
                        <div className={styles.accessHeader}>
                            <span className={styles.badge}>Protected</span>
                            <h1 className={styles.sectionTitle}>Admin</h1>
                            <p className={styles.accessDescription}>
                                Sign in with the shared internal admin password to manage chatbots, prompts, uploads, users, and embeds.
                            </p>
                        </div>
                        <form className={styles.form} onSubmit={handleSubmit} autoComplete="off">
                            <label className={styles.label} htmlFor="admin-password">
                                Password
                            </label>
                            <div className={styles.inputWrap}>
                                <input
                                    id="admin-password"
                                    className={styles.input}
                                    type={isPasswordVisible ? "text" : "password"}
                                    name="internal-admin-access-code"
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
                                {isCheckingAuthentication ? "Unlocking…" : "Unlock admin"}
                            </button>
                            <p className={styles.errorMessage} role="alert" aria-live="polite">
                                {authError}
                            </p>
                        </form>
                    </div>
                </section>
            </main>
        );
    }

    return (
        <div className={styles.adminRoot}>
            <header className={styles.topbar}>
                <div className={styles.brand}>
                    <span className={styles.badge}>Internal</span>
                    <span className={styles.brandTitle}>Admin</span>
                </div>
                <nav className={styles.tabBar} aria-label="Admin sections">
                    {ADMIN_TABS.map(tab => (
                        <NavLink key={tab.to} to={tab.to} className={({ isActive }) => `${styles.tab} ${isActive ? styles.tabActive : ""}`}>
                            {tab.label}
                        </NavLink>
                    ))}
                </nav>
                <button className={styles.lockButton} type="button" onClick={handleLockAdmin}>
                    Lock admin
                </button>
            </header>
            <AdminShellProvider value={shellContextValue}>
                <Outlet />
            </AdminShellProvider>
        </div>
    );
}

export default AdminLayout;
