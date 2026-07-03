import { createContext, useContext } from "react";

/*
 * Context published by AdminLayout to the admin tab pages (Chatbots, Prompts, Uploads, nerilio
 * users, Embed demo). The shell owns the single auth session (useInternalAdminAccess) and the
 * navigation-guard registry, so the tab pages consume these instead of each running their own
 * auth hook / duplicate /internal-admin/session check.
 */
export interface AdminShellContextValue {
    // Flip the shell back to the login gate when an API call reports the session expired. Returns
    // true when the error was the "session required" sentinel and was handled.
    handleUnauthorizedError: (error: unknown) => boolean;
    // Register a guard for the active tab. getReason returns a confirm message when leaving should
    // be blocked (unsaved prompt edits, active upload queue), or null when it is safe to leave.
    // The shell runs one blocker across all tab switches and also consults these before logout.
    registerGuard: (id: string, getReason: () => string | null) => void;
    unregisterGuard: (id: string) => void;
}

const AdminShellContext = createContext<AdminShellContextValue | null>(null);

export const AdminShellProvider = AdminShellContext.Provider;

export function useAdminShell(): AdminShellContextValue {
    const value = useContext(AdminShellContext);
    if (!value) {
        throw new Error("useAdminShell must be used within the AdminLayout shell.");
    }
    return value;
}
