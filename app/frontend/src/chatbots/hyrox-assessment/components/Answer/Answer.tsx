import lemonChatbotLogo from "../../../lemon/assets/lemon-chatbot.png";
import { createBotAnswer } from "../../../shared/answer";
import { SpeechOutputBrowser } from "./SpeechOutputBrowser";
import { SpeechOutputAzure } from "./SpeechOutputAzure";
import { stripAssessmentMarkers } from "./assessmentMarkers";

// Hidden assessment control markers are stripped for display only; the stored
// answer keeps them so they replay into the next request's history.
export const Answer = createBotAnswer(lemonChatbotLogo, SpeechOutputBrowser, SpeechOutputAzure, {
    preprocessAnswerText: stripAssessmentMarkers
});
