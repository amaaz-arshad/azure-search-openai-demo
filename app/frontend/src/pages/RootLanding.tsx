import { Helmet } from "react-helmet-async";
import { useTranslation } from "react-i18next";

import styles from "./RootLanding.module.css";

const RootLanding = () => {
    const { t } = useTranslation();

    return (
        <div className={styles.page}>
            <Helmet>
                <title>{t("rootLanding.pageTitle")}</title>
            </Helmet>

            <header className={styles.nav} role="navigation" aria-label={t("rootLanding.topbarAriaLabel")}>
                <a href="https://nerilio.ai/index.html" aria-label={t("rootLanding.homeAriaLabel")}>
                    <img
                        src="https://nerilio.ai/images/nerilio-logo-white.svg"
                        alt="nerilio"
                        className={styles.navLogo}
                        draggable={false}
                    />
                </a>
            </header>

            <main className={styles.main}>
                <div className={styles.wrap}>
                    <h1 className={styles.title}>{t("rootLanding.title")}</h1>
                    <a className={styles.back} href="https://nerilio.ai/index.html">
                        {t("rootLanding.backToHome")}
                    </a>
                    <img className={styles.robot} src="https://nerilio.ai/images/nerilio-frei.png" alt="" draggable={false} />
                </div>
            </main>
        </div>
    );
};

export default RootLanding;
