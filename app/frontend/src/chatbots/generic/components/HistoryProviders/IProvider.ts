import type { ChatAppResponse } from "../../../../api/models";

export type HistorySessionMetadata = Record<string, any>;
export type HistoryMetaData = { id: string; title: string; timestamp: number; metadata?: HistorySessionMetadata | null };
export type Answers = [user: string, response: ChatAppResponse][];

// Dynamic (provisioned) bots only persist chat history in the browser for now — no Cosmos. Keeping the
// same enum shape as the built-in bots' providers means this can grow a CosmosDB option later without
// changing call sites.
export const enum HistoryProviderOptions {
    None = "none",
    IndexedDB = "indexedDB"
}

export interface IHistoryProvider {
    getProviderName(): HistoryProviderOptions;
    resetContinuationToken(): void;
    getNextItems(count: number): Promise<HistoryMetaData[]>;
    addItem(id: string, answers: Answers, metadata?: HistorySessionMetadata): Promise<void>;
    getItem(id: string): Promise<Answers | null>;
    deleteItem(id: string): Promise<void>;
}
