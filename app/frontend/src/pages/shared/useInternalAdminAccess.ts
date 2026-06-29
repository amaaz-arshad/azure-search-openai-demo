import { useEffect, useState } from "react";

import {
    INTERNAL_ADMIN_REQUIRED_MESSAGE,
    getInternalAdminSessionApi,
    loginInternalAdminApi,
    logoutInternalAdminApi
} from "./internalAdminApi";
import { getInitialInternalAuthenticationState, setInternalAuthenticationState } from "./internalToolsAccess";

const INTERNAL_ADMIN_SESSION_EXPIRED_MESSAGE = "Your admin session expired. Sign in again.";

type LogoutOptions = {
    skipRequest?: boolean;
    preserveError?: boolean;
};

export function useInternalAdminAccess() {
    const [isAuthenticated, setIsAuthenticated] = useState<boolean>(getInitialInternalAuthenticationState);
    const [isCheckingAuthentication, setIsCheckingAuthentication] = useState(true);
    const [authError, setAuthError] = useState("");

    const applyAuthenticationState = (authenticated: boolean) => {
        setIsAuthenticated(authenticated);
        setInternalAuthenticationState(authenticated);
    };

    const clearAuthError = () => {
        setAuthError("");
    };

    const logout = async (options?: LogoutOptions) => {
        setIsCheckingAuthentication(true);
        try {
            if (!options?.skipRequest) {
                await logoutInternalAdminApi();
            }
        } catch {
            // Clearing local auth state matters more than surfacing logout failures here.
        } finally {
            applyAuthenticationState(false);
            if (!options?.preserveError) {
                setAuthError("");
            }
            setIsCheckingAuthentication(false);
        }
    };

    const handleUnauthorizedError = (error: unknown) => {
        if (!(error instanceof Error) || error.message !== INTERNAL_ADMIN_REQUIRED_MESSAGE) {
            return false;
        }

        applyAuthenticationState(false);
        setAuthError(INTERNAL_ADMIN_SESSION_EXPIRED_MESSAGE);
        setIsCheckingAuthentication(false);
        return true;
    };

    const login = async (password: string) => {
        setIsCheckingAuthentication(true);
        setAuthError("");
        try {
            const session = await loginInternalAdminApi(password);
            applyAuthenticationState(session.authenticated);
            return session.authenticated;
        } catch (error) {
            applyAuthenticationState(false);
            setAuthError(error instanceof Error ? error.message : "Could not sign in.");
            return false;
        } finally {
            setIsCheckingAuthentication(false);
        }
    };

    useEffect(() => {
        let isCancelled = false;

        const syncSession = async () => {
            setIsCheckingAuthentication(true);
            try {
                const session = await getInternalAdminSessionApi();
                if (isCancelled) {
                    return;
                }
                applyAuthenticationState(session.authenticated);
                if (session.authenticated) {
                    setAuthError("");
                }
            } catch (error) {
                if (isCancelled) {
                    return;
                }
                applyAuthenticationState(false);
                setAuthError(error instanceof Error ? error.message : "Could not verify admin session.");
            } finally {
                if (!isCancelled) {
                    setIsCheckingAuthentication(false);
                }
            }
        };

        void syncSession();

        return () => {
            isCancelled = true;
        };
    }, []);

    return {
        isAuthenticated,
        isCheckingAuthentication,
        authError,
        clearAuthError,
        handleUnauthorizedError,
        login,
        logout
    };
}
