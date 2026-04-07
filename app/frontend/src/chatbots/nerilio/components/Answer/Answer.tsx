import chatbotLogo from "../../assets/robo1.png";
import { createBotAnswer } from "../../../shared/answer";
import { SpeechOutputBrowser } from "./SpeechOutputBrowser";
import { SpeechOutputAzure } from "./SpeechOutputAzure";

export const Answer = createBotAnswer(chatbotLogo, SpeechOutputBrowser, SpeechOutputAzure, { showAssistantName: false, showCopyButton: false });
