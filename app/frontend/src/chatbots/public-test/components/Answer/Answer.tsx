import publicTestLogo from "../../assets/applogo.svg";
import { createBotAnswer } from "../../../shared/answer";
import { SpeechOutputBrowser } from "./SpeechOutputBrowser";
import { SpeechOutputAzure } from "./SpeechOutputAzure";

export const Answer = createBotAnswer(publicTestLogo, SpeechOutputBrowser, SpeechOutputAzure);
