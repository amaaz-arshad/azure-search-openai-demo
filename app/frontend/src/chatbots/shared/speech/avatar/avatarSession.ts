import * as SpeechSDK from "microsoft-cognitiveservices-speech-sdk";

import { AvatarTokenResponse, getAvatarToken } from "../azureSpeech";

/**
 * Wraps one Azure real-time text-to-speech avatar session.
 *
 * The service bills per second of wall-clock session time — whether or not the avatar is speaking
 * — so the lifecycle here is intentionally explicit: a session is created only by a user action
 * and every exit path must call `close()`. See `useAvatarSession` for the idle/visibility guards
 * that enforce that.
 */

/** Below the service's own 5-minute idle disconnect, so the client always closes first. */
export const AVATAR_IDLE_TIMEOUT_MS = 90_000;

/**
 * Ceiling while an answer is generating or the avatar is speaking.
 *
 * Those are activity, not idleness, so the short timeout must not apply — but a request that never
 * resolves still must not hold a billing session open until the service's 30-minute cap.
 */
export const AVATAR_BUSY_TIMEOUT_MS = 300_000;

/** 1080p rather than the SDK's 4K default: the panel is small and 4K costs more per minute. */
const AVATAR_VIDEO_WIDTH = 1920;
const AVATAR_VIDEO_HEIGHT = 1080;

export type AvatarSessionStatus = "idle" | "connecting" | "ready" | "speaking" | "error";

export interface AvatarSessionCallbacks {
    onStatusChange?: (status: AvatarSessionStatus) => void;
    onError?: (message: string) => void;
    /** Fires when the peer connection drops on its own (network, or a service-side timeout). */
    onDisconnected?: () => void;
    /**
     * Fires when the avatar starts and stops talking, from the service's own avatar events.
     * This is what drives half-duplex conversation mode: the microphone must be closed for
     * exactly as long as the avatar's voice is coming out of the speakers.
     */
    onSpeakingChange?: (speaking: boolean) => void;
}

/**
 * Read the avatar event's name.
 *
 * `AvatarEventArgs.type` looks like the right property but is **always `undefined`** in SDK
 * 1.48: the constructor assigns only `privOffset` and `privDescription` and never `privType`,
 * so the getter returns nothing. The event name actually arrives in `description`. Both are read
 * here so this keeps working if a later SDK starts populating `type`.
 */
const avatarEventName = (event: SpeechSDK.AvatarEventArgs): string =>
    String(event.description ?? "") || String((event as unknown as { type?: string }).type ?? "");

/**
 * Classify an avatar event into "the avatar started talking" / "it stopped".
 *
 * **The SDK's `AvatarEventTypes` enum does not match what the service sends.** It declares
 * `SwitchedToSpeaking` / `SwitchedToIdle`, but the wire names observed from a live session are
 * `SwitchToSpeaking` / `SwitchToIdle` (no "ed"), alongside `WebrtcConnected`, `TurnStart`,
 * `TurnEnd` and free-form `Debug info: …` strings. Matching the enum spelling silently never
 * fires — which leaves the microphone open while the avatar talks, i.e. it transcribes the avatar
 * and the bot answers itself. Both spellings are therefore accepted.
 *
 * `TurnEnd` counts as "stopped" because a live session emitted no trailing `SwitchToIdle` after
 * speech: its timing matched the end of playback (2.694s wall-clock after `SwitchToSpeaking`,
 * against a 2.65s span in the event offsets), so it is the dependable end-of-speech signal.
 *
 * `Debug info: …` payloads are ignored explicitly — they are prose and could otherwise collide
 * with the substring matching.
 */
const classifyAvatarEvent = (name: string): "speaking" | "idle" | null => {
    const normalized = name.toLowerCase();
    if (normalized.startsWith("debug")) {
        return null;
    }
    if (normalized === "switchtospeaking" || normalized === "switchedtospeaking") {
        return "speaking";
    }
    if (normalized === "switchtoidle" || normalized === "switchedtoidle" || normalized === "turnend") {
        return "idle";
    }
    return null;
};

const escapeSsml = (text: string): string =>
    text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&apos;");

