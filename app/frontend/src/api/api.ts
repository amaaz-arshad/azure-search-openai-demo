const BACKEND_URI = "";

import { ChatAppResponse, ChatAppResponseOrError, ChatAppRequest, Config, BotConfig, SimpleAPIResponse, HistoryListApiResponse, HistoryApiResponse } from "./models";
import { useLogin, getToken, isUsingAppServicesLogin } from "../authConfig";
import { getCurrentChatbotName } from "../chatHistoryScope";

export async function getHeaders(idToken: string | undefined): Promise<Record<string, string>> {
    // If using login and not using app services, add the id token of the logged in account as the authorization
    if (useLogin && !isUsingAppServicesLogin) {
        if (idToken) {
            return { Authorization: `Bearer ${idToken}` };
        }
    }

    return {};
}

export async function configApi(): Promise<Config> {
    const response = await fetch(`${BACKEND_URI}/config`, {
        method: "GET"
    });

    return (await response.json()) as Config;
}

// Fetch the runtime config for a dynamically provisioned bot. Throws on 404 (built-in/inactive/unknown
// name) so the caller can redirect home — identical UX to the static unknown-name fallback.
export async function botConfigApi(botName: string): Promise<BotConfig> {
    const response = await fetch(`${BACKEND_URI}/bot-config/${encodeURIComponent(botName)}`, {
        method: "GET"
    });
    if (!response.ok) {
        throw new Error(`bot-config request failed: ${response.status}`);
    }
    return (await response.json()) as BotConfig;
}

export async function chatApi(request: ChatAppRequest, shouldStream: boolean, idToken: string | undefined, signal: AbortSignal): Promise<Response> {
    let url = `${BACKEND_URI}/chat`;
    if (shouldStream) {
        url += "/stream";
    }
    const headers = await getHeaders(idToken);
    return await fetch(url, {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify(request),
        signal: signal
    });
}

export async function getSpeechApi(text: string): Promise<string | null> {
    return await fetch("/speech", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            text: text
        })
    })
        .then(response => {
            if (response.status == 200) {
                return response.blob();
            } else if (response.status == 400) {
                console.log("Speech synthesis is not enabled.");
                return null;
            } else {
                console.error("Unable to get speech synthesis.");
                return null;
            }
        })
        .then(blob => (blob ? URL.createObjectURL(blob) : null));
}

export function getCitationFilePath(citation: string): string {
    // If there are parentheses at end of citation, remove part in parentheses
    const cleanedCitation = citation.replace(/\s*\(.*?\)\s*$/, "").trim();
    const [pathWithoutFragment, fragment] = cleanedCitation.split("#", 2);
    const fragmentSuffix = fragment ? `#${fragment}` : "";
    const chatbotName = getCurrentChatbotName();
    if (!chatbotName) {
        return `${BACKEND_URI}/content/${pathWithoutFragment}${fragmentSuffix}`;
    }

    return `${BACKEND_URI}/content/${chatbotName}/${pathWithoutFragment}${fragmentSuffix}`;
}

export async function uploadFileApi(request: FormData, idToken: string): Promise<SimpleAPIResponse> {
    const response = await fetch("/upload", {
        method: "POST",
        headers: await getHeaders(idToken),
        body: request
    });

    if (!response.ok) {
        throw new Error(`Uploading files failed: ${response.statusText}`);
    }

    const dataResponse: SimpleAPIResponse = await response.json();
    return dataResponse;
}

export async function deleteUploadedFileApi(filename: string, idToken: string): Promise<SimpleAPIResponse> {
    const headers = await getHeaders(idToken);
    const response = await fetch("/delete_uploaded", {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ filename })
    });

    if (!response.ok) {
        throw new Error(`Deleting file failed: ${response.statusText}`);
    }

    const dataResponse: SimpleAPIResponse = await response.json();
    return dataResponse;
}

export async function listUploadedFilesApi(idToken: string): Promise<string[]> {
    const response = await fetch(`/list_uploaded`, {
        method: "GET",
        headers: await getHeaders(idToken)
    });

    if (!response.ok) {
        throw new Error(`Listing files failed: ${response.statusText}`);
    }

    const dataResponse: string[] = await response.json();
    return dataResponse;
}

export async function postChatHistoryApi(item: any, idToken: string): Promise<any> {
    const headers = await getHeaders(idToken);
    const chatbotName = getCurrentChatbotName();
    const response = await fetch("/chat_history", {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ ...item, chatbot_name: chatbotName })
    });

    if (!response.ok) {
        throw new Error(`Posting chat history failed: ${response.statusText}`);
    }

    const dataResponse: any = await response.json();
    return dataResponse;
}

export async function getChatHistoryListApi(count: number, continuationToken: string | undefined, idToken: string): Promise<HistoryListApiResponse> {
    const headers = await getHeaders(idToken);
    const chatbotName = getCurrentChatbotName();
    const searchParams = new URLSearchParams({ count: count.toString() });
    if (continuationToken) {
        searchParams.set("continuation_token", continuationToken);
    }
    if (chatbotName) {
        searchParams.set("chatbot_name", chatbotName);
    }

    const response = await fetch(`${BACKEND_URI}/chat_history/sessions?${searchParams.toString()}`, {
        method: "GET",
        headers: { ...headers, "Content-Type": "application/json" }
    });

    if (!response.ok) {
        throw new Error(`Getting chat histories failed: ${response.statusText}`);
    }

    const dataResponse: HistoryListApiResponse = await response.json();
    return dataResponse;
}

export async function getChatHistoryApi(id: string, idToken: string): Promise<HistoryApiResponse> {
    const headers = await getHeaders(idToken);
    const chatbotName = getCurrentChatbotName();
    const searchParams = new URLSearchParams();
    if (chatbotName) {
        searchParams.set("chatbot_name", chatbotName);
    }
    const query = searchParams.toString();
    const response = await fetch(`/chat_history/sessions/${id}${query ? `?${query}` : ""}`, {
        method: "GET",
        headers: { ...headers, "Content-Type": "application/json" }
    });

    if (!response.ok) {
        throw new Error(`Getting chat history failed: ${response.statusText}`);
    }

    const dataResponse: HistoryApiResponse = await response.json();
    return dataResponse;
}

export async function deleteChatHistoryApi(id: string, idToken: string): Promise<any> {
    const headers = await getHeaders(idToken);
    const chatbotName = getCurrentChatbotName();
    const searchParams = new URLSearchParams();
    if (chatbotName) {
        searchParams.set("chatbot_name", chatbotName);
    }
    const query = searchParams.toString();
    const response = await fetch(`/chat_history/sessions/${id}${query ? `?${query}` : ""}`, {
        method: "DELETE",
        headers: { ...headers, "Content-Type": "application/json" }
    });

    if (!response.ok) {
        throw new Error(`Deleting chat history failed: ${response.statusText}`);
    }
}
