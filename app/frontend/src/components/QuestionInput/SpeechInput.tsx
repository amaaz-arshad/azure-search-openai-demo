import { useEffect, useRef, useState } from "react";
import { Button, Tooltip } from "@fluentui/react-components";
import { Mic28Filled } from "@fluentui/react-icons";
import { useTranslation } from "react-i18next";
import * as SpeechSDK from "microsoft-cognitiveservices-speech-sdk";
import styles from "./QuestionInput.module.css";
import { supportedLngs } from "../../i18n/config";
import { getSpeechToken, invalidateSpeechToken, isSpeechAuthFailure } from "../../speech/azureSpeech";

interface Props {
    updateQuestion: (question: string) => void;
}

export const SpeechInput = ({ updateQuestion }: Props) => {
    const { t, i18n } = useTranslation();
    const [isRecording, setIsRecording] = useState(false);
    const [isStarting, setIsStarting] = useState(false);
    const recognizerRef = useRef<SpeechSDK.SpeechRecognizer | null>(null);
    const isStoppingRef = useRef(false);
    const sessionIdRef = useRef(0);
    const finalTranscriptRef = useRef("");
    const interimTranscriptRef = useRef("");

    const currentLng = i18n.language;
    let lngCode = supportedLngs[currentLng]?.locale;
    if (!lngCode) {
        lngCode = "en-US";
    }

    const syncTranscript = () => {
        const transcript = [finalTranscriptRef.current, interimTranscriptRef.current].filter(Boolean).join(" ").trim();
        updateQuestion(transcript);
    };

    const closeRecognizer = () => {
        if (recognizerRef.current) {
            recognizerRef.current.close();
            recognizerRef.current = null;
        }
    };

    const finishRecognition = () => {
        closeRecognizer();
        isStoppingRef.current = false;
        setIsRecording(false);
        setIsStarting(false);
    };

    const stopRecording = () => {
        if (!recognizerRef.current) {
            finishRecognition();
            return;
        }

        isStoppingRef.current = true;
        recognizerRef.current.stopContinuousRecognitionAsync(
            () => {
                finishRecognition();
            },
            err => {
                console.error("Unable to stop speech recognition.", err);
                finishRecognition();
            }
        );
    };

    const startRecording = async (forceTokenRefresh: boolean = false, resetTranscript: boolean = true) => {
        if (isRecording || isStarting) {
            return;
        }

        if (resetTranscript) {
            finalTranscriptRef.current = "";
            interimTranscriptRef.current = "";
            updateQuestion("");
        }

        setIsStarting(true);

        try {
            const speechToken = await getSpeechToken(forceTokenRefresh);
            const sessionId = sessionIdRef.current + 1;
            sessionIdRef.current = sessionId;

            const speechConfig = SpeechSDK.SpeechConfig.fromAuthorizationToken(
                speechToken.authorizationToken,
                speechToken.region
            );
            speechConfig.speechRecognitionLanguage = lngCode;

            const audioConfig = SpeechSDK.AudioConfig.fromDefaultMicrophoneInput();
            const recognizer = new SpeechSDK.SpeechRecognizer(speechConfig, audioConfig);
            recognizerRef.current = recognizer;
            isStoppingRef.current = false;

            recognizer.recognizing = (_sender, event) => {
                if (sessionId !== sessionIdRef.current) {
                    return;
                }

                if (event.result.reason === SpeechSDK.ResultReason.RecognizingSpeech) {
                    interimTranscriptRef.current = event.result.text.trim();
                    syncTranscript();
                }
            };

            recognizer.recognized = (_sender, event) => {
                if (sessionId !== sessionIdRef.current) {
                    return;
                }

                if (event.result.reason === SpeechSDK.ResultReason.RecognizedSpeech) {
                    const recognizedText = event.result.text.trim();
                    if (recognizedText) {
                        finalTranscriptRef.current = [finalTranscriptRef.current, recognizedText].filter(Boolean).join(" ").trim();
                        interimTranscriptRef.current = "";
                        syncTranscript();
                    }
                } else if (event.result.reason === SpeechSDK.ResultReason.NoMatch) {
                    interimTranscriptRef.current = "";
                    syncTranscript();
                }
            };

            recognizer.sessionStopped = () => {
                if (sessionId !== sessionIdRef.current) {
                    return;
                }
                finishRecognition();
            };

            recognizer.canceled = (_sender, event) => {
                if (sessionId !== sessionIdRef.current) {
                    return;
                }

                const wasStopping = isStoppingRef.current;
                const errorDetails = event.errorDetails || "";
                finishRecognition();

                if (wasStopping) {
                    return;
                }

                if (isSpeechAuthFailure(errorDetails) && !forceTokenRefresh) {
                    invalidateSpeechToken();
                    void startRecording(true, false);
                    return;
                }

                const reasonText = errorDetails || SpeechSDK.CancellationReason[event.reason] || "unknown";
                console.error("Speech recognition canceled.", reasonText);
                alert(`Speech recognition error detected: ${reasonText}.`);
            };

            recognizer.startContinuousRecognitionAsync(
                () => {
                    if (sessionId !== sessionIdRef.current) {
                        recognizer.stopContinuousRecognitionAsync(
                            () => {
                                recognizer.close();
                            },
                            () => {
                                recognizer.close();
                            }
                        );
                        return;
                    }

                    setIsStarting(false);
                    setIsRecording(true);
                },
                err => {
                    finishRecognition();

                    if (isSpeechAuthFailure(err) && !forceTokenRefresh) {
                        invalidateSpeechToken();
                        void startRecording(true, false);
                        return;
                    }

                    console.error("Unable to start speech recognition.", err);
                    alert(`Speech recognition error detected: ${err}.`);
                }
            );
        } catch (error) {
            finishRecognition();
            const errorMessage = error instanceof Error ? error.message : "Unable to start speech recognition.";
            console.error(error);
            alert(errorMessage);
        }
    };

    useEffect(() => {
        return () => {
            stopRecording();
        };
    }, []);

    const isBusy = isRecording || isStarting;

    if (typeof window === "undefined") {
        return <></>;
    }

    return (
        <>
            {!isBusy && (
                <div className={styles.questionInputButtonsContainer}>
                    <Tooltip content={t("tooltips.askWithVoice")} relationship="label">
                        <Button size="large" icon={<Mic28Filled primaryFill="black" />} onClick={() => void startRecording()} />
                    </Tooltip>
                </div>
            )}
            {isBusy && (
                <div className={styles.questionInputButtonsContainer}>
                    <Tooltip content={t("tooltips.stopRecording")} relationship="label">
                        <Button size="large" icon={<Mic28Filled primaryFill="rgba(250, 0, 0, 0.7)" />} disabled={!isBusy} onClick={stopRecording} />
                    </Tooltip>
                </div>
            )}
        </>
    );
};
