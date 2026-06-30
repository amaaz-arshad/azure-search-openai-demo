/**
 * Lemon app integration for the HYROX assessment bot.
 *
 * The Lemon app launches the bot in a webview with the learner's identity on the query
 * string, e.g. `/hyrox-assessment?account_id=123&first_name=John&last_name=Doe`. The bot
 * uses a hash router, so the launch query string lives in `window.location.search` (before
 * the `#`) and survives in-app navigation. When the test is passed the bot hands the result
 * back to the host so the LMS content placement can be marked complete. There are two host
 * contexts, distinguished by the `web_frontend` launch flag:
 *   - Native app (default, no flag): the custom scheme `lemon://save_progress?value=100`
 *     (see `reportLemonProgress`).
 *   - Web frontend (`web_frontend=true`): the bot runs in an iframe on the host's LMS page,
 *     which cannot act on the scheme, so it posts a literal completion string to the parent
 *     window instead (see `reportWebFrontendCompletion`).
 */

export type LemonAccount = {
    accountId?: string;
    firstName?: string;
    lastName?: string;
    // True when launched with `web_frontend=true`: switches the completion hand-off from the
    // native `lemon://` scheme to the web-frontend `postMessage` string.
    webFrontend?: boolean;
};

const STORAGE_KEY = "hyrox.lemonAccount";

function readFromStorage(): LemonAccount {
    try {
        const raw = window.sessionStorage.getItem(STORAGE_KEY);
        if (!raw) {
            return {};
        }
        const parsed = JSON.parse(raw) as LemonAccount;
        return parsed && typeof parsed === "object" ? parsed : {};
    } catch {
        return {};
    }
}

function writeToStorage(account: LemonAccount): void {
    try {
        window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(account));
    } catch {
        // sessionStorage unavailable (private mode / disabled) — non-fatal.
    }
}

/**
 * Read `account_id` / `first_name` / `last_name` / `web_frontend` from the launch URL. Missing
 * or empty values are returned as `undefined`. The result is cached in sessionStorage so a
 * same-tab reload (which may drop the query string) keeps the identity and host context; the URL
 * always wins when it carries values.
 */
export function readLemonAccount(): LemonAccount {
    if (typeof window === "undefined") {
        return {};
    }

    const params = new URLSearchParams(window.location.search);
    const pick = (key: string): string | undefined => {
        const value = params.get(key);
        return value && value.trim() !== "" ? value.trim() : undefined;
    };

    const fromUrl: LemonAccount = {
        accountId: pick("account_id"),
        firstName: pick("first_name"),
        lastName: pick("last_name"),
        webFrontend: params.get("web_frontend") === "true" ? true : undefined
    };

    if (fromUrl.accountId || fromUrl.firstName || fromUrl.lastName || fromUrl.webFrontend) {
        writeToStorage(fromUrl);
        return fromUrl;
    }

    return readFromStorage();
}

/**
 * Hand the progress value back to Lemon by triggering `lemon://save_progress?value=N`.
 *
 * Robust to both load contexts:
 *   1. `postMessage` to any embedding host (iframe case) with the value and full URL, using
 *      the same `chatbot:*` message convention as the widget bridge, so a host page can
 *      trigger the scheme on the bot's behalf.
 *   2. Navigate `window.location.href` to the scheme (direct-webview case). A registered
 *      scheme is intercepted by the native app and does not unload the page; an unregistered
 *      scheme in a plain desktop browser is a harmless no-op.
 */
export function reportLemonProgress(value: number): void {
    if (typeof window === "undefined") {
        return;
    }

    const url = `lemon://save_progress?value=${value}`;

    try {
        if (window.parent && window.parent !== window) {
            window.parent.postMessage({ type: "chatbot:save-progress", value, url }, "*");
        }
    } catch {
        // Cross-origin parent that rejects access — ignore and fall through to navigation.
    }

    try {
        window.location.href = url;
    } catch {
        // Navigation blocked — nothing more we can do client-side.
    }
}

// Web-frontend completion contract (launch with web_frontend=true). The host page embeds the
// bot in an iframe and listens for this exact literal message to mark its LMS content placement
// complete. It is the web counterpart to reportLemonProgress's lemon:// scheme (native apps).
// Fixed string per the integration contract; "Content-Typ-13" is the host's LMS content id.
export const WEB_FRONTEND_DONE_MESSAGE = "Content-Typ-13-finished";

/**
 * Hand completion back to the web-frontend host by posting the literal completion string to the
 * parent window. Used instead of `reportLemonProgress` when the bot was launched with
 * `web_frontend=true` (iframe context, where the `lemon://` scheme is a no-op). The host listens
 * for the bare string, so the payload is the string itself — not a `{ type }` object.
 */
export function reportWebFrontendCompletion(): void {
    if (typeof window === "undefined") {
        return;
    }

    try {
        window.parent.postMessage(WEB_FRONTEND_DONE_MESSAGE, "*");
    } catch {
        // Parent without postMessage access — nothing more we can do client-side.
    }
}
