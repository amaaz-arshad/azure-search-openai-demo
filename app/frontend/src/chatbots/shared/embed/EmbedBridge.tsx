import { useEffect } from "react";

/**
 * Mounted once on a chatbot page when `?embed=1` is active. It announces readiness to the host
 * widget loader (`chatbot:ready`), which lets the loader send `chatbot:host-init`.
 *
 * It renders nothing: closing the panel is handled entirely by the host launcher button (which
 * toggles to a close icon and stays visible on every screen size), so the widget never injects
 * chrome that could overlap the bot's own header controls.
 *
 * The host loader verifies `event.origin` before acting, so posting to the parent with "*" only
 * leaks this non-sensitive control signal.
 */
function postToHost(type: string) {
    try {
        window.parent?.postMessage({ type }, "*");
    } catch {
        /* parent without postMessage access — nothing to do */
    }
}

export function EmbedBridge() {
    useEffect(() => {
        postToHost("chatbot:ready");
    }, []);

    return null;
}
