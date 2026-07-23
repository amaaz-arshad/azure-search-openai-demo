import publishoneLogo from "../../../../assets/publishone_logo.jpeg";
import { createBotAnswer } from "../../../shared/answer";
import { SpeechOutputBrowser } from "./SpeechOutputBrowser";
import { SpeechOutputAzure } from "./SpeechOutputAzure";

export const Answer = createBotAnswer(publishoneLogo, SpeechOutputBrowser, SpeechOutputAzure, {
    showAssistantName: false,
    showCopyButton: false,
    assistantLogoPlacement: "outside-left"
});
