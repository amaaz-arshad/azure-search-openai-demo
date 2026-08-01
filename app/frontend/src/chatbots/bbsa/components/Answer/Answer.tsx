import bbsaAssistantLogo from "../../../../assets/bbsa-assisstant.png";
import { createBotAnswer } from "../../../shared/answer";
import { SpeechOutputBrowser } from "./SpeechOutputBrowser";
import { SpeechOutputAzure } from "./SpeechOutputAzure";

export const Answer = createBotAnswer(bbsaAssistantLogo, SpeechOutputBrowser, SpeechOutputAzure, {
    showAssistantName: false,
    showCopyButton: false,
    assistantLogoPlacement: "outside-left"
});
