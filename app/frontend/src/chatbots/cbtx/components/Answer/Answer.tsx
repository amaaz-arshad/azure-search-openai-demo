import cabletexLogo from "../../assets/cabletex-logo.png";
import { createBotAnswer } from "../../../shared/answer";
import { SpeechOutputBrowser } from "./SpeechOutputBrowser";
import { SpeechOutputAzure } from "./SpeechOutputAzure";

export const Answer = createBotAnswer(cabletexLogo, SpeechOutputBrowser, SpeechOutputAzure);
