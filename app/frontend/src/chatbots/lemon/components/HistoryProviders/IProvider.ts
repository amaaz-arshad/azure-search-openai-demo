import { ChatAppResponse } from "../../api";

export type HistorySessionMetadata = Record<string, any>;
export type HistoryMetaData = { id: string; title: string; timestamp: number; metadata?: HistorySessionMetadata | null };
export type Answers = [user: string, response: ChatAppResponse][];

export const enum HistoryProviderOptions {
    None = "none",
    IndexedDB = "indexedDB",
    CosmosDB = "cosmosDB"
}

export interface IHistoryProvider {
    getProviderName(): HistoryProviderOptions;
    resetContinuationToken(): void;
    getNextItems(count: number, idToken?: string): Promise<HistoryMetaData[]>;
    addItem(id: string, answers: Answers, idToken?: string, metadata?: HistorySessionMetadata): Promise<void>;
    getItem(id: string, idToken?: string): Promise<Answers | null>;
    deleteItem(id: string, idToken?: string): Promise<void>;
}
