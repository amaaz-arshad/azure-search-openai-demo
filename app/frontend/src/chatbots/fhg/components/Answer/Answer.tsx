import fhgLogo from "../../assets/grafik.png";
import { createBotAnswer } from "../../../shared/answer";
import { SpeechOutputBrowser } from "./SpeechOutputBrowser";
import { SpeechOutputAzure } from "./SpeechOutputAzure";

export const Answer = createBotAnswer(fhgLogo, SpeechOutputBrowser, SpeechOutputAzure);
