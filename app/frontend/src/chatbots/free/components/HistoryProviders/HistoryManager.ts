import { useContext, useMemo } from "react";
import { IHistoryProvider, HistoryProviderOptions } from "./IProvider";
import { NoneProvider } from "./None";
import { IndexedDBProvider } from "./IndexedDB";
import { CosmosDBProvider } from "./CosmosDB";
import { getChatHistoryScope } from "../../../../chatHistoryScope";
import { LoginContext } from "../../loginContext";

const getFreeUserScope = (email: string | null | undefined) => {
    const normalizedEmail = (email || "").trim().toLowerCase();
    if (!normalizedEmail) {
        return "anonymous";
    }

    return encodeURIComponent(normalizedEmail);
};

export const useHistoryManager = (provider: HistoryProviderOptions): IHistoryProvider => {
    const { currentUser } = useContext(LoginContext);

    const providerInstance = useMemo(() => {
        switch (provider) {
            case HistoryProviderOptions.IndexedDB:
                return new IndexedDBProvider(`chat-database-${getChatHistoryScope()}-${getFreeUserScope(currentUser?.email)}`, "chat-history");
            case HistoryProviderOptions.CosmosDB:
                return new CosmosDBProvider();
            case HistoryProviderOptions.None:
            default:
                return new NoneProvider();
        }
    }, [currentUser?.email, provider]);

    return providerInstance;
};
