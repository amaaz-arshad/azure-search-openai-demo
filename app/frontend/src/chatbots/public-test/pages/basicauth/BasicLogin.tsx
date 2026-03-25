import { FormEvent, useMemo, useState } from "react";
import { Icon } from "@fluentui/react";
import { useTranslation } from "react-i18next";

import publicTestLogo from "../../assets/applogo.svg";
import sharedStyles from "../../../shared/basicauth/BasicLoginPage.module.css";
import styles from "./BasicLogin.module.css";
import { login, PublicTestSession, signUp } from "./basicAuth";

type Mode = "login" | "signup";

const BasicLogin = ({ onSuccess }: { onSuccess: (session: PublicTestSession) => void }) => {
    const { t } = useTranslation();
    const [mode, setMode] = useState<Mode>("login");
    const [displayName, setDisplayName] = useState("");
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [confirmPassword, setConfirmPassword] = useState("");
    const [error, setError] = useState("");
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [isPasswordVisible, setIsPasswordVisible] = useState(false);
    const [isConfirmPasswordVisible, setIsConfirmPasswordVisible] = useState(false);

    const title = useMemo(
        () => (mode === "login" ? t("loginPage.title") : t("signupPage.title")),
        [mode, t]
    );
    const subtitle = useMemo(
        () => (mode === "login" ? t("loginPage.subtitle") : t("signupPage.subtitle")),
        [mode, t]
    );
    const submitLabel = useMemo(() => {
        if (!isSubmitting) {
            return mode === "login" ? t("loginPage.login") : t("signupPage.signUp");
        }
        return mode === "login" ? t("loginPage.loggingIn") : t("signupPage.creatingAccount");
    }, [isSubmitting, mode, t]);

    const clearMessages = () => {
        if (error) {
            setError("");
        }
    };

    const resetForm = (nextMode: Mode) => {
        setMode(nextMode);
        setDisplayName("");
        setEmail("");
        setPassword("");
        setConfirmPassword("");
        setError("");
        setIsPasswordVisible(false);
        setIsConfirmPasswordVisible(false);
    };

    const handleSubmit = async (event: FormEvent) => {
        event.preventDefault();
        setIsSubmitting(true);
        setError("");

        try {
            const result =
                mode === "login"
                    ? await login(email, password)
                    : await signUp({
                          displayName,
                          email,
                          password,
                          confirmPassword
                      });

            if (!result.ok) {
                setError(t(result.errorKey));
                return;
            }

            onSuccess(result.session);
        } catch (authError) {
            console.error("Public Test auth failed", authError);
            setError(t("authErrors.unexpected"));
        } finally {
            setIsSubmitting(false);
        }
    };

    return (
        <main className={sharedStyles.page}>
            <div className={sharedStyles.glowOne} aria-hidden="true" />
            <div className={sharedStyles.glowTwo} aria-hidden="true" />

            <section className={sharedStyles.shell}>
                <section className={sharedStyles.card}>
                    <div className={sharedStyles.header}>
                        <div className={sharedStyles.logoFrame}>
                            <img className={sharedStyles.logo} src={publicTestLogo} alt="Public Test logo" />
                        </div>
                    </div>

                    <h2 className={sharedStyles.title}>{title}</h2>
                    <p className={styles.subtitle}>{subtitle}</p>

                    <div className={styles.modeSwitch} role="tablist" aria-label={t("loginPage.switchToSignup")}>
                        <button
                            className={`${styles.modeButton} ${mode === "login" ? styles.modeButtonActive : ""}`}
                            disabled={isSubmitting}
                            onClick={() => resetForm("login")}
                            role="tab"
                            type="button"
                        >
                            {t("loginPage.login")}
                        </button>
                        <button
                            className={`${styles.modeButton} ${mode === "signup" ? styles.modeButtonActive : ""}`}
                            disabled={isSubmitting}
                            onClick={() => resetForm("signup")}
                            role="tab"
                            type="button"
                        >
                            {t("signupPage.signUp")}
                        </button>
                    </div>

                    <form className={sharedStyles.form} onSubmit={handleSubmit} autoComplete="off">
                        {mode === "signup" && (
                            <input
                                className={sharedStyles.input}
                                disabled={isSubmitting}
                                placeholder={t("signupPage.displayName")}
                                value={displayName}
                                onChange={event => {
                                    setDisplayName(event.target.value);
                                    clearMessages();
                                }}
                                autoComplete="name"
                            />
                        )}

                        <input
                            className={sharedStyles.input}
                            disabled={isSubmitting}
                            placeholder={mode === "login" ? t("loginPage.email") : t("signupPage.email")}
                            value={email}
                            onChange={event => {
                                setEmail(event.target.value);
                                clearMessages();
                            }}
                            autoComplete="email"
                            spellCheck={false}
                            autoCapitalize="none"
                            autoCorrect="off"
                        />

                        <div className={sharedStyles.inputWrap}>
                            <input
                                className={`${sharedStyles.input} ${sharedStyles.passwordInput}`}
                                disabled={isSubmitting}
                                type={isPasswordVisible ? "text" : "password"}
                                placeholder={mode === "login" ? t("loginPage.password") : t("signupPage.password")}
                                value={password}
                                onChange={event => {
                                    setPassword(event.target.value);
                                    clearMessages();
                                }}
                                autoComplete={mode === "login" ? "current-password" : "new-password"}
                                spellCheck={false}
                                autoCapitalize="none"
                                autoCorrect="off"
                            />
                            <button
                                className={sharedStyles.visibilityToggle}
                                disabled={isSubmitting}
                                type="button"
                                onClick={() => setIsPasswordVisible(current => !current)}
                                aria-label={isPasswordVisible ? "Hide password" : "Show password"}
                                aria-pressed={isPasswordVisible}
                            >
                                <Icon iconName={isPasswordVisible ? "Hide3" : "RedEye"} />
                            </button>
                        </div>

                        {mode === "signup" && (
                            <div className={sharedStyles.inputWrap}>
                                <input
                                    className={`${sharedStyles.input} ${sharedStyles.passwordInput}`}
                                    disabled={isSubmitting}
                                    type={isConfirmPasswordVisible ? "text" : "password"}
                                    placeholder={t("signupPage.confirmPassword")}
                                    value={confirmPassword}
                                    onChange={event => {
                                        setConfirmPassword(event.target.value);
                                        clearMessages();
                                    }}
                                    autoComplete="new-password"
                                    spellCheck={false}
                                    autoCapitalize="none"
                                    autoCorrect="off"
                                />
                                <button
                                    className={sharedStyles.visibilityToggle}
                                    disabled={isSubmitting}
                                    type="button"
                                    onClick={() => setIsConfirmPasswordVisible(current => !current)}
                                    aria-label={isConfirmPasswordVisible ? "Hide password" : "Show password"}
                                    aria-pressed={isConfirmPasswordVisible}
                                >
                                    <Icon iconName={isConfirmPasswordVisible ? "Hide3" : "RedEye"} />
                                </button>
                            </div>
                        )}

                        <button className={sharedStyles.button} disabled={isSubmitting} type="submit">
                            {submitLabel}
                        </button>

                        <p className={sharedStyles.error} role="alert" aria-live="polite">
                            {error}
                        </p>
                    </form>

                    <p className={styles.switchText}>
                        {mode === "login" ? t("loginPage.noAccount") : t("signupPage.haveAccount")}{" "}
                        <button
                            className={styles.switchLink}
                            disabled={isSubmitting}
                            type="button"
                            onClick={() => resetForm(mode === "login" ? "signup" : "login")}
                        >
                            {mode === "login" ? t("loginPage.switchToSignup") : t("signupPage.switchToLogin")}
                        </button>
                    </p>
                </section>
            </section>
        </main>
    );
};

export default BasicLogin;
