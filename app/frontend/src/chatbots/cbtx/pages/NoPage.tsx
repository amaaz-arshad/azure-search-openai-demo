import { Helmet } from "react-helmet-async";
import { Trans, useTranslation } from "react-i18next";

import robotImage from "../../shared/noPage/nerilioRobot.webp";
import styles from "../../shared/noPage/NoPage.module.css";

// CABLETEX-branded fork of the shared NoPage. The shared component is hardcoded with
// nerilio links and is re-exported by other bots, so cbtx gets its own copy that
// reuses the shared styles/robot asset but points at CABLETEX's own links.
// TODO(cabletex): replace these placeholder URLs/email with CABLETEX's real website,
// contact address, imprint, and privacy-policy links.
const HOME_URL = "https://www.cabletex.de";
const CONTACT_EMAIL = "info@cabletex.de";
const CONTACT_URL = `mailto:${CONTACT_EMAIL}`;
const IMPRESSUM_URL = "https://www.cabletex.de/impressum";
const PRIVACY_URL = "https://www.cabletex.de/datenschutz";

function getNoPageLanguage(language: string | undefined): "de" | "en" | "nl" {
    const normalizedLanguage = (language ?? "").toLowerCase();

    if (normalizedLanguage.startsWith("de")) {
        return "de";
    }

    if (normalizedLanguage.startsWith("nl")) {
        return "nl";
    }

    return "en";
}

export function Component(): JSX.Element {
    const { t, i18n } = useTranslation();
    const currentYear = new Date().getFullYear();
    const noPageLanguage = getNoPageLanguage(i18n.resolvedLanguage ?? i18n.language);

    return (
        <div className={styles.page}>
            <Helmet>
                <title>{t("rootLanding.pageTitle", { lng: noPageLanguage, defaultValue: "Page not found | CABLETEX" })}</title>
            </Helmet>

            <div aria-hidden="true" className={`${styles.blob} ${styles.blobOne}`} />
            <div aria-hidden="true" className={`${styles.blob} ${styles.blobTwo}`} />

            <main className={styles.main}>
                <div className={styles.card}>
                    <img alt="CABLETEX" className={styles.robot} src={robotImage} />

                    <div className={styles.errorCode}>404</div>

                    <h1 className={styles.title}>{t("noPage.title", { lng: noPageLanguage })}</h1>

                    <div className={styles.infoBox}>
                        <p>
                            <Trans
                                components={{ br: <br />, strong: <strong /> }}
                                i18nKey="noPage.info"
                                tOptions={{ lng: noPageLanguage }}
                            />
                        </p>
                    </div>

                    <div className={styles.actions}>
                        <a className={`${styles.button} ${styles.buttonPrimary}`} href={HOME_URL}>
                            <svg
                                aria-hidden="true"
                                fill="none"
                                height="16"
                                stroke="currentColor"
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                strokeWidth="2"
                                viewBox="0 0 24 24"
                                width="16">
                                <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
                                <polyline points="9 22 9 12 15 12 15 22" />
                            </svg>
                            <span>{t("noPage.primaryAction", { lng: noPageLanguage })}</span>
                        </a>

                        <a className={`${styles.button} ${styles.buttonSecondary}`} href={CONTACT_URL}>
                            <svg
                                aria-hidden="true"
                                fill="none"
                                height="16"
                                stroke="currentColor"
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                strokeWidth="2"
                                viewBox="0 0 24 24"
                                width="16">
                                <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
                                <polyline points="22 6 12 13 2 6" />
                            </svg>
                            <span>{t("noPage.secondaryAction", { lng: noPageLanguage })}</span>
                        </a>
                    </div>

                    <div className={styles.divider}>{t("noPage.divider", { lng: noPageLanguage })}</div>

                    <p className={styles.contactLine}>
                        <Trans
                            components={{
                                email: <a href={CONTACT_URL}>{CONTACT_EMAIL}</a>
                            }}
                            i18nKey="noPage.contactLine"
                            tOptions={{ lng: noPageLanguage }}
                        />
                    </p>
                </div>
            </main>

            <footer className={styles.footer}>
                &copy; {currentYear} CABLETEX
                <span aria-hidden="true">&nbsp;&middot;&nbsp;</span>
                <a href={IMPRESSUM_URL}>{t("noPage.impressum", { lng: noPageLanguage })}</a>
                <span aria-hidden="true">&nbsp;&middot;&nbsp;</span>
                <a href={PRIVACY_URL}>{t("noPage.privacy", { lng: noPageLanguage })}</a>
            </footer>
        </div>
    );
}

Component.displayName = "NoPage";
