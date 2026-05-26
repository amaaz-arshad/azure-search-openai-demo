import { Helmet } from "react-helmet-async";
import { Outlet } from "react-router-dom";

import { useInternalAdminAccess } from "../useInternalAdminAccess";
import { Sidebar } from "./components/Sidebar";
import { LoginPage } from "./pages/LoginPage";
import "./verwaltung.css";

/*
 * Top-level wrapper for /verwaltung/*. Handles admin auth via the existing
 * useInternalAdminAccess hook (shared with /chatbots, /manage-prompts, etc.).
 *
 * Auth states:
 *   - Checking: brief loading view
 *   - Unauthenticated: renders the ported LoginPage which calls login()
 *   - Authenticated: renders the app shell with sidebar + nested route Outlet
 *
 * PortalPage is intentionally NOT inside this layout (it represents the
 * customer-user surface from the source and has no sidebar/admin gate).
 */
export function VerwaltungLayout() {
    const { isAuthenticated, isCheckingAuthentication, authError, clearAuthError, login, logout } = useInternalAdminAccess();

    if (isCheckingAuthentication && !isAuthenticated) {
        return (
            <div className="verwaltung-root">
                <Helmet>
                    <title>Verwaltung – nerilio</title>
                </Helmet>
                <div className="loading">Lade …</div>
            </div>
        );
    }

    if (!isAuthenticated) {
        return (
            <div className="verwaltung-root login-page">
                <Helmet>
                    <title>Login – nerilio</title>
                </Helmet>
                <LoginPage onLogin={login} isSubmitting={isCheckingAuthentication} errorMessage={authError} onClearError={clearAuthError} />
            </div>
        );
    }

    return (
        <div className="verwaltung-root">
            <Helmet>
                <title>Verwaltung – nerilio</title>
            </Helmet>
            <div className="app">
                <Sidebar onLogout={() => void logout()} />
                <main className="content">
                    <Outlet />
                </main>
            </div>
        </div>
    );
}

export default VerwaltungLayout;
