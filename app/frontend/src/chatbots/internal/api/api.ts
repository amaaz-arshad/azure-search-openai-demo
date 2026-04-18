import {
    configApi as lemonConfigApi,
    deleteChatHistoryApi,
    getChatHistoryApi,
    getChatHistoryListApi,
    getHeaders,
    getSpeechApi,
    listUploadedFilesApi,
    postChatHistoryApi,
    uploadFileApi,
    deleteUploadedFileApi
} from "../../lemon/api/api";
import type { ChatAppRequest, Config } from "./models";

const BACKEND_URI = "";

export async function configApi(): Promise<Config> {
    return (await lemonConfigApi()) as Config;
}

export async function chatApi(
    request: ChatAppRequest,
    shouldStream: boolean,
    idToken: string | undefined,
    signal: AbortSignal
): Promise<Response> {
    let url = `${BACKEND_URI}/chat`;
    if (shouldStream) {
        url += "/stream";
    }
    const headers = await getHeaders(idToken);
    return await fetch(url, {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json", "X-Chatbot-Name": "internal" },
        body: JSON.stringify(request),
        signal
    });
}

export function getCitationFilePath(citation: string, sourceChatbot?: string): string {
    const cleanedCitation = citation.replace(/\s*\(.*?\)\s*$/, "").trim();
    const [pathWithoutFragment, fragment] = cleanedCitation.split("#", 2);
    const fragmentSuffix = fragment ? `#${fragment}` : "";
    if (!sourceChatbot) {
        return `${BACKEND_URI}/content/${pathWithoutFragment}${fragmentSuffix}`;
    }

    return `${BACKEND_URI}/content/${sourceChatbot}/${pathWithoutFragment}${fragmentSuffix}`;
}

export {
    deleteChatHistoryApi,
    deleteUploadedFileApi,
    getChatHistoryApi,
    getChatHistoryListApi,
    getHeaders,
    getSpeechApi,
    listUploadedFilesApi,
    postChatHistoryApi,
    uploadFileApi
};
