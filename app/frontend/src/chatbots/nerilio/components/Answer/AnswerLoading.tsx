import { Stack } from "@fluentui/react";
import { animated, useSpring } from "@react-spring/web";

import styles from "./Answer.module.css";
import sharedAnswerStyles from "../../../shared/answer/SharedAnswer.module.css";
import chatbotLogo from "../../assets/robo1.png";
import { BeatLoader } from "react-spinners";

export const AnswerLoading = () => {
    const animatedStyles = useSpring({
        from: { opacity: 0 },
        to: { opacity: 1 }
    });

    return (
        <animated.div style={{ ...animatedStyles }}>
            <div className={`${sharedAnswerStyles.answerShell} ${sharedAnswerStyles.answerShellWithOutsideAvatar}`}>
                <img
                    src={chatbotLogo}
                    alt="Nerilio logo"
                    className={`${sharedAnswerStyles.assistantAvatar} ${sharedAnswerStyles.assistantAvatarOutside}`}
                />
                <Stack className={`${sharedAnswerStyles.answerContainer} ${styles.loadingAnswerContainer}`}>
                    <BeatLoader color="grey" size={10} />
                </Stack>
            </div>
        </animated.div>
    );
};
