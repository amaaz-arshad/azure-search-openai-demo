import agindoLogo from "../../../../assets/agindo-chatbot.png";
import { createBotAnswer } from "../../../shared/answer";
import { SpeechOutputBrowser } from "./SpeechOutputBrowser";
import { SpeechOutputAzure } from "./SpeechOutputAzure";

export const Answer = createBotAnswer(agindoLogo, SpeechOutputBrowser, SpeechOutputAzure);
