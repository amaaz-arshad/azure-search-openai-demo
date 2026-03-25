export const INTERNAL_TOOLS_PASSWORD =
    (import.meta.env.VITE_CHATBOT_DIRECTORY_PASSWORD as string | undefined) || "chatbot123";
export const INTERNAL_TOOLS_SESSION_KEY = "chatbotDirectoryAuthenticated";

export const getInitialInternalAuthenticationState = () => {
    if (typeof window === "undefined") {
        return false;
    }

    return window.sessionStorage.getItem(INTERNAL_TOOLS_SESSION_KEY) === "true";
};
