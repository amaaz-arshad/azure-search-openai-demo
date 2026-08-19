import { useCallback, useEffect, useRef, useState } from "react";

import {
    AVATAR_GENERATING_TIMEOUT_MS,
    AVATAR_IDLE_TIMEOUT_MS,
    AVATAR_SPEAKING_TIMEOUT_MS,
    AvatarSession,
    AvatarSessionStatus
} from "./avatarSession";
import { ConversationListener } from "./conversationListener";
import { getSpeechToken } from "../azureSpeech";

/**
 * Owns the lifecycle of a real-time avatar session for a React tree.
 *
 * The service bills per second the session is open regardless of whether the avatar speaks, so
 * every path that could leave one running is closed here: idle timeout, tab hidden, unmount, and
 * page unload. The idle timer is the important one — a user who opens the avatar and then reads
 * quietly is otherwise billed the whole time.
 *
 * With `conversation` supplied it also runs hands-free mode, alternating the microphone and the
 * avatar's voice (see `reconcileListening`).
 */
export interface UseAvatarSessionOptions {
    conversation?: {
        /** Recognition locale, e.g. "de-DE". */
        locale: string;
        /** Called with a finished user utterance; wire this to the chat's send function. */
        onUtterance: (text: string) => void;
        /** True while the app is generating an answer — the microphone stays shut. */
        busy: boolean;
    };
}

export interface UseAvatarSessionResult {
    status: AvatarSessionStatus;
    isActive: boolean;
    isSpeaking: boolean;
    isListening: boolean;
    /** Connectivity is wobbling and the session is inside its recovery grace window. */
    isReconnecting: boolean;
    interimTranscript: string;
    error: string | null;
    videoRef: React.RefObject<HTMLVideoElement>;
    audioRef: React.RefObject<HTMLAudioElement>;
    start: () => Promise<void>;
    stop: () => void;
    speak: (text: string) => void;
    stopSpeaking: () => void;
}

