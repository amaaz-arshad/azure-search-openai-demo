import bensbergLogo from "../../assets/bensberg.png";
import { createBotAnswer } from "../../../shared/answer";
import { SpeechOutputBrowser, SpeechOutputAzure } from "../../../lemon/components/Answer";

export const Answer = createBotAnswer(bensbergLogo, SpeechOutputBrowser, SpeechOutputAzure);
