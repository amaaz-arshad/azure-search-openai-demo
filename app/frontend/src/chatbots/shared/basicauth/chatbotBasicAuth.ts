export type ChatbotBasicAuthSession = {
    authenticated: boolean;
    user?: string;
};

type StoredChatbotAuth = {
    user?: string;
};

type CurrentUserMapper<TUser> = (session: StoredChatbotAuth) => TUser | null;

const readStoredSession = (storageKey: string): StoredChatbotAuth | null => {
    if (typeof window === "undefined") {
        return null;
    }

    const rawValue = window.sessionStorage.getItem(storageKey);
    if (!rawValue) {
        return null;
    }

    try {
        const parsed = JSON.parse(rawValue) as StoredChatbotAuth;
        return parsed && typeof parsed === "object" ? parsed : null;
    } catch {
        return null;
    }
};

const writeStoredSession = (storageKey: string, session: StoredChatbotAuth) => {
    if (typeof window === "undefined") {
        return;
    }

    window.sessionStorage.setItem(storageKey, JSON.stringify(session));
};

const clearStoredSession = (storageKey: string) => {
    if (typeof window === "undefined") {
        return;
    }

    window.sessionStorage.removeItem(storageKey);
};

export const createSimpleChatbotAuth = <TUser = StoredChatbotAuth>(
    chatbotName: string,
    mapCurrentUser?: CurrentUserMapper<TUser>
) => {
    const storageKey = `${chatbotName}-basic-auth`;
    const authBaseUrl = `/chatbot-auth/${encodeURIComponent(chatbotName)}`;

    const applySession = (session: ChatbotBasicAuthSession): TUser | null => {
        if (!session.authenticated) {
            clearStoredSession(storageKey);
            return null;
        }

        const storedSession = { user: session.user };
        writeStoredSession(storageKey, storedSession);
        return mapCurrentUser ? mapCurrentUser(storedSession) : (storedSession as TUser);
    };

    const getCurrentSession = async (options?: { forceRefresh?: boolean }): Promise<TUser | null> => {
        const storedSession = readStoredSession(storageKey);
        if (!options?.forceRefresh && storedSession) {
            return mapCurrentUser ? mapCurrentUser(storedSession) : (storedSession as TUser);
        }

        const response = await fetch(`${authBaseUrl}/session`, {
            method: "GET",
            credentials: "include"
        });
        if (!response.ok) {
            clearStoredSession(storageKey);
            return null;
        }

        return applySession((await response.json()) as ChatbotBasicAuthSession);
    };

    const isAuthenticated = () => readStoredSession(storageKey) !== null;

    const getCurrentUser = () => {
        const storedSession = readStoredSession(storageKey);
        if (!storedSession) {
            return null;
        }

        return mapCurrentUser ? mapCurrentUser(storedSession) : (storedSession as TUser);
    };

    const login = async (username: string, password: string) => {
        const response = await fetch(`${authBaseUrl}/login`, {
            method: "POST",
            credentials: "include",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ username, password })
        });
        if (!response.ok) {
            clearStoredSession(storageKey);
            return false;
        }

        applySession((await response.json()) as ChatbotBasicAuthSession);
        return true;
    };

    const logout = async () => {
        clearStoredSession(storageKey);
        await fetch(`${authBaseUrl}/logout`, {
            method: "POST",
            credentials: "include"
        }).catch(() => undefined);
    };

    return {
        getCurrentSession,
        getCurrentUser,
        isAuthenticated,
        login,
        logout
    };
};
