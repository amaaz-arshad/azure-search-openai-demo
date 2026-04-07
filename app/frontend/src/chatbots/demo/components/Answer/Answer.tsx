import demoLogo from "../../assets/fbn.png";
import { createBotAnswer } from "../../../shared/answer";
import { SpeechOutputBrowser } from "./SpeechOutputBrowser";
import { SpeechOutputAzure } from "./SpeechOutputAzure";

export const Answer = createBotAnswer(demoLogo, SpeechOutputBrowser, SpeechOutputAzure);
