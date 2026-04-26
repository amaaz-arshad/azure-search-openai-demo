import { createSimpleChatbotAuth } from "../../../shared/basicauth/chatbotBasicAuth";

export const { getCurrentSession, isAuthenticated, login, logout } = createSimpleChatbotAuth("steuertipps");
