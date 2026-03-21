import * as SpeechSDK from "microsoft-cognitiveservices-speech-sdk";
import { getSpeechTokenApi, SpeechTokenResponse } from "../api";

let cachedSpeechToken: SpeechTokenResponse | null = null;
let pendingSpeechTokenRequest: Promise<SpeechTokenResponse> | null = null;

const SPEECH_TOKEN_REFRESH_BUFFER_MS = 2 * 60 * 1000;

const preferredStreamingFormats: {
    mimeType: string;
    outputFormat: SpeechSDK.SpeechSynthesisOutputFormat;
}[] = [
    {
        mimeType: "audio/mpeg",
        outputFormat: SpeechSDK.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3
    },
    {
        mimeType: "audio/webm; codecs=opus",
        outputFormat: SpeechSDK.SpeechSynthesisOutputFormat.Webm24Khz16BitMonoOpus
    },
    {
        mimeType: "audio/ogg",
        outputFormat: SpeechSDK.SpeechSynthesisOutputFormat.Ogg24Khz16BitMonoOpus
    }
];

const shouldRefreshSpeechToken = (speechToken: SpeechTokenResponse) => {
    return speechToken.expiresAt * 1000 <= Date.now() + SPEECH_TOKEN_REFRESH_BUFFER_MS;
};

export const getSpeechToken = async (forceRefresh: boolean = false): Promise<SpeechTokenResponse> => {
    if (!forceRefresh && cachedSpeechToken && !shouldRefreshSpeechToken(cachedSpeechToken)) {
        return cachedSpeechToken;
    }

    if (!forceRefresh && pendingSpeechTokenRequest) {
        return pendingSpeechTokenRequest;
    }

    pendingSpeechTokenRequest = getSpeechTokenApi()
        .then(speechToken => {
            cachedSpeechToken = speechToken;
            return speechToken;
        })
        .finally(() => {
            pendingSpeechTokenRequest = null;
        });

    return pendingSpeechTokenRequest;
};

export const invalidateSpeechToken = () => {
    cachedSpeechToken = null;
};

export const isSpeechAuthFailure = (error: string) => {
    const normalizedError = error.toLowerCase();
    return (
        normalizedError.includes("authentication failed") ||
        normalizedError.includes("no valid credentials") ||
        normalizedError.includes("unable to contact server") ||
        normalizedError.includes("statuscode: 1006")
    );
};

export const getPreferredSpeechSynthesisOutputFormat = (): SpeechSDK.SpeechSynthesisOutputFormat => {
    if (typeof MediaSource === "undefined") {
        return SpeechSDK.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3;
    }

    const supportedStreamingFormat = preferredStreamingFormats.find(format => MediaSource.isTypeSupported(format.mimeType));
    if (supportedStreamingFormat) {
        return supportedStreamingFormat.outputFormat;
    }

    return SpeechSDK.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3;
};
