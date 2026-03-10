import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { IconButton } from "@fluentui/react";
import * as SpeechSDK from "microsoft-cognitiveservices-speech-sdk";

let activePlaybackOwner: symbol | null = null;
let activePlaybackStop: (() => void) | null = null;

interface Props {
    answer: string;
    isStreaming: boolean;
}

export const SpeechOutputAzure = ({ answer, isStreaming }: Props) => {
    const [isLoading, setIsLoading] = useState(false);
    const [isPlaying, setIsPlaying] = useState(false);
    const instanceIdRef = useRef(Symbol("SpeechOutputAzure"));
    const synthesizerRef = useRef<SpeechSDK.SpeechSynthesizer | null>(null);
    const playerRef = useRef<SpeechSDK.SpeakerAudioDestination | null>(null);
    const playbackFallbackTimerRef = useRef<number | null>(null);
    const { t } = useTranslation();

    const clearPlaybackFallbackTimer = () => {
        if (playbackFallbackTimerRef.current !== null) {
            window.clearTimeout(playbackFallbackTimerRef.current);
            playbackFallbackTimerRef.current = null;
        }
    };

    const closeSynthesizer = () => {
        if (synthesizerRef.current) {
            synthesizerRef.current.close();
            synthesizerRef.current = null;
        }
    };

    const stopPlayerAudio = () => {
        if (!playerRef.current) return;
        try {
            playerRef.current.pause();
        } catch {
            // Ignore pause errors from browser/media state transitions.
        }
        try {
            const audio = playerRef.current.internalAudio;
            audio.pause();
            audio.currentTime = 0;
            audio.removeAttribute("src");
            audio.load();
        } catch {
            // Ignore direct element-stop errors; close() will still run.
        }
    };

    const closePlayer = () => {
        if (playerRef.current) {
            playerRef.current.onAudioStart = () => undefined;
            playerRef.current.onAudioEnd = () => undefined;
            playerRef.current.close();
            playerRef.current = null;
        }
    };

    const releaseActivePlaybackIfOwned = () => {
        if (activePlaybackOwner === instanceIdRef.current) {
            activePlaybackOwner = null;
            activePlaybackStop = null;
        }
    };

    const finishPlayback = (forceStopAudio: boolean = false) => {
        clearPlaybackFallbackTimer();
        if (forceStopAudio) {
            stopPlayerAudio();
        }
        closeSynthesizer();
        closePlayer();
        releaseActivePlaybackIfOwned();
        setIsPlaying(false);
        setIsLoading(false);
    };

    const handleStop = () => {
        if (!synthesizerRef.current && !playerRef.current) return;
        finishPlayback(true);
    };

    const handlePlay = () => {
        if (!answer) return alert("Enter text to speak");
        setIsLoading(true);
        setIsPlaying(true);

        // Configure speech
        const sdkSpeechConfig = SpeechSDK.SpeechConfig.fromSubscription("8ca3a8c2671046c9849d763655670358", "swedencentral");
        sdkSpeechConfig.speechSynthesisVoiceName = "de-DE-Florian:DragonHDLatestNeural";

        if (activePlaybackOwner !== instanceIdRef.current && activePlaybackStop) {
            activePlaybackStop();
        }
        clearPlaybackFallbackTimer();
        closeSynthesizer();
        closePlayer();
        releaseActivePlaybackIfOwned();

        const player = new SpeechSDK.SpeakerAudioDestination();
        player.onAudioStart = () => {
            setIsLoading(false);
            setIsPlaying(true);
        };
        player.onAudioEnd = () => {
            finishPlayback();
        };
        playerRef.current = player;

        // Use browser audio with explicit player hooks so we can track real playback end.
        const audioConfig = SpeechSDK.AudioConfig.fromSpeakerOutput(player);

        const synthesizer = new SpeechSDK.SpeechSynthesizer(sdkSpeechConfig, audioConfig);
        synthesizerRef.current = synthesizer;
        activePlaybackOwner = instanceIdRef.current;
        activePlaybackStop = () => {
            finishPlayback(true);
        };

        synthesizer.speakTextAsync(
            answer,
            (result: SpeechSDK.SpeechSynthesisResult) => {
                if (result.reason === SpeechSDK.ResultReason.SynthesizingAudioCompleted) {
                    const sdkDurationMs = result.audioDuration > 0 ? result.audioDuration / 10000 : 0;
                    const estimatedDurationMs = Math.max(1500, answer.length * 70);
                    const totalDurationMs = sdkDurationMs > 0 ? sdkDurationMs : estimatedDurationMs;
                    const currentTimeMs = playerRef.current ? Math.max(0, playerRef.current.currentTime * 1000) : 0;
                    // This timer is only a fallback when onAudioEnd doesn't fire.
                    const remainingMs = Math.max(0, totalDurationMs - currentTimeMs + 100);

                    clearPlaybackFallbackTimer();
                    playbackFallbackTimerRef.current = window.setTimeout(() => {
                        finishPlayback();
                    }, remainingMs);
                } else if (result.reason === SpeechSDK.ResultReason.Canceled) {
                    const cancel = SpeechSDK.CancellationDetails.fromResult(result);
                    console.error("Canceled:", cancel.errorDetails);
                    finishPlayback();
                }
            },
            (err: string) => {
                console.error(err);
                finishPlayback();
            }
        );
    };

    useEffect(() => {
        return () => {
            clearPlaybackFallbackTimer();
            closeSynthesizer();
            closePlayer();
            releaseActivePlaybackIfOwned();
        };
    }, []);

    const color = isPlaying ? "red" : "black";
    const title = isPlaying ? t("tooltips.stopStreaming") : t("tooltips.speakAnswer");
    const iconName = isLoading ? "Sync" : isPlaying ? "Stop" : "Volume3";

    return (
        <IconButton
            style={{ color }}
            iconProps={{ iconName }}
            title={title}
            ariaLabel={title}
            onClick={isPlaying ? handleStop : handlePlay}
            disabled={isStreaming || isLoading}
        />
    );
};
