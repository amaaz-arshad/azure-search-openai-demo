import { useTranslation } from "react-i18next";

import steuertippsLogo from "../../assets/steuertipps.jpeg";
import BasicLoginPage from "../../../shared/basicauth/BasicLoginPage";
import { login } from "./basicAuth";

const BasicLogin = ({ onSuccess }: { onSuccess: () => void }) => {
    const { t } = useTranslation();

    return (
        <BasicLoginPage
            logoSrc={steuertippsLogo}
            logoAlt="Logo"
            title={t("loginPage.title")}
            usernamePlaceholder={t("loginPage.username")}
            passwordPlaceholder={t("loginPage.password")}
            loginLabel={t("loginPage.login")}
            invalidCredentials={t("loginPage.invalidCredentials")}
            onLogin={login}
            onSuccess={onSuccess}
            theme={{
                chatbotName: "Steuertipps",
                accent: "#ffe016",
                accentDark: "#e0c300",
                accentSoft: "rgba(255, 224, 22, 0.18)",
                highlightSoft: "rgba(255, 255, 255, 0.22)",
                pageStart: "#fff7c4",
                pageMid: "#ffeb5c",
                pageEnd: "#ffe016",
                panelBorder: "rgba(0, 0, 0, 0.08)",
                inputBorder: "rgba(0, 0, 0, 0.12)",
                inputFocus: "rgba(18, 59, 182, 0.36)",
                focusRing: "rgba(18, 59, 182, 0.1)",
                focusRingStrong: "rgba(18, 59, 182, 0.2)",
                textStrong: "#191919",
                textMuted: "#4f4b2a",
                textPlaceholder: "#7e7750",
                logoSurface: "rgba(255, 255, 255, 0.9)",
                cardBackground: "rgba(255, 255, 255, 0.88)",
                cardShadow: "rgba(128, 111, 0, 0.18)",
                buttonText: "#191919",
                buttonShadow: "rgba(128, 111, 0, 0.18)",
                buttonShadowStrong: "rgba(128, 111, 0, 0.24)"
            }}
        />
    );
};

export default BasicLogin;
