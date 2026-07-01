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
 * Per-learner storage scope so two accounts on the same browser never share chat history or the
 * active-session pointer. Uses the stable numeric `account_id` from the launch URL; falls back to
 * a shared `"anonymous"` scope when the launch carried no id (mirrors the free/rak bots). This is
 * the single source of truth for the scope, so the IndexedDB database name and the active-session
 * key always agree.
 */
export function getLemonUserScope(account: LemonAccount): string {
    const id = (account.accountId || "").trim();
    return id ? encodeURIComponent(id) : "anonymous";
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
 * Hand completion back to the web-frontend host by posting the literal completion string. Used
 * instead of `reportLemonProgress` when the bot was launched with `web_frontend=true` (iframe
 * context, where the `lemon://` scheme is a no-op). The host listens for the bare string, so the
 * payload is the string itself — not a `{ type }` object.
 *
 * The bot may be a NESTED iframe (the host's LMS shell opens our iframe), so a listener can live on
 * the immediate parent OR the top window. We post to both and dedupe when they are the same window;
 * each target is guarded independently so a cross-origin rejection on one still lets the other fire.
 * A one-line diagnostic is logged so the integrator can confirm our side fired ("I don't see a
 * postMessage") — the remaining unknown is then purely whether the host page listens for the string.
 */
export function reportWebFrontendCompletion(): void {
    if (typeof window === "undefined") {
        return;
    }

    const targets: Window[] = [];
    try {
        if (window.parent && window.parent !== window) {
            targets.push(window.parent);
        }
    } catch {
        // Cross-origin parent that rejects access — skip it.
    }
    try {
        if (window.top && window.top !== window && !targets.includes(window.top)) {
            targets.push(window.top);
        }
    } catch {
        // Cross-origin top that rejects access — skip it.
    }

    let posted = 0;
    for (const target of targets) {
        try {
            target.postMessage(WEB_FRONTEND_DONE_MESSAGE, "*");
            posted += 1;
        } catch {
            // This target rejected postMessage — try the next one.
        }
    }

    console.info("[hyrox-assessment] web completion signalled:", WEB_FRONTEND_DONE_MESSAGE, {
        targets: targets.length,
        posted
    });
}
