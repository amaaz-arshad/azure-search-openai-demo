import knollLogo from "../../assets/knoll.png";
import { createBotAnswer } from "../../../shared/answer";
import { SpeechOutputBrowser } from "./SpeechOutputBrowser";
import { SpeechOutputAzure } from "./SpeechOutputAzure";

export const Answer = createBotAnswer(knollLogo, SpeechOutputBrowser, SpeechOutputAzure);
