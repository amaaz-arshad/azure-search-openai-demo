export const BASIC_AUTH_USER = "internal";
export const BASIC_AUTH_PASS = "internal";

const KEY = "internal-v2-basic-auth";

export const isAuthenticated = () => {
    return sessionStorage.getItem(KEY) === "true";
};

export const login = (user: string, pass: string) => {
    if (user === BASIC_AUTH_USER && pass === BASIC_AUTH_PASS) {
        sessionStorage.setItem(KEY, "true");
        return true;
    }

    return false;
};

export const logout = () => {
    sessionStorage.removeItem(KEY);
};
