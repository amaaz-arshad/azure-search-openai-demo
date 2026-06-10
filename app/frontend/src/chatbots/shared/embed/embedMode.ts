/**
 * Embed mode is signalled by the `?embed=1` query param that the widget loader appends to the
 * iframe URL (`<origin>/<chatbotId>?embed=1`). When active, the chatbot page slims its chrome and
 * opens a postMessage bridge to the host widget (see EmbedBridge).
 */
export function isEmbedMode(): boolean {
    if (typeof window === "undefined") {
        return false;
    }
    return new URLSearchParams(window.location.search).get("embed") === "1";
}
