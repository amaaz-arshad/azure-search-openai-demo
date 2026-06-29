const chatbotDisplayNames: Record<string, string> = {
    free: "nerilio",
    "public-test": "nerilio",
    internal: "Internal Bot"
};

const chatbotRouteSegments: Record<string, string> = {
    "public-test": "free"
};

export const formatChatbotLabel = (name: string) => chatbotDisplayNames[name] ?? name.replace(/[-_]+/g, " ");

export const getChatbotRouteSegment = (name: string) => chatbotRouteSegments[name] ?? name;

