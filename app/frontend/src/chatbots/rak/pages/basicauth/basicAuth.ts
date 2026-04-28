import { createSimpleChatbotAuth } from "../../../shared/basicauth/chatbotBasicAuth";

export type RakUser = {
    username: string;
};

const auth = createSimpleChatbotAuth<RakUser>("rak", session => {
    const username = session.user?.trim();
    return username ? { username } : null;
});

export const getCurrentSession = auth.getCurrentSession;
export const getAuthenticatedUser = auth.getCurrentUser;
export const isAuthenticated = auth.isAuthenticated;
export const login = auth.login;
export const logout = auth.logout;
