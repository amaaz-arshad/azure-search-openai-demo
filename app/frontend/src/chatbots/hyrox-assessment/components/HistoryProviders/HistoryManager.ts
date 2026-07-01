import { useMemo } from "react";
import { IHistoryProvider, HistoryProviderOptions } from "../HistoryProviders/IProvider";
import { NoneProvider } from "../HistoryProviders/None";
import { IndexedDBProvider } from "../HistoryProviders/IndexedDB";
import { CosmosDBProvider } from "../HistoryProviders/CosmosDB";
import { getChatHistoryScope } from "../../../../chatHistoryScope";
import { getLemonUserScope, readLemonAccount } from "../../lemonBridge";

export const useHistoryManager = (provider: HistoryProviderOptions): IHistoryProvider => {
    // Scope browser history per learner (account_id from the launch URL) so two users on the same
    // computer never share or resume each other's assessment. Missing id → shared "anonymous"
    // scope (today's behavior for un-identified launches). Both the chat page and the History panel
    // call this hook, so they stay on the same database automatically.
    const userScope = getLemonUserScope(readLemonAccount());
    const providerInstance = useMemo(() => {
        switch (provider) {
            case HistoryProviderOptions.IndexedDB:
                return new IndexedDBProvider(`chat-database-${getChatHistoryScope()}-${userScope}`, "chat-history");
            case HistoryProviderOptions.CosmosDB:
                return new CosmosDBProvider();
            case HistoryProviderOptions.None:
            default:
                return new NoneProvider();
        }
    }, [provider, userScope]);

    return providerInstance;
};
