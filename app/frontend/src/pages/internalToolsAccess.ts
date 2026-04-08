export const INTERNAL_TOOLS_SESSION_KEY = "internalToolsAdminAuthenticated";

export const getInitialInternalAuthenticationState = () => {
    if (typeof window === "undefined") {
        return false;
    }

    return window.sessionStorage.getItem(INTERNAL_TOOLS_SESSION_KEY) === "true";
};

export const setInternalAuthenticationState = (isAuthenticated: boolean) => {
    if (typeof window === "undefined") {
        return;
    }

    if (isAuthenticated) {
        window.sessionStorage.setItem(INTERNAL_TOOLS_SESSION_KEY, "true");
        return;
    }

    window.sessionStorage.removeItem(INTERNAL_TOOLS_SESSION_KEY);
};
