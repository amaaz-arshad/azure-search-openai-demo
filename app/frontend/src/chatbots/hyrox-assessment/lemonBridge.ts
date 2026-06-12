/**
 * Lemon app integration for the HYROX assessment bot.
 *
 * The Lemon app launches the bot in a webview with the learner's identity on the query
 * string, e.g. `/hyrox-assessment?account_id=123&first_name=John&last_name=Doe`. The bot
 * uses a hash router, so the launch query string lives in `window.location.search` (before
 * the `#`) and survives in-app navigation. When the test is passed the bot hands the result
 * back to Lemon by "calling" the custom scheme `lemon://save_progress?value=100`.
 */

export type LemonAccount = {
    accountId?: string;
    firstName?: string;
    lastName?: string;
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
 * Read `account_id` / `first_name` / `last_name` from the launch URL. Missing or empty
 * values are returned as `undefined`. The result is cached in sessionStorage so a same-tab
 * reload (which may drop the query string) keeps the identity; the URL always wins when it
 * carries values.
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
        lastName: pick("last_name")
    };

    if (fromUrl.accountId || fromUrl.firstName || fromUrl.lastName) {
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
