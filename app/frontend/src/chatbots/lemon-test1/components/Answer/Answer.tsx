import lemonChatbotLogo from "../../assets/lemon-chatbot.png";
import { createBotAnswer } from "../../../shared/answer";
import { SpeechOutputBrowser } from "./SpeechOutputBrowser";
import { SpeechOutputAzure } from "./SpeechOutputAzure";

export const Answer = createBotAnswer(lemonChatbotLogo, SpeechOutputBrowser, SpeechOutputAzure);
