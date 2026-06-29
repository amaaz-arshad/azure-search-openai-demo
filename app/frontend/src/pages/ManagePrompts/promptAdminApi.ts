export type PromptAdminEntry = {
    chatbotName: string;
    source: "default" | "override";
    currentPrompt: string;
    defaultPrompt: string;
    updatedAt?: string | null;
};

export type PromptAdminListResponse = {
    prompts: PromptAdminEntry[];
};

type PromptAdminMutationResponse = {
    message?: string;
    prompt: PromptAdminEntry;
};

async function parseErrorMessage(response: Response, fallbackMessage: string): Promise<never> {
    const errorBody = (await response.json().catch(() => null)) as { message?: string } | null;
    throw new Error(errorBody?.message || fallbackMessage);
}

export async function listPromptAdminEntriesApi(signal?: AbortSignal): Promise<PromptAdminListResponse> {
    const response = await fetch("/internal-admin/prompts", {
        method: "GET",
        signal
    });

    if (!response.ok) {
        await parseErrorMessage(response, `Loading prompts failed: ${response.statusText}`);
    }

    return (await response.json()) as PromptAdminListResponse;
}

export async function savePromptAdminEntryApi(chatbotName: string, prompt: string): Promise<PromptAdminMutationResponse> {
    const response = await fetch(`/internal-admin/prompts/${encodeURIComponent(chatbotName)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt })
    });

    if (!response.ok) {
        await parseErrorMessage(response, `Saving prompt failed: ${response.statusText}`);
    }

    return (await response.json()) as PromptAdminMutationResponse;
}

export async function resetPromptAdminEntryApi(chatbotName: string): Promise<PromptAdminMutationResponse> {
    const response = await fetch(`/internal-admin/prompts/${encodeURIComponent(chatbotName)}`, {
        method: "DELETE"
    });

    if (!response.ok) {
        await parseErrorMessage(response, `Resetting prompt failed: ${response.statusText}`);
    }

    return (await response.json()) as PromptAdminMutationResponse;
}
