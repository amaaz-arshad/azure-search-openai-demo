/**
 * Active-session persistence for "chat follows the user across navigation".
 *
 * The browser already stores every conversation in IndexedDB (when browser chat history is
 * enabled). This helper additionally remembers *which* session the user is currently in — a
 * small pointer kept in localStorage, scoped per chatbot via `getChatHistoryScope()`. On the
 * next page load the chat reads this pointer and restores that exact session, so closing and
 * reopening a tab (or following a source link to another page) reappears the last conversation
 * instead of a blank chat. Clearing it (New Chat) makes the next load start fresh.
 *
 * Persisting the *active* pointer — rather than always restoring the newest stored session — is
 * what makes New Chat behave correctly: after New Chat with nothing sent yet there is no
 * pointer, so the next load is blank.
 *
 * All access is try/catch-guarded: in private mode or blocked third-party storage the helper
 * silently no-ops and the chat falls back to today's blank-on-load behavior.
 */
import { getChatHistoryScope } from "../../../chatHistoryScope";

const keyFor = (scope: string) => `chatbot-active-session:${scope}`;

export function readActiveSessionId(): string | null {
    try {
        return window.localStorage.getItem(keyFor(getChatHistoryScope())) || null;
    } catch {
        return null;
    }
}

export function writeActiveSessionId(id: string): void {
    if (!id) {
        return;
    }
    try {
        window.localStorage.setItem(keyFor(getChatHistoryScope()), id);
    } catch {
        /* storage blocked — the active session simply won't persist */
    }
}

export function clearActiveSessionId(): void {
    try {
        window.localStorage.removeItem(keyFor(getChatHistoryScope()));
    } catch {
        /* storage blocked — nothing to clear */
    }
}
