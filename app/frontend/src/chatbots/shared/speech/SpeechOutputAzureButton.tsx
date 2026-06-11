import { useEffect, useRef, useState } from "react";
import { IconButton } from "@fluentui/react";
import { useTranslation } from "react-i18next";
import * as SpeechSDK from "microsoft-cognitiveservices-speech-sdk";

import { getPreferredSpeechSynthesisOutputFormat, getSpeechToken } from "./azureSpeech";

let activePlaybackOwner: symbol | null = null;
let activePlaybackStop: (() => void) | null = null;

interface Props {
    answer: string;
    isStreaming: boolean;
}

export const SpeechOutputAzureButton = ({ answer, isStreaming }: Props) => {
    const [isLoading, setIsLoading] = useState(false);
    const [isPlaying, setIsPlaying] = useState(false);
    const instanceIdRef = useRef(Symbol("SpeechOutputAzureButton"));
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
        if (!playerRef.current) {
            return;
        }

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

    const finishPlayback = (forceStopAudio = false) => {
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
        if (!synthesizerRef.current && !playerRef.current) {
            return;
        }
        finishPlayback(true);
    };

    const handlePlay = async () => {
        if (!answer.trim()) {
            return;
        }

        setIsLoading(true);
        setIsPlaying(true);

        try {
            const speechToken = await getSpeechToken();
            const sdkSpeechConfig = SpeechSDK.SpeechConfig.fromAuthorizationToken(speechToken.token, speechToken.region);
            sdkSpeechConfig.speechSynthesisVoiceName = speechToken.voice;
            sdkSpeechConfig.speechSynthesisOutputFormat = getPreferredSpeechSynthesisOutputFormat();

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

            const audioConfig = SpeechSDK.AudioConfig.fromSpeakerOutput(player);
            const synthesizer = new SpeechSDK.SpeechSynthesizer(sdkSpeechConfig, audioConfig);
            synthesizerRef.current = synthesizer;
            activePlaybackOwner = instanceIdRef.current;
            activePlaybackStop = () => {
                finishPlayback(true);
            };

            synthesizer.speakTextAsync(
                answer,
                result => {
                    if (result.reason === SpeechSDK.ResultReason.SynthesizingAudioCompleted) {
                        const sdkDurationMs = result.audioDuration > 0 ? result.audioDuration / 10000 : 0;
                        const estimatedDurationMs = Math.max(1500, answer.length * 70);
                        const totalDurationMs = sdkDurationMs > 0 ? sdkDurationMs : estimatedDurationMs;
                        const currentTimeMs = playerRef.current ? Math.max(0, playerRef.current.currentTime * 1000) : 0;
                        const remainingMs = Math.max(0, totalDurationMs - currentTimeMs + 100);

                        clearPlaybackFallbackTimer();
                        playbackFallbackTimerRef.current = window.setTimeout(() => {
                            finishPlayback();
                        }, remainingMs);
                    } else if (result.reason === SpeechSDK.ResultReason.Canceled) {
                        const cancel = SpeechSDK.CancellationDetails.fromResult(result);
                        console.error("Speech synthesis canceled", cancel.errorDetails);
                        finishPlayback();
                    }
                },
                error => {
                    console.error(error);
                    finishPlayback();
                }
            );
        } catch (error) {
            console.error(error);
            finishPlayback(true);
            alert("Speech output is not available.");
        }
    };

    useEffect(() => {
        return () => {
            clearPlaybackFallbackTimer();
            closeSynthesizer();
            closePlayer();
            releaseActivePlaybackIfOwned();
        };
    }, []);

    const color = isPlaying ? "red" : "var(--chatbot-answer-action-color, black)";
    const title = isPlaying ? t("tooltips.stopStreaming") : t("tooltips.speakAnswer");
    const iconName = isLoading ? "Sync" : isPlaying ? "Stop" : "Volume3";

    return (
        <IconButton
            style={{ color }}
            styles={{
                rootHovered: { backgroundColor: "var(--chatbot-answer-action-hover-background, #f3f2f1)" },
                rootPressed: { backgroundColor: "var(--chatbot-answer-action-pressed-background, #edebe9)" },
                rootDisabled: { backgroundColor: "transparent" }
            }}
            iconProps={{ iconName }}
            title={title}
            ariaLabel={title}
            onClick={isPlaying ? handleStop : () => void handlePlay()}
            disabled={isStreaming || isLoading}
        />
    );
};
