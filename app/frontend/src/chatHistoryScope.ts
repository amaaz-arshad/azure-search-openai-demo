export const NON_CHATBOT_ROUTE_SEGMENTS = new Set([
    "chatbots",
    "upload-files",
    "free-users",
    "public-test-users",
    "manage-prompts",
    "content",
    "assets"
]);

export const getCurrentChatbotName = (): string => {
    if (typeof window === "undefined") {
        return "";
    }

    const firstSegment = (window.location.pathname.split("/").filter(Boolean)[0] || "").toLowerCase();

    // Anonymized embed route (/embed/<publicId>): every embedded bot shares the literal "embed" path
    // segment, so the readable bot identity is injected by the backend instead. Use it so chat
    // history, the active-session pointer, citation paths, and request scoping stay per-bot — i.e.
    // exactly what the old /<name>?embed=1 URL gave us. Without this, all embedded bots collapse onto
    // the shared "embed" scope and show each other's history.
    if (firstSegment === "embed") {
        return (window.__EMBED_CHATBOT_NAME__ || "").toLowerCase();
    }

    if (!firstSegment || NON_CHATBOT_ROUTE_SEGMENTS.has(firstSegment)) {
        return "";
    }

    return firstSegment;
};

export const getChatHistoryScope = (): string => {
    return getCurrentChatbotName() || "default";
};
