import bbsaAssistantLogo from "../../../../assets/bbsa-assisstant.png";
import { createBotAnswer } from "../../../shared/answer";
import { SpeechOutputBrowser } from "./SpeechOutputBrowser";
import { SpeechOutputAzure } from "./SpeechOutputAzure";

// No option overrides: this is lemon's answer design (round avatar and assistant name INSIDE the
// bubble header, copy button in the header actions), not publishone's outside-left wordmark style.
export const Answer = createBotAnswer(bbsaAssistantLogo, SpeechOutputBrowser, SpeechOutputAzure);
