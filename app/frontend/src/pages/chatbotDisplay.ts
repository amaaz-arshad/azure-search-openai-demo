const chatbotDisplayNames: Record<string, string> = {
    free: "Nerilio Bot",
    "public-test": "Nerilio Bot",
    internal: "Internal Bot",
    "internal-v2": "Internal Bot v2"
};

const chatbotRouteSegments: Record<string, string> = {
    "public-test": "free"
};

export const formatChatbotLabel = (name: string) => chatbotDisplayNames[name] ?? name.replace(/[-_]+/g, " ");

export const getChatbotRouteSegment = (name: string) => chatbotRouteSegments[name] ?? name;