/**
 * Build the SSML for one utterance.
 *
 * SSML rather than speakTextAsync because the voice has to be named per utterance (the avatar
 * voice is independent of the deployment-wide speak-answer voice) and because
 * `leadingsilence-exact` removes the ~half-second of dead air the service otherwise prepends,
 * which is very visible when the avatar is already on screen and idle.
 */
export const buildAvatarSsml = (text: string, voice: string): string => {
    const locale = voice.split("-").slice(0, 2).join("-") || "de-AT";
    return (
        `<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' ` +
        `xmlns:mstts='http://www.w3.org/2001/mstts' xml:lang='${locale}'>` +
        `<voice name='${voice}'>` +
        `<mstts:leadingsilence-exact value='0'/>` +
        `${escapeSsml(text)}` +
        `</voice></speak>`
    );
};

export class AvatarSession {
    private synthesizer: SpeechSDK.AvatarSynthesizer | null = null;
    private peerConnection: RTCPeerConnection | null = null;
    private callbacks: AvatarSessionCallbacks;
    private closed = false;
    private tokenResponse: AvatarTokenResponse | null = null;

    constructor(callbacks: AvatarSessionCallbacks = {}) {
        this.callbacks = callbacks;
    }

    private setStatus(status: AvatarSessionStatus) {
        if (!this.closed || status === "idle") {
            this.callbacks.onStatusChange?.(status);
        }
    }

    get voice(): string {
        return this.tokenResponse?.voice ?? "";
    }

    /**
     * The Speech credentials this session is already holding.
     *
     * Conversation mode's recognizer needs exactly the same authorization token and region, so it
     * reuses these instead of calling /speech/token again. That round trip is not free: the token
     * is minted from the app's credential, which on a local backend shells out to the Azure
     * Developer CLI and can take tens of seconds — long enough that the microphone would appear
     * to be broken for the first half-minute of every session.
     */
    get credentials(): { token: string; region: string } | null {
        const token = this.tokenResponse;
        if (!token) {
            return null;
        }
        // Deliberately NOT gated on `expiresAt`. That value cannot be trusted: a locally run
        // backend authenticates with AzureDeveloperCliCredential, which hands back tokens stamped
        // with an expiry already in the past — an expiry check here rejected a token the live
        // avatar session was, at that very moment, successfully authenticated with, and fell back
        // to a /speech/token call that takes tens of seconds. Validity is proven by the session
        // being up, and the service caps a session at 30 minutes, comfortably inside a real
        // token's lifetime. `ConversationListener` retries with a fresh token if it is ever wrong.
        return { token: token.token, region: token.region };
    }

    /**
     * Open the session and attach the media tracks.
     *
     * `ontrack` fires twice — once for video, once for audio — so both elements are bound here
     * rather than relying on a single stream.
     */
    async start(videoElement: HTMLVideoElement, audioElement: HTMLAudioElement): Promise<void> {
        this.setStatus("connecting");

        const token = await getAvatarToken();
        this.tokenResponse = token;

        if (this.closed) {
            return;
        }

        const peerConnection = new RTCPeerConnection({
            iceServers: token.iceServers.map(server => ({
                urls: server.urls,
                username: server.username,
                credential: server.credential
            }))
        });

        peerConnection.ontrack = event => {
            if (event.track.kind === "video") {
                videoElement.srcObject = event.streams[0];
            } else if (event.track.kind === "audio") {
                audioElement.srcObject = event.streams[0];
            }
        };

        // sendrecv on both, per the avatar samples: the service rejects a recvonly offer.
        peerConnection.addTransceiver("video", { direction: "sendrecv" });
        peerConnection.addTransceiver("audio", { direction: "sendrecv" });

        peerConnection.oniceconnectionstatechange = () => {
            if (this.closed) {
                return;
            }
            if (peerConnection.iceConnectionState === "disconnected" || peerConnection.iceConnectionState === "failed") {
                this.callbacks.onDisconnected?.();
            }
        };

        this.peerConnection = peerConnection;

        const speechConfig = SpeechSDK.SpeechConfig.fromAuthorizationToken(token.token, token.region);
        speechConfig.speechSynthesisVoiceName = token.voice;

        const videoFormat = new SpeechSDK.AvatarVideoFormat();
        videoFormat.width = AVATAR_VIDEO_WIDTH;
        videoFormat.height = AVATAR_VIDEO_HEIGHT;

        const avatarConfig = new SpeechSDK.AvatarConfig(token.character, token.style, videoFormat);
        // Real-time avatar ignores the alpha channel, so a solid colour is the only real option.
        avatarConfig.backgroundColor = "#FFFFFFFF";

        const synthesizer = new SpeechSDK.AvatarSynthesizer(speechConfig, avatarConfig);
        synthesizer.avatarEventReceived = (_sender, event) => {
            if (this.closed) {
                return;
            }
            const classified = classifyAvatarEvent(avatarEventName(event));
            if (classified) {
                this.callbacks.onSpeakingChange?.(classified === "speaking");
            }
        };
        this.synthesizer = synthesizer;

        const result = await synthesizer.startAvatarAsync(peerConnection);
        if (result.reason === SpeechSDK.ResultReason.Canceled) {
            const details = SpeechSDK.CancellationDetails.fromResult(result as SpeechSDK.SpeechSynthesisResult);
            throw new Error(details.errorDetails || "Avatar session could not be started");
        }

        if (this.closed) {
            // The user cancelled while the handshake was in flight; don't leave a billed session open.
            this.close();
            return;
        }

        this.setStatus("ready");
    }

