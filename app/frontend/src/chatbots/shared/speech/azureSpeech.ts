import * as SpeechSDK from "microsoft-cognitiveservices-speech-sdk";

export interface SpeechTokenResponse {
    token: string;
    region: string;
    voice: string;
    expiresAt: number;
}

export interface AvatarIceServer {
    urls: string[];
    username: string;
    credential: string;
}

export interface AvatarTokenResponse {
    token: string;
    region: string;
    voice: string;
    character: string;
    style: string;
    iceServers: AvatarIceServer[];
    expiresAt: number;
}

export type SupportedSpeechLanguages = Record<string, { locale?: string }>;

const SPEECH_TOKEN_REFRESH_BUFFER_SECONDS = 60;
// Keyed by chatbot name because the response carries that bot's `voice`: a bot with its own
// speech_voice must not be served a cached token minted for the deployment default.
const cachedSpeechTokens = new Map<string, SpeechTokenResponse>();

/**
 * Fetch a Speech token, and with it the voice the speak-answer button should use.
 *
 * `chatbotName` is optional and only selects the voice — the deployment-wide
 * AZURE_SPEECH_SERVICE_VOICE is shared by every speech-enabled bot, so a bot that needs a
 * different one declares `speech_voice` in its backend config.py and identifies itself here.
 * Callers that only need the token and region (e.g. speech recognition) can omit it.
 */
export async function getSpeechToken(forceRefresh = false, chatbotName?: string): Promise<SpeechTokenResponse> {
    const cacheKey = chatbotName ?? "";
    const cached = cachedSpeechTokens.get(cacheKey);
    if (!forceRefresh && cached && cached.expiresAt > Date.now() / 1000 + SPEECH_TOKEN_REFRESH_BUFFER_SECONDS) {
        return cached;
    }

    const query = chatbotName ? `?chatbot=${encodeURIComponent(chatbotName)}` : "";
    const response = await fetch(`/speech/token${query}`, {
        method: "GET"
    });

    if (!response.ok) {
        const errorMessage = await response.text();
        throw new Error(errorMessage || `Failed to fetch speech token (${response.status})`);
    }

    const speechToken = (await response.json()) as SpeechTokenResponse;
    cachedSpeechTokens.set(cacheKey, speechToken);
    return speechToken;
}

/**
 * Fetch the credentials for one real-time avatar session.
 *
 * Deliberately NOT cached, unlike getSpeechToken: the ICE/TURN credentials are minted per session
 * and a session is only ever opened by an explicit user action, so a stale cached entry would buy
 * nothing and could fail the WebRTC handshake.
 */
export async function getAvatarToken(): Promise<AvatarTokenResponse> {
    const response = await fetch("/speech/avatar-token", {
        method: "GET"
    });

    if (!response.ok) {
        // The backend reports failures as {"error": "..."}; surface that rather than the raw JSON,
        // which is shown to the user in the avatar panel.
        const body = await response.text();
        let errorMessage = body;
        try {
            const parsed = JSON.parse(body);
            if (parsed && typeof parsed.error === "string") {
                errorMessage = parsed.error;
            }
        } catch {
            // Not JSON — fall back to the raw body.
        }
        throw new Error(errorMessage || `Failed to fetch avatar token (${response.status})`);
    }

    return (await response.json()) as AvatarTokenResponse;
}

export function getSpeechRecognitionLocale(currentLanguage: string, supportedLngs: SupportedSpeechLanguages): string {
    const normalizedLanguage = currentLanguage.toLowerCase();
    const baseLanguage = normalizedLanguage.split("-")[0];

    for (const [languageKey, languageConfig] of Object.entries(supportedLngs)) {
        const normalizedKey = languageKey.toLowerCase();
        const normalizedLocale = languageConfig.locale?.toLowerCase();
        const localeBaseLanguage = normalizedLocale?.split("-")[0];

        if (
            normalizedLanguage === normalizedKey ||
            normalizedLanguage === normalizedLocale ||
            baseLanguage === normalizedKey ||
            baseLanguage === localeBaseLanguage
        ) {
            return languageConfig.locale ?? "en-US";
        }
    }

    return "en-US";
}

const synthesisFormatCandidates: Array<{ mimeType: string; format: SpeechSDK.SpeechSynthesisOutputFormat }> = [
    {
        mimeType: "audio/mpeg",
        format: SpeechSDK.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3
    },
    {
        mimeType: 'audio/webm; codecs="opus"',
        format: SpeechSDK.SpeechSynthesisOutputFormat.Webm16Khz16BitMonoOpus
    },
    {
        mimeType: 'audio/ogg; codecs="opus"',
        format: SpeechSDK.SpeechSynthesisOutputFormat.Ogg16Khz16BitMonoOpus
    }
];

export function getPreferredSpeechSynthesisOutputFormat(): SpeechSDK.SpeechSynthesisOutputFormat {
    const mediaSource = typeof window === "undefined" ? undefined : window.MediaSource;
    if (!mediaSource || typeof mediaSource.isTypeSupported !== "function") {
        return SpeechSDK.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3;
    }

    const supportedFormat = synthesisFormatCandidates.find(candidate => mediaSource.isTypeSupported(candidate.mimeType));
    return supportedFormat?.format ?? SpeechSDK.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3;
}
