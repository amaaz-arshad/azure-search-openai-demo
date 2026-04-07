import sartoriusLogo from "../../../../assets/sartorius-logo.svg";
import { createBotAnswer } from "../../../shared/answer";
import { SpeechOutputBrowser } from "./SpeechOutputBrowser";
import { SpeechOutputAzure } from "./SpeechOutputAzure";
import styles from "./Answer.module.css";

export const Answer = createBotAnswer(sartoriusLogo, SpeechOutputBrowser, SpeechOutputAzure, {
    showAssistantName: false,
    assistantLogoVariant: "wordmark",
    assistantLogoClassName: styles.wordmarkLogo
});
