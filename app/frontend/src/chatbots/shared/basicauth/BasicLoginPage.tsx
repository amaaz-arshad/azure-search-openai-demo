import React, { useState } from "react";
import { Icon } from "@fluentui/react";

import styles from "./BasicLoginPage.module.css";

type BasicLoginTheme = {
    chatbotName: string;
    accent: string;
    accentDark: string;
    accentSoft: string;
    highlightSoft: string;
    pageStart: string;
    pageMid: string;
    pageEnd: string;
    panelBorder: string;
    inputBorder: string;
    inputFocus: string;
    focusRing: string;
    focusRingStrong: string;
    textStrong: string;
    textMuted: string;
    textPlaceholder: string;
    logoSurface: string;
    cardBackground: string;
    cardShadow: string;
    buttonText: string;
    buttonShadow: string;
    buttonShadowStrong: string;
};

type BasicLoginPageProps = {
    logoSrc: string;
    logoAlt: string;
    title: string;
    usernamePlaceholder: string;
    passwordPlaceholder: string;
    loginLabel: string;
    invalidCredentials: string;
    theme: BasicLoginTheme;
    onLogin: (username: string, password: string) => boolean;
    onSuccess: () => void;
};

const BasicLoginPage = ({
    logoSrc,
    logoAlt,
    title,
    usernamePlaceholder,
    passwordPlaceholder,
    loginLabel,
    invalidCredentials,
    theme,
    onLogin,
    onSuccess
}: BasicLoginPageProps) => {
    const [username, setUsername] = useState("");
    const [password, setPassword] = useState("");
    const [error, setError] = useState("");
    const [isPasswordVisible, setIsPasswordVisible] = useState(false);

    const handleSubmit = (event: React.FormEvent) => {
        event.preventDefault();
        const ok = onLogin(username, password);

        if (ok) {
            onSuccess();
            return;
        }

        setError(invalidCredentials);
    };

    const handleUsernameChange = (event: React.ChangeEvent<HTMLInputElement>) => {
        setUsername(event.target.value);
        if (error) {
            setError("");
        }
    };

    const handlePasswordChange = (event: React.ChangeEvent<HTMLInputElement>) => {
        setPassword(event.target.value);
        if (error) {
            setError("");
        }
    };

    const themeStyle = {
        "--login-accent": theme.accent,
        "--login-accent-dark": theme.accentDark,
        "--login-accent-soft": theme.accentSoft,
        "--login-highlight-soft": theme.highlightSoft,
        "--login-page-start": theme.pageStart,
        "--login-page-mid": theme.pageMid,
        "--login-page-end": theme.pageEnd,
        "--login-panel-border": theme.panelBorder,
        "--login-input-border": theme.inputBorder,
        "--login-input-focus": theme.inputFocus,
        "--login-focus-ring": theme.focusRing,
        "--login-focus-ring-strong": theme.focusRingStrong,
        "--login-text-strong": theme.textStrong,
        "--login-text-muted": theme.textMuted,
        "--login-text-placeholder": theme.textPlaceholder,
        "--login-logo-surface": theme.logoSurface,
        "--login-card-background": theme.cardBackground,
        "--login-card-shadow": theme.cardShadow,
        "--login-button-text": theme.buttonText,
        "--login-button-shadow": theme.buttonShadow,
        "--login-button-shadow-strong": theme.buttonShadowStrong
    } as React.CSSProperties;

    return (
        <main className={styles.page} style={themeStyle}>
            <div className={styles.glowOne} aria-hidden="true" />
            <div className={styles.glowTwo} aria-hidden="true" />

            <section className={styles.shell}>
                <section className={styles.card}>
                    <div className={styles.header}>
                        {/* <span className={styles.eyebrow}>{theme.chatbotName}</span> */}
                        <div className={styles.logoFrame}>
                            <img className={styles.logo} src={logoSrc} alt={logoAlt} />
                        </div>
                    </div>
                    <h2 className={styles.title}>{title}</h2>

                    <form className={styles.form} onSubmit={handleSubmit} autoComplete="off">
                        <input
                            className={styles.input}
                            placeholder={usernamePlaceholder}
                            value={username}
                            onChange={handleUsernameChange}
                            autoComplete="username"
                            spellCheck={false}
                            autoCapitalize="none"
                            autoCorrect="off"
                        />

                        <div className={styles.inputWrap}>
                            <input
                                className={`${styles.input} ${styles.passwordInput}`}
                                type={isPasswordVisible ? "text" : "password"}
                                placeholder={passwordPlaceholder}
                                value={password}
                                onChange={handlePasswordChange}
                                autoComplete="current-password"
                                spellCheck={false}
                                autoCapitalize="none"
                                autoCorrect="off"
                            />
                            <button
                                className={styles.visibilityToggle}
                                type="button"
                                onClick={() => setIsPasswordVisible(current => !current)}
                                aria-label={isPasswordVisible ? "Hide password" : "Show password"}
                                aria-pressed={isPasswordVisible}
                            >
                                <Icon iconName={isPasswordVisible ? "Hide3" : "RedEye"} />
                            </button>
                        </div>

                        <button className={styles.button} type="submit">
                            {loginLabel}
                        </button>

                        <p className={styles.error} role="alert" aria-live="polite">
                            {error}
                        </p>
                    </form>
                </section>
            </section>
        </main>
    );
};

export default BasicLoginPage;
