import type { ChatbotMode } from "../../chatbots/registry";

/**
 * A provisioned ("dynamic") chatbot as the admin directory sees it. These bots live in the backend
 * registry rather than the compiled frontend registry, so the directory has to fetch them; `llm` and
 * `reasoningEffort` are the EFFECTIVE values the backend would really serve with.
 */
export type DynamicChatbotEntry = {
    botName: string;
    displayName: string;
    active: boolean;
    publicId: string | null;
    llm: string;
    reasoningEffort?: string | null;
    mode: ChatbotMode;
    plan?: string | null;
    numberSessions?: number;
    createdAt?: string;
    updatedAt?: string;
};

type DynamicChatbotsResponse = {
    chatbots: DynamicChatbotEntry[];
};

export async function listDynamicChatbotsApi(signal?: AbortSignal): Promise<DynamicChatbotEntry[]> {
    const response = await fetch("/internal-admin/dynamic-chatbots", { method: "GET", signal });

    if (!response.ok) {
        const errorBody = (await response.json().catch(() => null)) as { message?: string } | null;
        throw new Error(errorBody?.message || `Loading provisioned chatbots failed: ${response.statusText}`);
    }

    const payload = (await response.json()) as DynamicChatbotsResponse;
    return Array.isArray(payload.chatbots) ? payload.chatbots : [];
}
