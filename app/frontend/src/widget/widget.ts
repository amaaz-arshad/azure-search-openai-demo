/**
 * Embeddable chatbot widget loader.
 *
 * A tiny, dependency-free script (no React/Fluent) that website owners embed with a single
 * <script> tag. `data-chatbot-id` is an anonymous, generated public ID (GA/Clarity style) — never
 * the readable chatbot name. On load the widget fetches the bot's public embed config
 * (`<origin>/embed/<publicId>/config`); if the current page is not on that bot's whitelist it
 * renders nothing. Otherwise it injects a floating launcher and, on first open, a cross-origin
 * iframe that loads `<origin>/embed/<publicId>?embed=1` (which resolves the bot server-side, so the
 * name never appears in the host DOM). All chat traffic stays inside that iframe (same-origin to
 * the backend), so no CORS is required on the host site for chat.
 *
 * Usage (primary, race-free):
 *   <script async src="https://chat.nerilio.ai/widget.js" data-chatbot-id="muw0oowcw3"></script>
 *
 * Usage (programmatic, e.g. SPAs):
 *   <script async src="https://chat.nerilio.ai/widget.js"></script>
 *   <script>
 *     window.chatbot = window.chatbot || { q: [], init(o){this.q.push(["init",o])},
 *       open(){this.q.push(["open"])}, close(){this.q.push(["close"])} };
 *     chatbot.init({ chatbotId: "muw0oowcw3" });
 *   </script>
 */

interface ChatbotWidgetConfig {
    /** Anonymous public ID from the embed snippet (never the readable chatbot name). */
    chatbotId: string;
    position?: "right" | "left";
    primaryColor?: string;
    /** Launcher icon (foreground) color. Defaults to white; used for dark/branded bubbles. */
    launcherIconColor?: string;
    launcherText?: string;
    locale?: string;
    autoOpen?: boolean;
}

interface ChatbotWidgetApi {
    init: (config: ChatbotWidgetConfig) => void;
    open: () => void;
    close: () => void;
    /** Internal command queue used by the snippet stub before this script loads. */
    q?: Array<[string, ChatbotWidgetConfig?]>;
}

declare global {
    interface Window {
        chatbot?: ChatbotWidgetApi;
    }
}

