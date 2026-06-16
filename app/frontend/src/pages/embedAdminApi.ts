export type EmbedConfigEntry = {
    chatbotName: string;
    publicId: string | null;
    allowedRules: string[];
    updatedAt?: string | null;
};

type EmbedConfigResponse = {
    embedConfig: EmbedConfigEntry;
};

type EmbedConfigMutationResponse = {
    message?: string;
    embedConfig: EmbedConfigEntry;
};

async function parseErrorMessage(response: Response, fallbackMessage: string): Promise<never> {
    const errorBody = (await response.json().catch(() => null)) as { message?: string } | null;
    throw new Error(errorBody?.message || fallbackMessage);
}

export async function getEmbedConfigApi(chatbotName: string, signal?: AbortSignal): Promise<EmbedConfigEntry> {
    const response = await fetch(`/internal-admin/embed-config/${encodeURIComponent(chatbotName)}`, {
        method: "GET",
        signal
    });

    if (!response.ok) {
        await parseErrorMessage(response, `Loading embed config failed: ${response.statusText}`);
    }

    return ((await response.json()) as EmbedConfigResponse).embedConfig;
}

export async function saveEmbedConfigApi(chatbotName: string, allowedRules: string[]): Promise<EmbedConfigEntry> {
    const response = await fetch(`/internal-admin/embed-config/${encodeURIComponent(chatbotName)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ allowedRules })
    });

    if (!response.ok) {
        await parseErrorMessage(response, `Saving embed whitelist failed: ${response.statusText}`);
    }

    return ((await response.json()) as EmbedConfigMutationResponse).embedConfig;
}
