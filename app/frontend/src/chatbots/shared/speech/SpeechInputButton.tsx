import { useEffect, useRef, useState } from "react";
import { Button, Tooltip } from "@fluentui/react-components";
import { Mic28Filled } from "@fluentui/react-icons";
import * as SpeechSDK from "microsoft-cognitiveservices-speech-sdk";
import { useTranslation } from "react-i18next";

import { getSpeechRecognitionLocale, getSpeechToken, SupportedSpeechLanguages } from "./azureSpeech";

let activeRecognitionOwner: symbol | null = null;
let activeRecognitionStop: (() => Promise<void>) | null = null;

interface Props {
    updateQuestion: (question: string) => void;
    supportedLngs: SupportedSpeechLanguages;
    containerClassName: string;
    idleMicColor?: string;
}

const stopRecognizer = async (recognizer: SpeechSDK.SpeechRecognizer) =>
    await new Promise<void>(resolve => {
        recognizer.stopContinuousRecognitionAsync(
            () => resolve(),
            error => {
                console.error(error);
                resolve();
            }
        );
    });

export const SpeechInputButton = ({ updateQuestion, supportedLngs, containerClassName, idleMicColor = "black" }: Props) => {
    const { t, i18n } = useTranslation();
    const [isRecording, setIsRecording] = useState(false);
    const [isStarting, setIsStarting] = useState(false);
    const recognizerRef = useRef<SpeechSDK.SpeechRecognizer | null>(null);
    const finalTranscriptRef = useRef("");
    const interimTranscriptRef = useRef("");
    const instanceIdRef = useRef(Symbol("SpeechInputButton"));

    const syncQuestion = () => {
        updateQuestion([finalTranscriptRef.current, interimTranscriptRef.current].filter(Boolean).join(" ").trim());
    };

    const releaseActiveRecognitionIfOwned = () => {
        if (activeRecognitionOwner === instanceIdRef.current) {
            activeRecognitionOwner = null;
            activeRecognitionStop = null;
        }
    };

    const closeRecognizer = () => {
        if (!recognizerRef.current) {
            return;
        }

        recognizerRef.current.recognizing = () => undefined;
        recognizerRef.current.recognized = () => undefined;
        recognizerRef.current.canceled = () => undefined;
        recognizerRef.current.sessionStopped = () => undefined;
        recognizerRef.current.close();
        recognizerRef.current = null;
    };

    const finishRecognition = () => {
        interimTranscriptRef.current = "";
        syncQuestion();
        closeRecognizer();
        releaseActiveRecognitionIfOwned();
        setIsRecording(false);
        setIsStarting(false);
    };

    const stopRecording = async () => {
        const recognizer = recognizerRef.current;
        if (!recognizer) {
            finishRecognition();
            return;
        }

        await stopRecognizer(recognizer);
        finishRecognition();
    };

    const startRecording = async () => {
        if (isRecording || isStarting) {
            return;
        }

        setIsStarting(true);
        finalTranscriptRef.current = "";
        interimTranscriptRef.current = "";
        syncQuestion();

        try {
            if (activeRecognitionOwner !== instanceIdRef.current && activeRecognitionStop) {
                await activeRecognitionStop();
            }

            const speechToken = await getSpeechToken();
            const speechConfig = SpeechSDK.SpeechConfig.fromAuthorizationToken(speechToken.token, speechToken.region);
            speechConfig.speechRecognitionLanguage = getSpeechRecognitionLocale(i18n.language, supportedLngs);
            const audioConfig = SpeechSDK.AudioConfig.fromDefaultMicrophoneInput();
            const recognizer = new SpeechSDK.SpeechRecognizer(speechConfig, audioConfig);

            recognizer.recognizing = (_sender, event) => {
                interimTranscriptRef.current = event.result?.text ?? "";
                syncQuestion();
            };

            recognizer.recognized = (_sender, event) => {
                if (event.result.reason !== SpeechSDK.ResultReason.RecognizedSpeech) {
                    return;
                }

                const transcript = event.result.text.trim();
                if (!transcript) {
                    return;
                }

                finalTranscriptRef.current = [finalTranscriptRef.current, transcript].filter(Boolean).join(" ").trim();
                interimTranscriptRef.current = "";
                syncQuestion();
            };

            recognizer.sessionStopped = () => {
                finishRecognition();
            };

            recognizer.canceled = (_sender, event) => {
                if (event.reason === SpeechSDK.CancellationReason.Error) {
                    console.error("Speech recognition canceled", event.errorDetails);
                    alert(event.errorDetails || "Speech input is not available.");
                }

                finishRecognition();
            };

            recognizerRef.current = recognizer;
            await new Promise<void>((resolve, reject) => {
                recognizer.startContinuousRecognitionAsync(
                    () => resolve(),
                    error => reject(new Error(String(error)))
                );
            });

            activeRecognitionOwner = instanceIdRef.current;
            activeRecognitionStop = stopRecording;
            setIsRecording(true);
            setIsStarting(false);
        } catch (error) {
            console.error(error);
            finishRecognition();
            alert("Speech input is not available.");
        }
    };

    useEffect(() => {
        return () => {
            void stopRecording();
        };
    }, []);

    return (
        <div className={containerClassName}>
            {isRecording ? (
                <Tooltip content={t("tooltips.stopRecording")} relationship="label" showDelay={0} hideDelay={0}>
                    <Button size="large" icon={<Mic28Filled primaryFill="rgba(250, 0, 0, 0.7)" />} onClick={() => void stopRecording()} />
                </Tooltip>
            ) : (
                <Tooltip content={t("tooltips.askWithVoice")} relationship="label" showDelay={0} hideDelay={0}>
                    <Button size="large" icon={<Mic28Filled primaryFill={idleMicColor} />} onClick={() => void startRecording()} disabled={isStarting} />
                </Tooltip>
            )}
        </div>
    );
};