(function () {
    // Final fallback only — used when the chatbotId has no theme entry and no data-primary-color.
    const DEFAULT_PRIMARY_COLOR = "#4f46e5";
    // Default launcher icon (foreground) color; overridden per-bot only for dark/branded bubbles.
    const DEFAULT_ICON_COLOR = "#ffffff";
    const HOST_ELEMENT_ID = "nerilio-chatbot-widget-host";
    const MIN_WIDTH = 320;
    const MIN_HEIGHT = 380;

    const sizeStorageKey = (chatbotId: string) => `chatbot-widget-size:${chatbotId}`;

    function readStoredSize(chatbotId: string): { width: number; height: number } | null {
        try {
            const raw = window.localStorage.getItem(sizeStorageKey(chatbotId));
            if (!raw) {
                return null;
            }
            const parsed = JSON.parse(raw);
            if (typeof parsed?.width === "number" && typeof parsed?.height === "number") {
                return { width: parsed.width, height: parsed.height };
            }
        } catch {
            /* storage blocked (private mode / third-party) — fall back to default size */
        }
        return null;
    }

    function writeStoredSize(chatbotId: string, width: number, height: number) {
        try {
            window.localStorage.setItem(sizeStorageKey(chatbotId), JSON.stringify({ width, height }));
        } catch {
            /* storage blocked — size simply won't persist */
        }
    }

    // Remember whether the panel was open, so the chat "follows" the user across pages of the
    // host site: if it was open when they navigated/closed the tab, it re-opens on the next page;
    // if they had closed it, it stays closed. Stored in the host page's first-party localStorage.
    const openStorageKey = (chatbotId: string) => `chatbot-widget-open:${chatbotId}`;

    function readStoredOpen(chatbotId: string): boolean {
        try {
            return window.localStorage.getItem(openStorageKey(chatbotId)) === "1";
        } catch {
            /* storage blocked — default to closed */
            return false;
        }
    }

    function writeStoredOpen(chatbotId: string, isOpen: boolean) {
        try {
            window.localStorage.setItem(openStorageKey(chatbotId), isOpen ? "1" : "0");
        } catch {
            /* storage blocked — open state simply won't persist */
        }
    }

    // Resolve the backend origin from this very script's URL so the widget always talks back to
    // whichever host served it (no hardcoded domain).
    const scriptEl =
        (document.currentScript as HTMLScriptElement | null) ??
        (Array.from(document.getElementsByTagName("script")).find(s => /\/widget\.js(\?|$)/.test(s.src)) as
            | HTMLScriptElement
            | undefined) ??
        null;
    const backendOrigin = scriptEl ? new URL(scriptEl.src, window.location.href).origin : window.location.origin;

    let widget: WidgetInstance | null = null;
    // init() kicks off an async config fetch; these guard against double-init and remember an
    // open() that arrived before the widget finished initialising.
    let initStarted = false;
    let pendingOpen = false;

    interface WidgetInstance {
        config: Required<Pick<ChatbotWidgetConfig, "chatbotId" | "position" | "primaryColor">> & ChatbotWidgetConfig;
        shadow: ShadowRoot;
        launcher: HTMLButtonElement;
        panel: HTMLDivElement;
        iframe: HTMLIFrameElement | null;
        isOpen: boolean;
    }

    function readConfigFromScript(): ChatbotWidgetConfig | null {
        if (!scriptEl) {
            return null;
        }
        const chatbotId = scriptEl.getAttribute("data-chatbot-id");
        if (!chatbotId) {
            return null;
        }
        const position = scriptEl.getAttribute("data-position");
        return {
            chatbotId,
            position: position === "left" ? "left" : "right",
            primaryColor: scriptEl.getAttribute("data-primary-color") || undefined,
            launcherIconColor: scriptEl.getAttribute("data-icon-color") || undefined,
            launcherText: scriptEl.getAttribute("data-launcher-text") || undefined,
            locale: scriptEl.getAttribute("data-locale") || undefined,
            autoOpen: scriptEl.getAttribute("data-auto-open") === "true"
        };
    }

    function buildIframeSrc(config: ChatbotWidgetConfig): string {
        const params = new URLSearchParams({ embed: "1" });
        if (config.locale) {
            params.set("locale", config.locale);
        }
        // The anonymized route resolves the public ID server-side, so the chatbot name never
        // appears in the iframe `src`.
        return `${backendOrigin}/embed/${encodeURIComponent(config.chatbotId)}?${params.toString()}`;
    }

    // Public embed config returned by the backend, fetched cross-origin before anything renders.
    interface WidgetRemoteConfig {
        ok: boolean;
        primaryColor?: string;
        launcherIconColor?: string;
        allowAll?: boolean;
        rules?: string[];
    }

    async function fetchRemoteConfig(publicId: string): Promise<WidgetRemoteConfig | null> {
        try {
            const response = await fetch(`${backendOrigin}/embed/${encodeURIComponent(publicId)}/config`, {
                method: "GET",
                credentials: "omit"
            });
            if (!response.ok) {
                return null;
            }
            const data = (await response.json()) as WidgetRemoteConfig;
            return data && typeof data === "object" && data.ok === true ? data : null;
        } catch {
            // Network/CORS failure or unknown public ID — render nothing rather than guess.
            return null;
        }
    }

    // --- whitelist matching (mirrors app/backend/embed_rules.py; keep the two in lockstep) -------

    function parseRule(rule: string): { host: string; path: string | null } | null {
        const candidate = rule.trim().replace(/^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//, "");
        if (!candidate) {
            return null;
        }
        const slash = candidate.indexOf("/");
        const host = (slash === -1 ? candidate : candidate.slice(0, slash)).trim().toLowerCase();
        if (!host) {
            return null;
        }
        return { host, path: slash === -1 ? null : candidate.slice(slash) };
    }

    function hostMatches(patternHost: string, urlHost: string): boolean {
        const host = (urlHost || "").toLowerCase();
        if (!host) {
            return false;
        }
        if (patternHost.startsWith("*.")) {
            const suffix = patternHost.slice(1); // ".snap.de"
            return host.endsWith(suffix) && host.length > suffix.length;
        }
        return host === patternHost;
    }

    function pathMatches(patternPath: string | null, urlPath: string): boolean {
        if (patternPath === null || patternPath === "" || patternPath === "/" || patternPath === "/*") {
            return true;
        }
        const path = urlPath || "/";
        if (patternPath.endsWith("/*")) {
            const prefix = patternPath.slice(0, -2);
            return path === prefix || path.startsWith(prefix + "/");
        }
        if (patternPath.endsWith("*")) {
            return path.startsWith(patternPath.slice(0, -1));
        }
        return path === patternPath;
    }

    function isUrlAllowed(rules: string[], url: string): boolean {
        const parsed = rules
            .map(parseRule)
            .filter((rule): rule is { host: string; path: string | null } => rule !== null);
        if (parsed.length === 0) {
            return true; // empty whitelist => allow all
        }
        let host = "";
        let path = "/";
        try {
            const parsedUrl = new URL(url);
            host = parsedUrl.hostname;
            path = parsedUrl.pathname || "/";
        } catch {
            return false;
        }
        return parsed.some(rule => hostMatches(rule.host, host) && pathMatches(rule.path, path));
    }

    const CHAT_ICON =
        '<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>';
    const CLOSE_ICON =
        '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';

    function styleSheet(primaryColor: string, iconColor: string, position: "right" | "left"): string {
        const side = position === "left" ? "left" : "right";
        // The panel is anchored to `side`, so it grows from the opposite edge — that's where the
        // resize handles live (top edge, opposite side edge, and the corner between them).
        const resizeSide = position === "left" ? "right" : "left";
        const cornerCursor = position === "left" ? "nesw-resize" : "nwse-resize";
        return `
:host { all: initial; }
* { box-sizing: border-box; font-family: "Segoe UI", system-ui, -apple-system, sans-serif; }
.launcher {
    position: fixed; bottom: 20px; ${side}: 20px; z-index: 2147483000;
    width: 60px; height: 60px; border-radius: 50%; border: none; cursor: pointer;
    background: ${primaryColor}; color: ${iconColor}; display: flex; align-items: center; justify-content: center;
    box-shadow: 0 6px 24px rgba(0,0,0,0.28); transition: transform .15s ease, box-shadow .15s ease;
}
.launcher:hover { transform: scale(1.06); box-shadow: 0 10px 28px rgba(0,0,0,0.34); }
.launcher:focus-visible { outline: 3px solid rgba(255,255,255,0.6); outline-offset: 2px; }
.panel {
    position: fixed; bottom: 92px; ${side}: 20px; z-index: 2147483000;
    width: var(--cw-width, 400px); height: var(--cw-height, 640px);
    max-height: calc(100vh - 112px); max-width: calc(100vw - 40px);
    border-radius: 16px; overflow: hidden; background: #fff;
    box-shadow: 0 12px 48px rgba(0,0,0,0.30);
    opacity: 0; transform: translateY(12px) scale(0.98); pointer-events: none;
    transition: opacity .18s ease, transform .18s ease;
}
.panel.open { opacity: 1; transform: translateY(0) scale(1); pointer-events: auto; }
.panel iframe { width: 100%; height: 100%; border: 0; display: block; }
/* Drag-to-resize handles (desktop). Pointer capture keeps the drag alive over the iframe. */
.rz-handle { position: absolute; z-index: 3; touch-action: none; }
.rz-top { top: 0; left: 0; right: 0; height: 9px; cursor: ns-resize; }
.rz-side { top: 0; bottom: 0; ${resizeSide}: 0; width: 9px; cursor: ew-resize; }
.rz-corner { top: 0; ${resizeSide}: 0; width: 20px; height: 20px; z-index: 4; cursor: ${cornerCursor}; }
.panel.resizing { user-select: none; transition: none; }
.panel.resizing iframe { pointer-events: none; }
@media (max-width: 480px) {
    /* Near-fullscreen, but leave the launcher peeking at the bottom so it stays the close control
       (no in-iframe close button that could overlap the bot's own header). Resize is desktop-only;
       the explicit width/height here override the --cw-* custom size on small screens. */
    .panel {
        width: calc(100vw - 24px); max-width: calc(100vw - 24px);
        height: calc(100dvh - 104px); max-height: calc(100dvh - 104px);
        bottom: 88px; ${side}: 12px; border-radius: 16px;
    }
    .rz-handle { display: none; }
}
`;
    }

    function attachResize(handle: HTMLElement, instance: WidgetInstance, mode: "w" | "h" | "wh", growsLeft: boolean) {
        handle.addEventListener("pointerdown", event => {
            event.preventDefault();
            const panel = instance.panel;
            try {
                handle.setPointerCapture(event.pointerId);
            } catch {
                /* pointer capture unsupported — drag still works via the handle listeners */
            }
            const rect = panel.getBoundingClientRect();
            const startX = event.clientX;
            const startY = event.clientY;
            const startWidth = rect.width;
            const startHeight = rect.height;
            panel.classList.add("resizing");

            const onMove = (moveEvent: PointerEvent) => {
                if (mode.indexOf("w") !== -1) {
                    const delta = growsLeft ? startX - moveEvent.clientX : moveEvent.clientX - startX;
                    const width = Math.max(MIN_WIDTH, Math.min(window.innerWidth - 40, startWidth + delta));
                    panel.style.setProperty("--cw-width", `${Math.round(width)}px`);
                }
                if (mode.indexOf("h") !== -1) {
                    // Anchored to the bottom, so the panel always grows upward.
                    const height = Math.max(MIN_HEIGHT, Math.min(window.innerHeight - 40, startHeight + (startY - moveEvent.clientY)));
                    panel.style.setProperty("--cw-height", `${Math.round(height)}px`);
                }
            };
            const onUp = () => {
                handle.removeEventListener("pointermove", onMove);
                handle.removeEventListener("pointerup", onUp);
                handle.removeEventListener("pointercancel", onUp);
                try {
                    handle.releasePointerCapture(event.pointerId);
                } catch {
                    /* no-op */
                }
                panel.classList.remove("resizing");
                const finalRect = panel.getBoundingClientRect();
                writeStoredSize(instance.config.chatbotId, Math.round(finalRect.width), Math.round(finalRect.height));
            };
            handle.addEventListener("pointermove", onMove);
            handle.addEventListener("pointerup", onUp);
            handle.addEventListener("pointercancel", onUp);
        });
    }

    function addResizeHandles(instance: WidgetInstance) {
        const growsLeft = instance.config.position !== "left";
        const handles: Array<[string, "w" | "h" | "wh"]> = [
            ["rz-handle rz-top", "h"],
            ["rz-handle rz-side", "w"],
            ["rz-handle rz-corner", "wh"]
        ];
        for (const [className, mode] of handles) {
            const handle = document.createElement("div");
            handle.className = className;
            attachResize(handle, instance, mode, growsLeft);
            instance.panel.appendChild(handle);
        }
    }

    function createWidget(rawConfig: ChatbotWidgetConfig): WidgetInstance {
        const config = {
            ...rawConfig,
            position: rawConfig.position === "left" ? ("left" as const) : ("right" as const),
            // Precedence already resolved in startWidget: data-primary-color > backend theme color >
            // generic default. This guard just covers the programmatic path.
            primaryColor: rawConfig.primaryColor || DEFAULT_PRIMARY_COLOR
        };

        const host = document.createElement("div");
        host.id = HOST_ELEMENT_ID;
        document.body.appendChild(host);
        const shadow = host.attachShadow({ mode: "open" });

        const style = document.createElement("style");
        style.textContent = styleSheet(config.primaryColor, config.launcherIconColor || DEFAULT_ICON_COLOR, config.position);
        shadow.appendChild(style);

        const panel = document.createElement("div");
        panel.className = "panel";
        panel.setAttribute("role", "dialog");
        panel.setAttribute("aria-label", config.launcherText || "Chat");
        shadow.appendChild(panel);

        const launcher = document.createElement("button");
        launcher.className = "launcher";
        launcher.type = "button";
        launcher.setAttribute("aria-label", config.launcherText || "Open chat");
        launcher.innerHTML = CHAT_ICON;
        launcher.addEventListener("click", () => toggle());
        shadow.appendChild(launcher);

        const instance: WidgetInstance = { config, shadow, launcher, panel, iframe: null, isOpen: false };

        // Restore a previously dragged size, then add the resize handles.
        const storedSize = readStoredSize(config.chatbotId);
        if (storedSize) {
            panel.style.setProperty("--cw-width", `${storedSize.width}px`);
            panel.style.setProperty("--cw-height", `${storedSize.height}px`);
        }
        addResizeHandles(instance);

        // Open automatically when explicitly requested, when an open() arrived during async init,
        // or when the panel was open on the previous page (so the chat follows the user across
        // same-site navigation/new tabs).
        if (config.autoOpen || pendingOpen || readStoredOpen(config.chatbotId)) {
            // Defer so the launcher paints first.
            window.setTimeout(() => openPanel(instance), 0);
        }
        return instance;
    }

    function ensureIframe(instance: WidgetInstance): HTMLIFrameElement {
        if (instance.iframe) {
            return instance.iframe;
        }
        const iframe = document.createElement("iframe");
        iframe.src = buildIframeSrc(instance.config);
        iframe.setAttribute("allow", "microphone; clipboard-write; autoplay");
        iframe.setAttribute("title", instance.config.launcherText || "Chat");
        instance.panel.appendChild(iframe);
        instance.iframe = iframe;
        return iframe;
    }

    function openPanel(instance: WidgetInstance) {
        ensureIframe(instance);
        instance.isOpen = true;
        instance.panel.classList.add("open");
        instance.launcher.innerHTML = CLOSE_ICON;
        instance.launcher.setAttribute("aria-label", "Close chat");
        writeStoredOpen(instance.config.chatbotId, true);
    }

    function closePanel(instance: WidgetInstance) {
        instance.isOpen = false;
        instance.panel.classList.remove("open");
        instance.launcher.innerHTML = CHAT_ICON;
        instance.launcher.setAttribute("aria-label", instance.config.launcherText || "Open chat");
        writeStoredOpen(instance.config.chatbotId, false);
    }

    function toggle() {
        if (!widget) {
            return;
        }
        if (widget.isOpen) {
            closePanel(widget);
        } else {
            openPanel(widget);
        }
    }

    // --- public API ---------------------------------------------------------

    function init(config: ChatbotWidgetConfig) {
        if (!config || !config.chatbotId) {
            // eslint-disable-next-line no-console
            console.error("[chatbot] init() requires a chatbotId");
            return;
        }
        if (widget || initStarted) {
            return; // already initialised (or initialising); ignore re-init
        }
        initStarted = true;
        void startWidget(config);
    }

    async function startWidget(config: ChatbotWidgetConfig) {
        const remote = await fetchRemoteConfig(config.chatbotId);
        if (!remote) {
            // Unknown public ID or fetch failure — show nothing, and allow a later retry.
            initStarted = false;
            return;
        }
        const rules = Array.isArray(remote.rules) ? remote.rules : [];
        // Domain whitelist enforcement: if this page isn't allowed, the widget must not be displayed.
        if (!isUrlAllowed(rules, window.location.href)) {
            return;
        }
        const resolvedConfig: ChatbotWidgetConfig = {
            ...config,
            // Precedence: explicit data-primary-color > the bot's theme color from config > default.
            primaryColor: config.primaryColor || remote.primaryColor || DEFAULT_PRIMARY_COLOR,
            // Same precedence for the icon color; falsy stays undefined so createWidget applies white.
            launcherIconColor: config.launcherIconColor || remote.launcherIconColor || undefined
        };
        const start = () => {
            if (!widget) {
                widget = createWidget(resolvedConfig);
            }
        };
        if (document.body) {
            start();
        } else {
            window.addEventListener("DOMContentLoaded", start, { once: true });
        }
    }

    function open() {
        if (widget) {
            openPanel(widget);
        } else {
            // Remember it so the panel opens as soon as async init finishes.
            pendingOpen = true;
        }
    }

    function close() {
        pendingOpen = false;
        if (widget) {
            closePanel(widget);
        }
    }

    // Bridge messages from the chat iframe (origin-checked).
    window.addEventListener("message", event => {
        if (event.origin !== backendOrigin) {
            return;
        }
        const data = event.data;
        if (!data || typeof data !== "object") {
            return;
        }
        switch (data.type) {
            case "chatbot:ready":
                if (widget?.iframe?.contentWindow) {
                    widget.iframe.contentWindow.postMessage(
                        {
                            type: "chatbot:host-init",
                            config: {
                                primaryColor: widget.config.primaryColor,
                                launcherText: widget.config.launcherText,
                                locale: widget.config.locale
                            }
                        },
                        backendOrigin
                    );
                }
                break;
            case "chatbot:close":
                close();
                break;
            default:
                break;
        }
    });

    // Drain any queued commands pushed by the snippet stub before this script executed, then
    // install the real implementation.
    const queued = window.chatbot && Array.isArray(window.chatbot.q) ? window.chatbot.q.slice() : [];
    const api: ChatbotWidgetApi = { init, open, close };
    window.chatbot = api;
    for (const [command, arg] of queued) {
        if (command === "init" && arg) {
            init(arg);
        } else if (command === "open") {
            open();
        } else if (command === "close") {
            close();
        }
    }

    // Auto-init from data attributes (the race-free single-line snippet).
    const scriptConfig = readConfigFromScript();
    if (scriptConfig) {
        init(scriptConfig);
    }
})();

export {};
