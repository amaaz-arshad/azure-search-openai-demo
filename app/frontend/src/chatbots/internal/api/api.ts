import {
    chatApi as lemonChatApi,
    configApi as lemonConfigApi,
    deleteChatHistoryApi,
    getCitationFilePath,
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

export async function configApi(): Promise<Config> {
    return (await lemonConfigApi()) as Config;
}

export async function chatApi(
    request: ChatAppRequest,
    shouldStream: boolean,
    idToken: string | undefined,
    signal: AbortSignal
): Promise<Response> {
    return lemonChatApi(request as any, shouldStream, idToken, signal);
}

export {
    deleteChatHistoryApi,
    deleteUploadedFileApi,
    getCitationFilePath,
    getChatHistoryApi,
    getChatHistoryListApi,
    getHeaders,
    getSpeechApi,
    listUploadedFilesApi,
    postChatHistoryApi,
    uploadFileApi
};