    async speak(text: string): Promise<void> {
        const trimmed = text.trim();
        if (!this.synthesizer || !trimmed || this.closed) {
            return;
        }

        this.setStatus("speaking");
        // Assume speech immediately rather than waiting for the service's SwitchToSpeaking event.
        // The microphone must be shut BEFORE any audio can reach the speakers, and the event
        // arrives ~140ms after the request; closing late would feed the avatar's first syllables
        // straight back into the recognizer.
        this.callbacks.onSpeakingChange?.(true);
        try {
            const result = await this.synthesizer.speakSsmlAsync(buildAvatarSsml(trimmed, this.voice));
            if (result.reason === SpeechSDK.ResultReason.Canceled) {
                const details = SpeechSDK.CancellationDetails.fromResult(result as SpeechSDK.SpeechSynthesisResult);
                this.callbacks.onError?.(details.errorDetails || "Avatar synthesis was canceled");
            }
        } catch (error) {
            this.callbacks.onError?.(error instanceof Error ? error.message : String(error));
        } finally {
            // Backstop for the TurnEnd/SwitchToIdle events: this promise resolved within a
            // millisecond of TurnEnd in a live session, so if the events ever change shape again
            // the microphone still reopens instead of the conversation stalling forever.
            if (!this.closed) {
                this.callbacks.onSpeakingChange?.(false);
                this.setStatus("ready");
            }
        }
    }

    /** Barge-in: drop the queued audio and return the avatar to its idle pose. */
    async stopSpeaking(): Promise<void> {
        if (!this.synthesizer || this.closed) {
            return;
        }
        try {
            await this.synthesizer.stopSpeakingAsync();
        } catch {
            // The session may already be tearing down; nothing to recover here.
        }
        if (!this.closed) {
            this.setStatus("ready");
        }
    }

    /**
     * Tear the session down. Safe to call repeatedly.
     *
     * `stopAvatarAsync()` is documented as equivalent to `close()`, so a session can never be
     * restarted — `useAvatarSession` constructs a fresh AvatarSession instead.
     */
    close(): void {
        // Deliberately NOT an early return when already closed: it always tears down whatever is
        // currently held, and only the status callback is made once. Today `start` cannot leak a
        // session past a cancel (everything between the cancel guard and the peer-connection
        // assignment is synchronous, so a click cannot land in between), but an early return here
        // would silently turn any future await added in that stretch into a live, billing avatar
        // nobody can see. Cheap insurance against the most expensive failure mode this file has.
        const wasClosed = this.closed;
        this.closed = true;

        try {
            this.synthesizer?.close();
        } catch {
            // Ignore teardown races.
        }
        this.synthesizer = null;

        try {
            this.peerConnection?.close();
        } catch {
            // Ignore teardown races.
        }
        this.peerConnection = null;

        if (!wasClosed) {
            // The service can't send a closing SwitchedToIdle once the connection is gone, so
            // clear the speaking flag here — otherwise conversation mode would believe the avatar
            // is still talking and refuse to reopen the microphone.
            this.callbacks.onSpeakingChange?.(false);
            this.callbacks.onStatusChange?.("idle");
        }
    }
}
