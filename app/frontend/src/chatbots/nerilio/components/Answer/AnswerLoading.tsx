import { Stack } from "@fluentui/react";
import { animated, useSpring } from "@react-spring/web";
import { useTranslation } from "react-i18next";

import styles from "./Answer.module.css";
import sharedAnswerStyles from "../../../shared/answer/SharedAnswer.module.css";
import chatbotLogo from "../../assets/robo1.png";

export const AnswerLoading = () => {
    const { t } = useTranslation();
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
                    <span className={styles.typingDots} role="status" aria-label={t("generatingAnswer")}>
                        <span className={styles.typingDot} />
                        <span className={styles.typingDot} />
                        <span className={styles.typingDot} />
                    </span>
                </Stack>
            </div>
        </animated.div>
    );
};
