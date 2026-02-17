import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { IconButton } from "@fluentui/react";
import { SpeechConfig } from "../../api";
import * as SpeechSDK from "microsoft-cognitiveservices-speech-sdk";

interface Props {
    answer: string;
    speechConfig: SpeechConfig;
    isStreaming: boolean;
}

export const SpeechOutputAzure = ({ answer, speechConfig, isStreaming }: Props) => {
    const [isLoading, setIsLoading] = useState(false);
    const [isPlaying, setIsPlaying] = useState(false);
    const audioRef = useRef<HTMLAudioElement>(null);
    const { t } = useTranslation();

    const handlePlay = () => {
        if (!answer) return alert("Enter text to speak");
        setIsLoading(true);
        setIsPlaying(true);

        // Configure speech
        const speechConfig = SpeechSDK.SpeechConfig.fromSubscription("8ca3a8c2671046c9849d763655670358", "swedencentral");
        speechConfig.speechSynthesisVoiceName = "de-DE-Florian:DragonHDLatestNeural";

        // Use browser audio
        const audioConfig = SpeechSDK.AudioConfig.fromDefaultSpeakerOutput();

        const synthesizer = new SpeechSDK.SpeechSynthesizer(speechConfig, audioConfig);

        synthesizer.speakTextAsync(
            answer,
            result => {
                if (result.reason === SpeechSDK.ResultReason.SynthesizingAudioCompleted) {
                    console.log("Speech finished");
                } else if (result.reason === SpeechSDK.ResultReason.Canceled) {
                    const cancel = SpeechSDK.CancellationDetails.fromResult(result);
                    console.error("Canceled:", cancel.errorDetails);
                }
                synthesizer.close();
                setIsPlaying(false);
                setIsLoading(false);
            },
            err => {
                console.error(err);
                synthesizer.close();
                setIsPlaying(false);
                setIsLoading(false);
            }
        );
    };

    const color = isPlaying ? "red" : "black";

    return isLoading ? (
        <IconButton style={{ color }} iconProps={{ iconName: "Sync" }} title="Loading speech" ariaLabel="Loading speech" disabled={true} />
    ) : (
        <IconButton
            style={{ color }}
            iconProps={{ iconName: "Volume3" }}
            title={t("tooltips.speakAnswer")}
            ariaLabel={t("tooltips.speakAnswer")}
            onClick={handlePlay}
            disabled={isStreaming || isPlaying}
        />
    );
};
