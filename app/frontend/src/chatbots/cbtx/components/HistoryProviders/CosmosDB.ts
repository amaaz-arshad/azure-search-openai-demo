import { IHistoryProvider, Answers, HistoryProviderOptions, HistoryMetaData, HistorySessionMetadata } from "./IProvider";
import { deleteChatHistoryApi, getChatHistoryApi, getChatHistoryListApi, postChatHistoryApi } from "../../api";

export class CosmosDBProvider implements IHistoryProvider {
    getProviderName = () => HistoryProviderOptions.CosmosDB;

    private continuationToken: string | undefined;
    private isItemEnd: boolean = false;

    resetContinuationToken() {
        this.continuationToken = undefined;
        this.isItemEnd = false;
    }

    async getNextItems(count: number, idToken?: string): Promise<HistoryMetaData[]> {
        if (this.isItemEnd) {
            return [];
        }

        try {
            const response = await getChatHistoryListApi(count, this.continuationToken, idToken || "");
            this.continuationToken = response.continuation_token;
            if (!this.continuationToken) {
                this.isItemEnd = true;
            }
            return response.sessions.map(session => ({
                id: session.id,
                title: session.title,
                timestamp: session.timestamp,
                metadata: session.metadata
            }));
        } catch (e) {
            console.error(e);
            return [];
        }
    }

    async addItem(id: string, answers: Answers, idToken?: string, metadata?: HistorySessionMetadata): Promise<void> {
        await postChatHistoryApi({ id, answers, metadata }, idToken || "");
        return;
    }

    async getItem(id: string, idToken?: string): Promise<Answers | null> {
        const response = await getChatHistoryApi(id, idToken || "");
        if (!response.answers) {
            return null;
        }

        const answers = response.answers as Answers & { metadata?: HistorySessionMetadata | null };
        if (response.metadata !== undefined) {
            answers.metadata = response.metadata;
        }
        return answers;
    }

    async deleteItem(id: string, idToken?: string): Promise<void> {
        await deleteChatHistoryApi(id, idToken || "");
        return;
    }
}
