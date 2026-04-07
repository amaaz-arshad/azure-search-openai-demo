import vjoonk4Logo from "../../../../assets/Snap.svg";
import { createBotAnswer } from "../../../shared/answer";
import { SpeechOutputBrowser } from "./SpeechOutputBrowser";
import { SpeechOutputAzure } from "./SpeechOutputAzure";

export const Answer = createBotAnswer(vjoonk4Logo, SpeechOutputBrowser, SpeechOutputAzure);
