import { useMemo } from "react";
import { IHistoryProvider, HistoryProviderOptions } from "./IProvider";
import { NoneProvider } from "./None";
import { IndexedDBProvider } from "./IndexedDB";
import { getChatHistoryScope } from "../../../../chatHistoryScope";

// Resolve a browser history provider for a dynamic bot. The IndexedDB database is scoped per bot via
// getChatHistoryScope() (derived from the route slug), so each provisioned bot keeps its own history —
// exactly like the built-in bots.
export const useHistoryManager = (provider: HistoryProviderOptions): IHistoryProvider => {
    const providerInstance = useMemo(() => {
        switch (provider) {
            case HistoryProviderOptions.IndexedDB:
                return new IndexedDBProvider(`chat-database-${getChatHistoryScope()}`, "chat-history");
            case HistoryProviderOptions.None:
            default:
                return new NoneProvider();
        }
    }, [provider]);

    return providerInstance;
};
