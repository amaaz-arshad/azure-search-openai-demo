import { FormEvent, useState } from "react";

/*
 * Ported from D:\working student\snap\nerilio backend\views\login.php
 *
 * The source has separate email + password fields. This repo's admin auth
 * (useInternalAdminAccess) uses a single shared password. We keep the source's
 * two-input layout for visual fidelity, but only the password value is sent
 * to the auth hook; the email field is preserved as a placeholder (not wired
 * to any backend yet — matches the "empty shells" decision).
 */

type LoginPageProps = {
    onLogin?: (password: string) => Promise<boolean>;
    isSubmitting?: boolean;
    errorMessage?: string;
    onClearError?: () => void;
};

export function LoginPage({ onLogin, isSubmitting, errorMessage, onClearError }: LoginPageProps) {
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");

    const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (!onLogin) return;
        const success = await onLogin(password);
        if (success) {
            setPassword("");
        }
    };

    const handleCancel = () => {
        setEmail("");
        setPassword("");
        onClearError?.();
    };

    return (
        <div className="login-card">
            <h1>Login</h1>

            {errorMessage ? <div className="login-error">{errorMessage}</div> : null}

            <form method="post" onSubmit={handleSubmit}>
                <div className="form-group">
                    <label htmlFor="vw-email">E-Mail</label>
                    <input
                        type="email"
                        id="vw-email"
                        name="email"
                        value={email}
                        onChange={event => {
                            setEmail(event.target.value);
                            onClearError?.();
                        }}
                        autoComplete="username"
                    />
                </div>

                <div className="form-group">
                    <label htmlFor="vw-password">Passwort</label>
                    <input
                        type="password"
                        id="vw-password"
                        name="password"
                        required
                        value={password}
                        onChange={event => {
                            setPassword(event.target.value);
                            onClearError?.();
                        }}
                        autoComplete="current-password"
                    />
                </div>

                <div className="buttons">
                    <button type="submit" className="btn-login" disabled={isSubmitting}>
                        {isSubmitting ? "Lade …" : "Login"}
                    </button>
                    <button type="button" className="btn-cancel" onClick={handleCancel}>
                        Abbrechen
                    </button>
                </div>
            </form>

            <div className="login-footer" />
        </div>
    );
}

export default LoginPage;
