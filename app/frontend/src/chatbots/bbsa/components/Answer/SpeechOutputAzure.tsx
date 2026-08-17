import { SpeechOutputAzureButton } from "../../../shared/speech/SpeechOutputAzureButton";

interface Props {
    answer: string;
    isStreaming: boolean;
}

/**
 * bbsa speaks with its own voice rather than the deployment default.
 *
 * Naming the bot here is what lets the backend return `speech_voice` from bbsa's config.py
 * (de-AT-JonasNeural) instead of AZURE_SPEECH_SERVICE_VOICE. That env var is shared by every
 * speech-enabled bot, so it could not be repointed for bbsa alone.
 */
export const SpeechOutputAzure = (props: Props) => <SpeechOutputAzureButton {...props} chatbotName="bbsa" />;
