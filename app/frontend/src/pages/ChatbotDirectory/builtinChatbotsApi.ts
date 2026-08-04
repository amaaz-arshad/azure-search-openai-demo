/**
 * A built-in chatbot's EFFECTIVE chat settings, as the running backend would serve them.
 *
 * The compiled `chatbots/registry.ts` metadata hand-mirrors these from the deployment `.env`, which
 * silently drifts whenever a bot's `config.py` or the deployment default changes. The backend reads
 * them off the same approach object `/chat` uses, so the directory prefers this and keeps the
 * compiled values only as an offline fallback. `mode` and the agentic-retrieval default stay in the
 * frontend registry: they are frontend behavior with no backend fact behind them.
 */
export type BuiltinChatbotEntry = {
    name: string;
    llm: string | null;
    reasoningEffort?: string | null;
    // `/internal` is a router shell: its retrieval category, prompt and model all come from the
    // source bot the user picks, so it has no model of its own to display.
    variesBySourceBot?: boolean;
};

type BuiltinChatbotsResponse = {
    chatbots: BuiltinChatbotEntry[];
};

export async function listBuiltinChatbotsApi(signal?: AbortSignal): Promise<BuiltinChatbotEntry[]> {
    const response = await fetch("/internal-admin/builtin-chatbots", { method: "GET", signal });

    if (!response.ok) {
        const errorBody = (await response.json().catch(() => null)) as { message?: string } | null;
        throw new Error(errorBody?.message || `Loading built-in chatbot settings failed: ${response.statusText}`);
    }

    const payload = (await response.json()) as BuiltinChatbotsResponse;
    return Array.isArray(payload.chatbots) ? payload.chatbots : [];
}
