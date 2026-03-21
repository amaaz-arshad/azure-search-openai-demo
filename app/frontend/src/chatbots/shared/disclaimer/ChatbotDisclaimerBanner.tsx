import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import styles from "./ChatbotDisclaimerBanner.module.css";

type ChatbotDisclaimerBannerProps = {
    isLoggedIn: boolean;
};

export function ChatbotDisclaimerBanner({ isLoggedIn }: ChatbotDisclaimerBannerProps) {
    const { t } = useTranslation();
    const [isVisible, setIsVisible] = useState(true);
    const wasLoggedIn = useRef(isLoggedIn);

    useEffect(() => {
        if (!wasLoggedIn.current && isLoggedIn) {
            setIsVisible(true);
        }
        wasLoggedIn.current = isLoggedIn;
    }, [isLoggedIn]);

    if (!isVisible) {
        return null;
    }

    return (
        <section className={styles.wrapper} data-testid="chatbot-disclaimer" role="note" aria-live="polite">
            <div className={styles.banner}>
                <div className={styles.content}>
                    <p className={styles.label}>{t("disclaimer.label")}</p>
                    <p className={styles.message}>{t("disclaimer.message")}</p>
                </div>
                <button
                    aria-label={t("disclaimer.dismiss")}
                    className={styles.dismissButton}
                    data-testid="chatbot-disclaimer-close"
                    onClick={() => setIsVisible(false)}
                    type="button"
                >
                    <span aria-hidden="true">&times;</span>
                </button>
            </div>
        </section>
    );
}
