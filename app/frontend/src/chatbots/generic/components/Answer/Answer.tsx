import { useMemo, type ComponentProps } from "react";

// Fallback assistant avatar for a provisioned bot that ships no `design.icon`: the shared nerilio robot
// mascot (also used by the 404 NoPage), NOT the generic Azure "stars" app mark (applogo.svg).
import fallbackAvatar from "../../../shared/noPage/nerilioRobot.webp";
import { createBotAnswer } from "../../../shared/answer";
// Speech wrappers are behaviorally bot-agnostic (SpeechOutputAzure is itself a re-export of the shared
// button; SpeechOutputBrowser is a thin browser-TTS wrapper). Reused as-is for now; a later migration
// step promotes them into shared/ so the generic bot has no lemon import at all.
import { SpeechOutputBrowser } from "../../../lemon/components/Answer/SpeechOutputBrowser";
import { SpeechOutputAzure } from "../../../lemon/components/Answer/SpeechOutputAzure";
import { useBotConfig } from "../../botConfigContext";

// Build the shared answer factory bound to a given assistant-avatar source.
// citationContentRoot "content2": provisioned bots' KB files live in the content2 container and are
// never mirrored into content, so citations must resolve through the backend /content2 route.
const makeAnswer = (assistantAvatarSrc: string) =>
    createBotAnswer(assistantAvatarSrc, SpeechOutputBrowser, SpeechOutputAzure, { citationContentRoot: "content2" });

// Default binding uses the shared nerilio robot mascot so a provisioned bot without its own icon NEVER
// inherits another bot's logo (importing lemon's pre-baked Answer once froze lemon-chatbot.png into every
// dynamic bot — that was the bug) and never shows the generic Azure "stars" app mark.
const DefaultAnswer = makeAnswer(fallbackAvatar);

type AnswerComponentProps = ComponentProps<typeof DefaultAnswer>;

// Generic (dynamic) bots own their assistant-avatar binding. The avatar is the provisioned `design.icon`
// (base64 data URI from /bot-config) when present, else the nerilio robot fallback. `icon` is stable for a
// bot's route lifetime, so the memoized inner component is created once per bot — no remount churn per render.
export function Answer(props: AnswerComponentProps) {
    const botConfig = useBotConfig();
    const iconSrc = botConfig.icon || fallbackAvatar;
    const InnerAnswer = useMemo(() => (iconSrc === fallbackAvatar ? DefaultAnswer : makeAnswer(iconSrc)), [iconSrc]);
    return <InnerAnswer {...props} />;
}
