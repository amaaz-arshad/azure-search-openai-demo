const BACKEND_URI = "";

import {
    ChatAppResponse,
    ChatAppResponseOrError,
    ChatAppRequest,
    Config,
    SimpleAPIResponse,
    HistoryListApiResponse,
    HistoryApiResponse,
    ChatbotUploadResponse,
    ChatbotBulkDeleteResponse
} from "./models";
import { useLogin, getToken, isUsingAppServicesLogin } from "../authConfig";

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
    const firstSegment = typeof window === "undefined" ? "" : window.location.pathname.split("/").filter(Boolean)[0] || "";
    const chatbotName = !firstSegment || ["chatbots", "upload-files", "content", "assets"].includes(firstSegment) ? "" : firstSegment;
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

export async function uploadChatbotFilesApi(
    chatbotName: string,
    request: FormData,
    options?: { signal?: AbortSignal; uploadId?: string }
): Promise<ChatbotUploadResponse> {
    const headers: Record<string, string> = {};
    if (options?.uploadId) {
        headers["X-Upload-Id"] = options.uploadId;
    }

    const response = await fetch(`/chatbot_uploads/${chatbotName}`, {
        method: "POST",
        body: request,
        headers,
        signal: options?.signal
    });

    if (!response.ok) {
        const errorBody = (await response.json().catch(() => null)) as SimpleAPIResponse | null;
        throw new Error(errorBody?.message || `Uploading files failed: ${response.statusText}`);
    }

    return (await response.json()) as ChatbotUploadResponse;
}

export async function listChatbotUploadedFilesApi(chatbotName: string): Promise<string[]> {
    const response = await fetch(`/chatbot_uploads/${chatbotName}`, {
        method: "GET"
    });

    if (!response.ok) {
        throw new Error(`Listing files failed: ${response.statusText}`);
    }

    return (await response.json()) as string[];
}

export async function cancelChatbotUploadApi(chatbotName: string, uploadId: string): Promise<SimpleAPIResponse> {
    const response = await fetch(`/chatbot_uploads/${chatbotName}/cancel/${encodeURIComponent(uploadId)}`, {
        method: "POST"
    });

    if (!response.ok) {
        const errorBody = (await response.json().catch(() => null)) as SimpleAPIResponse | null;
        throw new Error(errorBody?.message || `Stopping upload failed: ${response.statusText}`);
    }

    return (await response.json()) as SimpleAPIResponse;
}

export async function deleteChatbotUploadedFileApi(chatbotName: string, filename: string): Promise<SimpleAPIResponse> {
    const response = await fetch(`/chatbot_uploads/${chatbotName}/${encodeURIComponent(filename)}`, {
        method: "DELETE"
    });

    if (!response.ok) {
        const errorBody = (await response.json().catch(() => null)) as SimpleAPIResponse | null;
        throw new Error(errorBody?.message || `Deleting file failed: ${response.statusText}`);
    }

    return (await response.json()) as SimpleAPIResponse;
}

export async function deleteAllChatbotUploadedFilesApi(chatbotName: string): Promise<ChatbotBulkDeleteResponse> {
    const response = await fetch(`/chatbot_uploads/${chatbotName}`, {
        method: "DELETE"
    });

    if (!response.ok) {
        const errorBody = (await response.json().catch(() => null)) as ChatbotBulkDeleteResponse | null;
        throw new Error(errorBody?.message || `Deleting files failed: ${response.statusText}`);
    }

    return (await response.json()) as ChatbotBulkDeleteResponse;
}

export async function postChatHistoryApi(item: any, idToken: string): Promise<any> {
    const headers = await getHeaders(idToken);
    const response = await fetch("/chat_history", {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify(item)
    });

    if (!response.ok) {
        throw new Error(`Posting chat history failed: ${response.statusText}`);
    }

    const dataResponse: any = await response.json();
    return dataResponse;
}

export async function getChatHistoryListApi(count: number, continuationToken: string | undefined, idToken: string): Promise<HistoryListApiResponse> {
    const headers = await getHeaders(idToken);
    let url = `${BACKEND_URI}/chat_history/sessions?count=${count}`;
    if (continuationToken) {
        url += `&continuationToken=${continuationToken}`;
    }

    const response = await fetch(url.toString(), {
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
    const response = await fetch(`/chat_history/sessions/${id}`, {
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
    const response = await fetch(`/chat_history/sessions/${id}`, {
        method: "DELETE",
        headers: { ...headers, "Content-Type": "application/json" }
    });

    if (!response.ok) {
        throw new Error(`Deleting chat history failed: ${response.statusText}`);
    }
}
