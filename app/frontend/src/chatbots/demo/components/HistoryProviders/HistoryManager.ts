import { useMemo } from "react";
import { IHistoryProvider, HistoryProviderOptions } from "./IProvider";
import { NoneProvider } from "./None";
import { IndexedDBProvider } from "./IndexedDB";
import { CosmosDBProvider } from "./CosmosDB";
import { getChatHistoryScope } from "../../../../chatHistoryScope";

export const useHistoryManager = (provider: HistoryProviderOptions): IHistoryProvider => {
    const providerInstance = useMemo(() => {
        switch (provider) {
            case HistoryProviderOptions.IndexedDB:
                return new IndexedDBProvider(`chat-database-${getChatHistoryScope()}`, "chat-history");
            case HistoryProviderOptions.CosmosDB:
                return new CosmosDBProvider();
            case HistoryProviderOptions.None:
            default:
                return new NoneProvider();
        }
    }, [provider]);

    return providerInstance;
};
