import { motion, useReducedMotion, type Variants } from "framer-motion";
import { useTranslation } from "react-i18next";

import styles from "./WelcomePrompts.module.css";

interface Props {
    onPromptClick: (value: string) => void;
}

// Suggested starter prompts shown beneath the welcome message before the first
// question. Kept nerilio-owned (not the shared Example component) so the styling
// and stagger stay isolated to this bot.
export const WelcomePrompts = ({ onPromptClick }: Props) => {
    const { t } = useTranslation();
    const prefersReducedMotion = useReducedMotion();

    const prompts = [t("defaultExamples.1"), t("defaultExamples.2"), t("defaultExamples.3")].filter(prompt => prompt && prompt.trim().length > 0);

    if (prompts.length === 0) {
        return null;
    }

    const containerVariants: Variants = {
        hidden: {},
        visible: {
            transition: {
                staggerChildren: prefersReducedMotion ? 0 : 0.07,
                delayChildren: prefersReducedMotion ? 0 : 0.08
            }
        }
    };

    const itemVariants: Variants = {
        hidden: prefersReducedMotion ? { opacity: 0 } : { opacity: 0, y: 10 },
        visible: {
            opacity: 1,
            y: 0,
            transition: { duration: 0.32, ease: "easeOut" }
        }
    };

    return (
        <motion.div className={styles.welcome} variants={containerVariants} initial="hidden" animate="visible">
            <motion.p className={styles.label} variants={itemVariants}>
                {t("chatEmptyStateSubtitle")}
            </motion.p>
            <div className={styles.cards}>
                {prompts.map((prompt, i) => (
                    <motion.button
                        key={i}
                        type="button"
                        className={styles.card}
                        variants={itemVariants}
                        whileHover={prefersReducedMotion ? undefined : { y: -2 }}
                        whileTap={prefersReducedMotion ? undefined : { scale: 0.985 }}
                        onClick={() => onPromptClick(prompt)}
                    >
                        <span className={styles.cardText}>{prompt}</span>
                        <span className={styles.cardArrow} aria-hidden="true">
                            →
                        </span>
                    </motion.button>
                ))}
            </div>
        </motion.div>
    );
};
