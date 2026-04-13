import vjoonk4Logo from "../../../../assets/robo1.png";
import { createBotAnswer } from "../../../shared/answer";
import { SpeechOutputBrowser } from "./SpeechOutputBrowser";
import { SpeechOutputAzure } from "./SpeechOutputAzure";

export const Answer = createBotAnswer(vjoonk4Logo, SpeechOutputBrowser, SpeechOutputAzure);
