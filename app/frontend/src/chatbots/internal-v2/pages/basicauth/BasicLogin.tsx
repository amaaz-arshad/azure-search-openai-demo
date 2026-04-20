import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { Icon } from "@fluentui/react";

import appLogo from "../../../../assets/applogo.svg";
import { login } from "./basicAuth";
import styles from "./BasicLogin.module.css";

type BasicLoginProps = {
    onSuccess: () => void;
};

const BasicLogin = ({ onSuccess }: BasicLoginProps) => {
    const { t } = useTranslation();
    const [username, setUsername] = useState("");
    const [password, setPassword] = useState("");
    const [error, setError] = useState("");
    const [isPasswordVisible, setIsPasswordVisible] = useState(false);

    const handleSubmit = (event: React.FormEvent) => {
        event.preventDefault();
        const ok = login(username, password);

        if (ok) {
            onSuccess();
            return;
        }

        setError(t("loginPage.invalidCredentials"));
    };

    const clearError = () => {
        if (error) setError("");
    };

    return (
        <main className={styles.page}>
            <div className={`${styles.orb} ${styles.orbOne}`} aria-hidden="true" />
            <div className={`${styles.orb} ${styles.orbTwo}`} aria-hidden="true" />

            <section className={styles.shell}>
                <section className={styles.card}>
                    <div className={styles.brand}>
                        <div className={styles.logoRing}>
                            <img className={styles.logo} src={appLogo} alt="Internal Bot v2" />
                        </div>
                        <span className={styles.badge}>
                            <span className={styles.badgeDot} aria-hidden="true" />
                            Internal Bot v2
                        </span>
                        <div>
                            <h1 className={styles.title}>{t("loginPage.title")}</h1>
                            <p className={styles.subtitle}>Sign in to continue to the workspace</p>
                        </div>
                    </div>

                    <form className={styles.form} onSubmit={handleSubmit} autoComplete="off">
                        <div>
                            <div className={styles.fieldLabel}>{t("loginPage.username")}</div>
                            <div className={styles.inputWrap}>
                                <input
                                    className={styles.input}
                                    placeholder={t("loginPage.username")}
                                    value={username}
                                    onChange={e => {
                                        setUsername(e.target.value);
                                        clearError();
                                    }}
                                    autoComplete="username"
                                    spellCheck={false}
                                    autoCapitalize="none"
                                    autoCorrect="off"
                                />
                            </div>
                        </div>

                        <div>
                            <div className={styles.fieldLabel}>{t("loginPage.password")}</div>
                            <div className={styles.inputWrap}>
                                <input
                                    className={`${styles.input} ${styles.passwordInput}`}
                                    type={isPasswordVisible ? "text" : "password"}
                                    placeholder={t("loginPage.password")}
                                    value={password}
                                    onChange={e => {
                                        setPassword(e.target.value);
                                        clearError();
                                    }}
                                    autoComplete="current-password"
                                    spellCheck={false}
                                    autoCapitalize="none"
                                    autoCorrect="off"
                                />
                                <button
                                    className={styles.visibilityToggle}
                                    type="button"
                                    onClick={() => setIsPasswordVisible(v => !v)}
                                    aria-label={isPasswordVisible ? "Hide password" : "Show password"}
                                    aria-pressed={isPasswordVisible}
                                >
                                    <Icon iconName={isPasswordVisible ? "Hide3" : "RedEye"} />
                                </button>
                            </div>
                        </div>

                        <button className={styles.button} type="submit">
                            {t("loginPage.login")}
                        </button>

                        <p className={styles.error} role="alert" aria-live="polite">
                            {error}
                        </p>
                    </form>
                </section>

                <div className={styles.footer}>
                    <strong>nerilio</strong> · Internal workspace
                </div>
            </section>
        </main>
    );
};

export default BasicLogin;
