import appLogo from "../../../../assets/applogo.svg";
import { createBotAnswer } from "../../../shared/answer";
// Speech wrappers are behaviorally bot-agnostic (SpeechOutputAzure is itself a re-export of the shared
// button; SpeechOutputBrowser is a thin browser-TTS wrapper). Reused as-is for now; a later migration
// step promotes them into shared/ so the generic bot has no lemon import at all.
import { SpeechOutputBrowser } from "../../../lemon/components/Answer/SpeechOutputBrowser";
import { SpeechOutputAzure } from "../../../lemon/components/Answer/SpeechOutputAzure";

// Generic (dynamic) bots own their assistant-avatar binding of the shared answer factory. Using the
// neutral shared app mark (applogo.svg) means a provisioned bot NEVER inherits another bot's logo —
// unlike importing lemon's pre-baked Answer, which froze the lemon-chatbot.png avatar into every
// dynamic bot. Once BotConfig carries a per-bot logo URL this can prefer that over applogo.svg.
// citationContentRoot "content2": provisioned bots' KB files live in the content2 container and
// are never mirrored into content, so citations must resolve through the backend /content2 route.
export const Answer = createBotAnswer(appLogo, SpeechOutputBrowser, SpeechOutputAzure, { citationContentRoot: "content2" });
