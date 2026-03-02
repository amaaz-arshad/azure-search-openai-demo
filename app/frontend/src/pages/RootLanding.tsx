import { Helmet } from "react-helmet-async";
import { useTranslation } from "react-i18next";

import styles from "./RootLanding.module.css";

const RootLanding = () => {
    const { t } = useTranslation();

    return (
        <div className={styles.page}>
            <Helmet>
                <title>{t("rootLanding.pageTitle", "Page not found | nerilio")}</title>
            </Helmet>

            <header className={styles.nav} role="navigation" aria-label={t("rootLanding.topbarAriaLabel", "Topbar")}>
                <a href="https://nerilio.ai/index.html" aria-label={t("rootLanding.homeAriaLabel", "Go to homepage")}>
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
                    <h1 className={styles.title}>{t("rootLanding.title", "Please use your specific chat URL.")}</h1>
                    <a className={styles.back} href="https://nerilio.ai/index.html">
                        {t("rootLanding.backToHome", "→ Or click here to return to the homepage.")}
                    </a>
                    <img className={styles.robot} src="https://nerilio.ai/images/nerilio-frei.png" alt="" draggable={false} />
                </div>
            </main>
        </div>
    );
};

export default RootLanding;