export function useAvatarSession(options: UseAvatarSessionOptions = {}): UseAvatarSessionResult {
    const [status, setStatus] = useState<AvatarSessionStatus>("idle");
    const [error, setError] = useState<string | null>(null);
    const [isSpeaking, setIsSpeaking] = useState(false);
    const [isListening, setIsListening] = useState(false);
    const [isReconnecting, setIsReconnecting] = useState(false);
    const [interimTranscript, setInterimTranscript] = useState("");
    // State, not just the ref below: the reconciling effect has to re-run when the listener comes
    // into existence. The listener is built after `session.start()` resolves, which is *after*
    // the status has already flipped to "ready" — so without this the effect would fire once with
    // a null ref, bail out, and never open the microphone at all.
    const [listenerReady, setListenerReady] = useState(false);

    const sessionRef = useRef<AvatarSession | null>(null);
    const listenerRef = useRef<ConversationListener | null>(null);
    const videoRef = useRef<HTMLVideoElement>(null);
    const audioRef = useRef<HTMLAudioElement>(null);
    const idleTimerRef = useRef<number | null>(null);

    const conversation = options.conversation;
    // Held in a ref so a new inline callback on every render doesn't tear down the recognizer.
    const onUtteranceRef = useRef(conversation?.onUtterance);
    onUtteranceRef.current = conversation?.onUtterance;

    const clearIdleTimer = useCallback(() => {
        if (idleTimerRef.current !== null) {
            window.clearTimeout(idleTimerRef.current);
            idleTimerRef.current = null;
        }
    }, []);

    const stop = useCallback(() => {
        clearIdleTimer();
        listenerRef.current?.close();
        listenerRef.current = null;
        setListenerReady(false);
        sessionRef.current?.close();
        sessionRef.current = null;
        setIsListening(false);
        setIsSpeaking(false);
        setIsReconnecting(false);
        setInterimTranscript("");
        setStatus("idle");
    }, [clearIdleTimer]);

    const armIdleTimer = useCallback(
        (durationMs: number = AVATAR_IDLE_TIMEOUT_MS) => {
            clearIdleTimer();
            idleTimerRef.current = window.setTimeout(() => {
                stop();
            }, durationMs);
        },
        [clearIdleTimer, stop]
    );

    const start = useCallback(async () => {
        if (sessionRef.current) {
            return;
        }
        setError(null);

        const session = new AvatarSession({
            onStatusChange: setStatus,
            onError: message => setError(message),
            onSpeakingChange: setIsSpeaking,
            onConnectionUnstable: setIsReconnecting,
            onDisconnected: () => {
                // A dropped peer connection cannot be revived on the same synthesizer. This now
                // fires only after the recovery grace window has elapsed without healing, or on a
                // terminal `failed` — not on the first transient blip.
                stop();
            }
        });
        sessionRef.current = session;

        try {
            if (!videoRef.current || !audioRef.current) {
                throw new Error("Avatar media elements are not mounted");
            }
            await session.start(videoRef.current, audioRef.current);

            if (conversation && sessionRef.current === session) {
                const getCredentials = async (forceRefresh: boolean) => {
                    // Reuse the token the avatar session already holds — a /speech/token round
                    // trip can take tens of seconds against a local backend, which the user would
                    // experience as the microphone simply not working.
                    const existing = forceRefresh ? null : session.credentials;
                    if (existing) {
                        return existing;
                    }
                    const refreshed = await getSpeechToken(true);
                    return { token: refreshed.token, region: refreshed.region };
                };

                listenerRef.current = new ConversationListener(conversation.locale, getCredentials, {
                    onUtterance: text => {
                        // Close the microphone immediately rather than waiting for `busy` to
                        // propagate, so the tail of this turn can't start a second one.
                        void listenerRef.current?.stop();
                        armIdleTimer();
                        onUtteranceRef.current?.(text);
                    },
                    onListeningChange: setIsListening,
                    onInterimTranscript: setInterimTranscript,
                    onError: message => setError(message)
                });
                setListenerReady(true);
            }

            armIdleTimer();
        } catch (caught) {
            const message = caught instanceof Error ? caught.message : String(caught);
            // Tear down FIRST: close() reports "idle", so setting the error status before it would
            // let that "idle" win the batched update — hiding the panel and swallowing the error.
            session.close();
            sessionRef.current = null;
            setError(message);
            setStatus("error");
        }
    }, [armIdleTimer, conversation, stop]);

    const speak = useCallback(
        (text: string) => {
            if (!sessionRef.current) {
                return;
            }
            armIdleTimer();
            void sessionRef.current.speak(text);
        },
        [armIdleTimer]
    );

    const stopSpeaking = useCallback(() => {
        void sessionRef.current?.stopSpeaking();
        setIsSpeaking(false);
    }, []);

    /**
     * The conversation state machine, expressed as one reconciliation rather than a chain of
     * events: listen only when the session is up, the avatar is silent, and no answer is being
     * generated. Any of those going false closes the microphone — which is what makes the mode
     * half-duplex and stops the recognizer hearing the avatar through the speakers.
     */
    const conversationBusy = conversation?.busy ?? false;
    const conversationEnabled = Boolean(conversation);
    useEffect(() => {
        const listener = listenerRef.current;
        if (!listener) {
            return;
        }
        const shouldListen = conversationEnabled && status === "ready" && !isSpeaking && !conversationBusy;
        if (shouldListen) {
            void listener.start();
        } else {
            void listener.stop();
        }
    }, [conversationEnabled, listenerReady, status, isSpeaking, conversationBusy]);

    /**
     * Generating an answer and speaking it are activity, not idleness.
     *
     * The short idle timeout exists to stop billing for a user who wandered off, so it must only
     * count down while we are actually waiting for that user. Left running through a slow answer
     * it closes the session in the moment before the avatar was about to speak — the user asks a
     * question and the avatar silently disappears (observed against the local backend, whose
     * answers outlast the timeout).
     *
     * A generous timeout rather than none at all, so a request that never resolves still cannot
     * hold a billing session open until the service's own 30-minute cap.
     */
    useEffect(() => {
        if (!sessionRef.current) {
            return;
        }
        // Speaking is checked first: media is flowing, so the service is not idle and only the
        // length of the utterance bounds this. Generating is the case that must stay under the
        // service's own 5-minute idle cutoff.
        const nextTimeout = isSpeaking
            ? AVATAR_SPEAKING_TIMEOUT_MS
            : conversationBusy
              ? AVATAR_GENERATING_TIMEOUT_MS
              : AVATAR_IDLE_TIMEOUT_MS;
        armIdleTimer(nextTimeout);
    }, [conversationBusy, isSpeaking, armIdleTimer]);

    // Close when the tab is hidden: a backgrounded tab keeps billing otherwise.
    useEffect(() => {
        const handleVisibilityChange = () => {
            if (document.visibilityState === "hidden") {
                stop();
            }
        };
        const handleUnload = () => {
            stop();
        };

        document.addEventListener("visibilitychange", handleVisibilityChange);
        window.addEventListener("beforeunload", handleUnload);
        return () => {
            document.removeEventListener("visibilitychange", handleVisibilityChange);
            window.removeEventListener("beforeunload", handleUnload);
        };
    }, [stop]);

    // Final guard: never leave a session or an open microphone past unmount.
    useEffect(() => {
        return () => {
            clearIdleTimer();
            listenerRef.current?.close();
            listenerRef.current = null;
            sessionRef.current?.close();
            sessionRef.current = null;
        };
    }, [clearIdleTimer]);

    return {
        status,
        isActive: status !== "idle" && status !== "error",
        isSpeaking,
        isListening,
        isReconnecting,
        interimTranscript,
        error,
        videoRef,
        audioRef,
        start,
        stop,
        speak,
        stopSpeaking
    };
}
