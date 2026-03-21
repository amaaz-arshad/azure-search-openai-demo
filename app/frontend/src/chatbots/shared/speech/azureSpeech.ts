import * as SpeechSDK from "microsoft-cognitiveservices-speech-sdk";

export interface SpeechTokenResponse {
    token: string;
    region: string;
    voice: string;
    expiresAt: number;
}

export type SupportedSpeechLanguages = Record<string, { locale?: string }>;

const SPEECH_TOKEN_REFRESH_BUFFER_SECONDS = 60;
let cachedSpeechToken: SpeechTokenResponse | null = null;

export async function getSpeechToken(forceRefresh = false): Promise<SpeechTokenResponse> {
    if (!forceRefresh && cachedSpeechToken && cachedSpeechToken.expiresAt > Date.now() / 1000 + SPEECH_TOKEN_REFRESH_BUFFER_SECONDS) {
        return cachedSpeechToken;
    }

    const response = await fetch("/speech/token", {
        method: "GET"
    });

    if (!response.ok) {
        const errorMessage = await response.text();
        throw new Error(errorMessage || `Failed to fetch speech token (${response.status})`);
    }

    cachedSpeechToken = (await response.json()) as SpeechTokenResponse;
    return cachedSpeechToken;
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
