import publishoneLogo from "../../../../assets/publishone-chat.png";
import { createBotAnswer } from "../../../shared/answer";
import { SpeechOutputBrowser } from "./SpeechOutputBrowser";
import { SpeechOutputAzure } from "./SpeechOutputAzure";
import styles from "./Answer.module.css";

export const Answer = createBotAnswer(publishoneLogo, SpeechOutputBrowser, SpeechOutputAzure, {
    showAssistantName: false,
    assistantLogoVariant: "wordmark",
    assistantLogoClassName: styles.wordmarkLogo
});
