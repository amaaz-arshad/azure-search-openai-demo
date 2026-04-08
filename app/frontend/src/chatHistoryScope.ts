export const NON_CHATBOT_ROUTE_SEGMENTS = new Set([
    "chatbots",
    "upload-files",
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
    if (!firstSegment || NON_CHATBOT_ROUTE_SEGMENTS.has(firstSegment)) {
        return "";
    }

    return firstSegment;
};

export const getChatHistoryScope = (): string => {
    return getCurrentChatbotName() || "default";
};
