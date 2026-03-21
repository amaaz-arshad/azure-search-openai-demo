export const BASIC_AUTH_USER = "moodle";
export const BASIC_AUTH_PASS = "H8mburg#";

const KEY = "moodle-basic-auth";

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
