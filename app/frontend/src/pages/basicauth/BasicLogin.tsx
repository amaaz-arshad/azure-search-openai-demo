import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import knollLogo from "../../assets/knoll.png";
import { login } from "./basicAuth";

const BasicLogin = ({ onSuccess }: { onSuccess: () => void }) => {
    const { t } = useTranslation();

    const [username, setUsername] = useState("");
    const [password, setPassword] = useState("");
    const [error, setError] = useState("");

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        const ok = login(username, password);
        if (ok) {
            onSuccess();
        } else {
            setError(t("loginPage.invalidCredentials"));
        }
    };

    return (
        <div style={styles.container}>
            <form onSubmit={handleSubmit} style={styles.form}>
                <img src={knollLogo} alt="Logo" style={styles.logo} />
                <h2 style={styles.title}>{t("loginPage.title")}</h2>

                <input placeholder={t("loginPage.username")} value={username} onChange={e => setUsername(e.target.value)} style={styles.input} />

                <input
                    type="password"
                    placeholder={t("loginPage.password")}
                    value={password}
                    onChange={e => setPassword(e.target.value)}
                    style={styles.input}
                />

                {error && <div style={styles.error}>{error}</div>}

                <button type="submit" style={styles.button}>
                    {t("loginPage.login")}
                </button>
            </form>
        </div>
    );
};

const styles: { [key: string]: React.CSSProperties } = {
    container: {
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        height: "100vh",
        backgroundColor: "#0199fe"
    },
    form: {
        backgroundColor: "#ffffff",
        padding: "40px 30px",
        borderRadius: 12,
        boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        minWidth: 300
    },
    logo: {
        width: 60,
        height: 60,
        marginBottom: 20
    },
    title: {
        marginBottom: 20,
        color: "#333",
        fontFamily: "Segoe UI, sans-serif"
    },
    input: {
        width: "100%",
        padding: "10px 12px",
        marginBottom: 15,
        borderRadius: 6,
        border: "1px solid #ccc",
        fontSize: 14
    },
    button: {
        width: "100%",
        padding: "10px 12px",
        borderRadius: 6,
        border: "none",
        backgroundColor: "#0199fe",
        color: "#fff",
        fontSize: 16,
        cursor: "pointer",
        transition: "background-color 0.2s"
    },
    error: {
        color: "#d13438",
        marginBottom: 10,
        fontSize: 13,
        textAlign: "center"
    }
};

export default BasicLogin;
