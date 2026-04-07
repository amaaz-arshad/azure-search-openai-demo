import moodleLogo from "../../assets/moodle.png";
import { createBotAnswer } from "../../../shared/answer";
import { SpeechOutputBrowser } from "./SpeechOutputBrowser";
import { SpeechOutputAzure } from "./SpeechOutputAzure";

export const Answer = createBotAnswer(moodleLogo, SpeechOutputBrowser, SpeechOutputAzure);
