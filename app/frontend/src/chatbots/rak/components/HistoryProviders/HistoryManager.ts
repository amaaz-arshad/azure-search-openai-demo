import { useContext, useMemo } from "react";
import { IHistoryProvider, HistoryProviderOptions } from "./IProvider";
import { NoneProvider } from "./None";
import { IndexedDBProvider } from "./IndexedDB";
import { CosmosDBProvider } from "./CosmosDB";
import { getChatHistoryScope } from "../../../../chatHistoryScope";
import { LoginContext } from "../../loginContext";

const getRakUserScope = (username: string | null | undefined) => {
    const normalizedUsername = (username || "").trim();
    if (!normalizedUsername) {
        return "anonymous";
    }

    return encodeURIComponent(normalizedUsername);
};

export const useHistoryManager = (provider: HistoryProviderOptions): IHistoryProvider => {
    const { currentUser } = useContext(LoginContext);

    const providerInstance = useMemo(() => {
        switch (provider) {
            case HistoryProviderOptions.IndexedDB:
                return new IndexedDBProvider(`chat-database-${getChatHistoryScope()}-${getRakUserScope(currentUser?.username)}`, "chat-history");
            case HistoryProviderOptions.CosmosDB:
                return new CosmosDBProvider();
            case HistoryProviderOptions.None:
            default:
                return new NoneProvider();
        }
    }, [currentUser?.username, provider]);

    return providerInstance;
};
