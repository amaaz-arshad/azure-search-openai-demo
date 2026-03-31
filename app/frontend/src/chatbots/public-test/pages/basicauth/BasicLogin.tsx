import { FormEvent, useMemo, useState } from "react";
import { Icon } from "@fluentui/react";
import { useTranslation } from "react-i18next";

import publicTestLogo from "../../assets/applogo.svg";
import sharedStyles from "../../../shared/basicauth/BasicLoginPage.module.css";
import styles from "./BasicLogin.module.css";
import {
    login,
    PublicTestSession,
    requestPasswordReset,
    resendPasswordResetCode,
    resendSignUpCode,
    signUp,
    verifyPasswordReset,
    verifySignUp
} from "./basicAuth";

type Mode = "login" | "signup" | "reset";
type SignupStage = "details" | "verify";
type ResetStage = "request" | "verify";

const BasicLogin = ({ onSuccess }: { onSuccess: (session: PublicTestSession) => void }) => {
    const { t } = useTranslation();
    const [mode, setMode] = useState<Mode>("login");
    const [signupStage, setSignupStage] = useState<SignupStage>("details");
    const [resetStage, setResetStage] = useState<ResetStage>("request");
    const [displayName, setDisplayName] = useState("");
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [confirmPassword, setConfirmPassword] = useState("");
    const [verificationCode, setVerificationCode] = useState("");
    const [error, setError] = useState("");
    const [statusMessage, setStatusMessage] = useState("");
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [isResending, setIsResending] = useState(false);
    const [isPasswordVisible, setIsPasswordVisible] = useState(false);
    const [isConfirmPasswordVisible, setIsConfirmPasswordVisible] = useState(false);

    const controlsDisabled = isSubmitting || isResending;
    const isSignupVerifyStep = mode === "signup" && signupStage === "verify";
    const isResetVerifyStep = mode === "reset" && resetStage === "verify";
    const isVerificationStep = isSignupVerifyStep || isResetVerifyStep;

    const title = useMemo(() => {
        if (mode === "login") {
            return t("loginPage.title");
        }
        if (mode === "signup") {
            return isSignupVerifyStep ? t("signupPage.verifyTitle") : t("signupPage.title");
        }
        return isResetVerifyStep ? t("passwordResetPage.verifyTitle") : t("passwordResetPage.title");
    }, [isResetVerifyStep, isSignupVerifyStep, mode, t]);

    const subtitle = useMemo(() => {
        if (mode === "login") {
            return t("loginPage.subtitle");
        }
        if (mode === "signup") {
            return isSignupVerifyStep ? t("signupPage.verifySubtitle", { email }) : t("signupPage.subtitle");
        }
        return isResetVerifyStep
            ? t("passwordResetPage.verifySubtitle", { email })
            : t("passwordResetPage.subtitle");
    }, [email, isResetVerifyStep, isSignupVerifyStep, mode, t]);

    const submitLabel = useMemo(() => {
        if (!isSubmitting) {
            if (mode === "login") {
                return t("loginPage.login");
            }
            if (mode === "signup") {
                return isSignupVerifyStep ? t("signupPage.verifyCode") : t("signupPage.signUp");
            }
            return isResetVerifyStep ? t("passwordResetPage.resetPassword") : t("passwordResetPage.requestCode");
        }

        if (mode === "login") {
            return t("loginPage.loggingIn");
        }
        if (mode === "signup") {
            return isSignupVerifyStep ? t("signupPage.verifyingCode") : t("signupPage.sendingCode");
        }
        return isResetVerifyStep ? t("passwordResetPage.resettingPassword") : t("passwordResetPage.sendingCode");
    }, [isResetVerifyStep, isSignupVerifyStep, isSubmitting, mode, t]);

    const clearMessages = () => {
        if (error) {
            setError("");
        }
        if (statusMessage) {
            setStatusMessage("");
        }
    };

    const resetForm = (nextMode: Mode) => {
        setMode(nextMode);
        setSignupStage("details");
        setResetStage("request");
        setDisplayName("");
        setEmail("");
        setPassword("");
        setConfirmPassword("");
        setVerificationCode("");
        setError("");
        setStatusMessage("");
        setIsPasswordVisible(false);
        setIsConfirmPasswordVisible(false);
    };

    const handleStartSignup = async () => {
        const result = await signUp({
            displayName,
            email,
            password,
            confirmPassword
        });

        if (!result.ok) {
            setError(t(result.errorKey));
            return;
        }

        setEmail(result.email);
        setSignupStage("verify");
        setVerificationCode("");
        setPassword("");
        setConfirmPassword("");
        setStatusMessage(t("signupPage.codeSent", { email: result.email }));
    };

    const handleVerifySignup = async () => {
        const result = await verifySignUp(email, verificationCode);
        if (!result.ok) {
            setError(t(result.errorKey));
            return;
        }

        onSuccess(result.session);
    };

    const handleStartPasswordReset = async () => {
        const result = await requestPasswordReset(email);

        if (!result.ok) {
            setError(t(result.errorKey));
            return;
        }

        setEmail(result.email);
        setResetStage("verify");
        setVerificationCode("");
        setPassword("");
        setConfirmPassword("");
        setStatusMessage(t("passwordResetPage.codeSent", { email: result.email }));
    };

    const handleVerifyPasswordReset = async () => {
        const result = await verifyPasswordReset(email, verificationCode, password, confirmPassword);
        if (!result.ok) {
            setError(t(result.errorKey));
            return;
        }

        onSuccess(result.session);
    };

    const handleSubmit = async (event: FormEvent) => {
        event.preventDefault();
        setIsSubmitting(true);
        setError("");
        setStatusMessage("");

        try {
            if (mode === "login") {
                const result = await login(email, password);
                if (!result.ok) {
                    setError(t(result.errorKey));
                    return;
                }
                onSuccess(result.session);
                return;
            }

            if (mode === "signup") {
                if (isSignupVerifyStep) {
                    await handleVerifySignup();
                    return;
                }
                await handleStartSignup();
                return;
            }

            if (isResetVerifyStep) {
                await handleVerifyPasswordReset();
                return;
            }

            await handleStartPasswordReset();
        } catch (authError) {
            console.error("Public Test auth failed", authError);
            setError(t("authErrors.unexpected"));
        } finally {
            setIsSubmitting(false);
        }
    };

    const handleResendCode = async () => {
        setIsResending(true);
        setError("");
        setStatusMessage("");
        try {
            const result =
                mode === "signup" ? await resendSignUpCode(email) : await resendPasswordResetCode(email);
            if (!result.ok) {
                setError(t(result.errorKey));
                return;
            }
            setStatusMessage(
                t(mode === "signup" ? "signupPage.codeResent" : "passwordResetPage.codeResent", {
                    email: result.email
                })
            );
        } catch (authError) {
            console.error("Public Test verification resend failed", authError);
            setError(t("authErrors.unexpected"));
        } finally {
            setIsResending(false);
        }
    };

    const handleChangeEmail = () => {
        if (mode === "signup") {
            setSignupStage("details");
        } else {
            setResetStage("request");
        }
        setVerificationCode("");
        setPassword("");
        setConfirmPassword("");
        setError("");
        setStatusMessage("");
    };

    const handleForgotPassword = () => {
        resetForm("reset");
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

                    {!isVerificationStep && mode !== "reset" && (
                        <div className={styles.modeSwitch} role="tablist" aria-label={t("loginPage.switchToSignup")}>
                            <button
                                className={`${styles.modeButton} ${mode === "login" ? styles.modeButtonActive : ""}`}
                                disabled={controlsDisabled}
                                onClick={() => resetForm("login")}
                                role="tab"
                                type="button"
                            >
                                {t("loginPage.login")}
                            </button>
                            <button
                                className={`${styles.modeButton} ${mode === "signup" ? styles.modeButtonActive : ""}`}
                                disabled={controlsDisabled}
                                onClick={() => resetForm("signup")}
                                role="tab"
                                type="button"
                            >
                                {t("signupPage.signUp")}
                            </button>
                        </div>
                    )}

                    <form className={sharedStyles.form} onSubmit={handleSubmit} autoComplete="off">
                        {mode === "signup" && signupStage === "details" && (
                            <input
                                className={sharedStyles.input}
                                disabled={controlsDisabled}
                                placeholder={t("signupPage.displayName")}
                                value={displayName}
                                onChange={event => {
                                    setDisplayName(event.target.value);
                                    clearMessages();
                                }}
                                autoComplete="name"
                            />
                        )}

                        {!isVerificationStep && (
                            <input
                                className={sharedStyles.input}
                                disabled={controlsDisabled}
                                placeholder={
                                    mode === "signup"
                                        ? t("signupPage.email")
                                        : mode === "reset"
                                          ? t("passwordResetPage.email")
                                          : t("loginPage.email")
                                }
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
                        )}

                        {(mode === "login" || (mode === "signup" && signupStage === "details")) && (
                            <div className={sharedStyles.inputWrap}>
                                <input
                                    className={`${sharedStyles.input} ${sharedStyles.passwordInput}`}
                                    disabled={controlsDisabled}
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
                                    disabled={controlsDisabled}
                                    type="button"
                                    onClick={() => setIsPasswordVisible(current => !current)}
                                    aria-label={isPasswordVisible ? "Hide password" : "Show password"}
                                    aria-pressed={isPasswordVisible}
                                >
                                    <Icon iconName={isPasswordVisible ? "Hide3" : "RedEye"} />
                                </button>
                            </div>
                        )}

                        {mode === "signup" && signupStage === "details" && (
                            <div className={sharedStyles.inputWrap}>
                                <input
                                    className={`${sharedStyles.input} ${sharedStyles.passwordInput}`}
                                    disabled={controlsDisabled}
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
                                    disabled={controlsDisabled}
                                    type="button"
                                    onClick={() => setIsConfirmPasswordVisible(current => !current)}
                                    aria-label={isConfirmPasswordVisible ? "Hide password" : "Show password"}
                                    aria-pressed={isConfirmPasswordVisible}
                                >
                                    <Icon iconName={isConfirmPasswordVisible ? "Hide3" : "RedEye"} />
                                </button>
                            </div>
                        )}

                        {isVerificationStep && (
                            <>
                                <input
                                    className={sharedStyles.input}
                                    disabled={controlsDisabled}
                                    placeholder={
                                        mode === "signup"
                                            ? t("signupPage.verificationCode")
                                            : t("passwordResetPage.verificationCode")
                                    }
                                    value={verificationCode}
                                    onChange={event => {
                                        setVerificationCode(event.target.value.replace(/[^\d]/g, "").slice(0, 6));
                                        clearMessages();
                                    }}
                                    inputMode="numeric"
                                    autoComplete="one-time-code"
                                />
                                <p className={styles.verificationHint}>
                                    {t(
                                        mode === "signup"
                                            ? "signupPage.verificationHint"
                                            : "passwordResetPage.verificationHint"
                                    )}
                                </p>
                            </>
                        )}

                        {mode === "reset" && resetStage === "verify" && (
                            <>
                                <div className={sharedStyles.inputWrap}>
                                    <input
                                        className={`${sharedStyles.input} ${sharedStyles.passwordInput}`}
                                        disabled={controlsDisabled}
                                        type={isPasswordVisible ? "text" : "password"}
                                        placeholder={t("passwordResetPage.password")}
                                        value={password}
                                        onChange={event => {
                                            setPassword(event.target.value);
                                            clearMessages();
                                        }}
                                        autoComplete="new-password"
                                        spellCheck={false}
                                        autoCapitalize="none"
                                        autoCorrect="off"
                                    />
                                    <button
                                        className={sharedStyles.visibilityToggle}
                                        disabled={controlsDisabled}
                                        type="button"
                                        onClick={() => setIsPasswordVisible(current => !current)}
                                        aria-label={isPasswordVisible ? "Hide password" : "Show password"}
                                        aria-pressed={isPasswordVisible}
                                    >
                                        <Icon iconName={isPasswordVisible ? "Hide3" : "RedEye"} />
                                    </button>
                                </div>

                                <div className={sharedStyles.inputWrap}>
                                    <input
                                        className={`${sharedStyles.input} ${sharedStyles.passwordInput}`}
                                        disabled={controlsDisabled}
                                        type={isConfirmPasswordVisible ? "text" : "password"}
                                        placeholder={t("passwordResetPage.confirmPassword")}
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
                                        disabled={controlsDisabled}
                                        type="button"
                                        onClick={() => setIsConfirmPasswordVisible(current => !current)}
                                        aria-label={isConfirmPasswordVisible ? "Hide password" : "Show password"}
                                        aria-pressed={isConfirmPasswordVisible}
                                    >
                                        <Icon iconName={isConfirmPasswordVisible ? "Hide3" : "RedEye"} />
                                    </button>
                                </div>
                            </>
                        )}

                        <button className={sharedStyles.button} disabled={controlsDisabled} type="submit">
                            {submitLabel}
                        </button>

                        {isVerificationStep && (
                            <div className={styles.secondaryActions}>
                                <button
                                    className={styles.secondaryButton}
                                    disabled={controlsDisabled}
                                    onClick={() => void handleResendCode()}
                                    type="button"
                                >
                                    {isResending
                                        ? t(mode === "signup" ? "signupPage.resendingCode" : "passwordResetPage.resendingCode")
                                        : t(mode === "signup" ? "signupPage.resendCode" : "passwordResetPage.resendCode")}
                                </button>
                                <button
                                    className={styles.secondaryButton}
                                    disabled={controlsDisabled}
                                    onClick={handleChangeEmail}
                                    type="button"
                                >
                                    {t(mode === "signup" ? "signupPage.changeEmail" : "passwordResetPage.changeEmail")}
                                </button>
                            </div>
                        )}

                        <p className={styles.statusMessage} role="status" aria-live="polite">
                            {statusMessage}
                        </p>
                        <p className={sharedStyles.error} role="alert" aria-live="polite">
                            {error}
                        </p>
                    </form>

                    {mode === "login" && !isVerificationStep && (
                        <div className={styles.switchActions}>
                            <p className={styles.switchText}>
                                {t("loginPage.noAccount")}{" "}
                                <button
                                    className={styles.switchLink}
                                    disabled={controlsDisabled}
                                    type="button"
                                    onClick={() => resetForm("signup")}
                                >
                                    {t("loginPage.switchToSignup")}
                                </button>
                            </p>
                            <button
                                className={styles.switchLinkStandalone}
                                disabled={controlsDisabled}
                                type="button"
                                onClick={handleForgotPassword}
                            >
                                {t("loginPage.forgotPassword")}
                            </button>
                        </div>
                    )}

                    {mode === "signup" && !isVerificationStep && (
                        <p className={styles.switchText}>
                            {t("signupPage.haveAccount")}{" "}
                            <button
                                className={styles.switchLink}
                                disabled={controlsDisabled}
                                type="button"
                                onClick={() => resetForm("login")}
                            >
                                {t("signupPage.switchToLogin")}
                            </button>
                        </p>
                    )}

                    {mode === "reset" && !isVerificationStep && (
                        <p className={styles.switchText}>
                            <button
                                className={styles.switchLink}
                                disabled={controlsDisabled}
                                type="button"
                                onClick={() => resetForm("login")}
                            >
                                {t("passwordResetPage.backToLogin")}
                            </button>
                        </p>
                    )}
                </section>
            </section>
        </main>
    );
};

export default BasicLogin;
