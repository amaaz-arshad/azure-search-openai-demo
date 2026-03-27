export type RakUser = {
    username: string;
};

const BASIC_AUTH_USERS = new Set(["12345", "67890"]);
const BASIC_AUTH_PASS = "rak99#";
const KEY = "rak-basic-auth-user";

export const getAuthenticatedUser = (): RakUser | null => {
    const username = (sessionStorage.getItem(KEY) || "").trim();
    if (!BASIC_AUTH_USERS.has(username)) {
        return null;
    }
    return { username };
};

export const isAuthenticated = () => getAuthenticatedUser() !== null;

export const login = (user: string, pass: string) => {
    const normalizedUser = user.trim();
    if (BASIC_AUTH_USERS.has(normalizedUser) && pass === BASIC_AUTH_PASS) {
        sessionStorage.setItem(KEY, normalizedUser);
        return true;
    }
    return false;
};

export const logout = () => {
    sessionStorage.removeItem(KEY);
};
