/**
 * Embeddable chatbot widget loader.
 *
 * A tiny, dependency-free script (no React/Fluent) that website owners embed with a single
 * <script> tag. It injects a floating launcher button and, on first open, a cross-origin iframe
 * that loads the existing chatbot page at `<origin>/<chatbotId>?embed=1`. All chat traffic stays
 * inside that iframe (same-origin to the backend), so no CORS is required on the host site.
 *
 * Usage (primary, race-free):
 *   <script async src="https://chat.nerilio.ai/widget.js" data-chatbot-id="lemon"></script>
 *
 * Usage (programmatic, e.g. SPAs):
 *   <script async src="https://chat.nerilio.ai/widget.js"></script>
 *   <script>
 *     window.chatbot = window.chatbot || { q: [], init(o){this.q.push(["init",o])},
 *       open(){this.q.push(["open"])}, close(){this.q.push(["close"])} };
 *     chatbot.init({ chatbotId: "lemon" });
 *   </script>
 */

// Per-bot brand colors (single source of truth shared with the React app). Used so the launcher
// bubble matches the embedded bot's theme out of the box, without each site setting a color.
import { chatbotThemes } from "../chatbots/shared/theme/chatbotThemes";

interface ChatbotWidgetConfig {
    chatbotId: string;
    position?: "right" | "left";
    primaryColor?: string;
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
        return `${backendOrigin}/${encodeURIComponent(config.chatbotId)}?${params.toString()}`;
    }

    const CHAT_ICON =
        '<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>';
    const CLOSE_ICON =
        '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';

    function styleSheet(primaryColor: string, position: "right" | "left"): string {
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
    background: ${primaryColor}; color: #fff; display: flex; align-items: center; justify-content: center;
    box-shadow: 0 6px 24px rgba(0,0,0,0.28); transition: transform .15s ease, box-shadow .15s ease;
}
.launcher:hover { transform: scale(1.06); box-shadow: 0 10px 28px rgba(0,0,0,0.34); }
.launcher:focus-visible { outline: 3px solid rgba(255,255,255,0.6); outline-offset: 2px; }
.panel {
    position: fixed; bottom: 92px; ${side}: 20px; z-index: 2147483000;
    width: var(--cw-width, 400px); height: var(--cw-height, 640px);
    max-height: calc(100vh - 112px); max-width: calc(100vw - 40px);
    border-radius: 16px; overflow: hidden; background: #fff;
    box-shadow: 0 12px 48px rgba(0,0,0,0.30); border: 1px solid rgba(0,0,0,0.08);
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
            // Precedence: explicit data-primary-color > the bot's own theme color > generic default.
            primaryColor: rawConfig.primaryColor || chatbotThemes[rawConfig.chatbotId]?.primary || DEFAULT_PRIMARY_COLOR
        };

        const host = document.createElement("div");
        host.id = HOST_ELEMENT_ID;
        document.body.appendChild(host);
        const shadow = host.attachShadow({ mode: "open" });

        const style = document.createElement("style");
        style.textContent = styleSheet(config.primaryColor, config.position);
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

        if (config.autoOpen) {
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
    }

    function closePanel(instance: WidgetInstance) {
        instance.isOpen = false;
        instance.panel.classList.remove("open");
        instance.launcher.innerHTML = CHAT_ICON;
        instance.launcher.setAttribute("aria-label", instance.config.launcherText || "Open chat");
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
        if (widget) {
            return; // already initialised; ignore re-init
        }
        const start = () => {
            widget = createWidget(config);
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
        }
    }

    function close() {
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
