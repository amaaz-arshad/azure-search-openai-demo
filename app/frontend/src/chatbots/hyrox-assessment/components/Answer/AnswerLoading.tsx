import { Spinner, Stack } from "@fluentui/react";
import { animated, useSpring } from "@react-spring/web";
import { useTranslation } from "react-i18next";

import styles from "./Answer.module.css";
import { AnswerIcon } from "./AnswerIcon";
import { BeatLoader, PulseLoader } from "react-spinners";

export const AnswerLoading = () => {
    const { t, i18n } = useTranslation();
    const animatedStyles = useSpring({
        from: { opacity: 0 },
        to: { opacity: 1 }
    });

    return (
        <animated.div style={{ ...animatedStyles }}>
            <Stack className={styles.answerContainer}>
                <BeatLoader color="var(--chatbot-answer-action-color, grey)" size={10} />
            </Stack>
        </animated.div>
    );
};
