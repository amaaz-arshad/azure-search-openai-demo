import type { ComponentType } from "react";

import { createBotAnswer } from "../../shared/answer/createBotAnswer";
import appLogo from "../../../assets/applogo.svg";

// Speech output is out of scope for the dynamic-bot v1 surface; render nothing.
const NoSpeechBrowser: ComponentType<{ answer: string }> = () => null;
const NoSpeechAzure: ComponentType<{ answer: string; isStreaming: boolean }> = () => null;

export const Answer = createBotAnswer(appLogo, NoSpeechBrowser, NoSpeechAzure, {
    showAssistantName: false,
    showCopyButton: true,
    assistantLogoPlacement: "outside-left"
});
