import { useTranslation } from "react-i18next";

import demoLogo from "../../assets/fbn.png";
import BasicLoginPage from "../../../shared/basicauth/BasicLoginPage";
import { login } from "./basicAuth";

const BasicLogin = ({ onSuccess }: { onSuccess: () => void }) => {
    const { t } = useTranslation();

    return (
        <BasicLoginPage
            logoSrc={demoLogo}
            logoAlt="Demo Chatbot logo"
            title={t("loginPage.title")}
            usernamePlaceholder={t("loginPage.username")}
            passwordPlaceholder={t("loginPage.password")}
            loginLabel={t("loginPage.login")}
            invalidCredentials={t("loginPage.invalidCredentials")}
            onLogin={login}
            onSuccess={onSuccess}
            theme={{
                chatbotName: "Demo",
                accent: "#313335",
                accentDark: "#1f2123",
                accentSoft: "rgba(49, 51, 53, 0.12)",
                highlightSoft: "rgba(255, 255, 255, 0.08)",
                pageStart: "#2b2d2f",
                pageMid: "#313335",
                pageEnd: "#3b3e41",
                panelBorder: "rgba(49, 51, 53, 0.12)",
                inputBorder: "rgba(49, 51, 53, 0.14)",
                inputFocus: "rgba(49, 51, 53, 0.38)",
                focusRing: "rgba(49, 51, 53, 0.1)",
                focusRingStrong: "rgba(49, 51, 53, 0.2)",
                textStrong: "#202225",
                textMuted: "#5e6670",
                textPlaceholder: "#7e8791",
                logoSurface: "rgba(255, 255, 255, 0.94)",
                cardBackground: "rgba(255, 255, 255, 0.94)",
                cardShadow: "rgba(0, 0, 0, 0.24)",
                buttonText: "#ffffff",
                buttonShadow: "rgba(0, 0, 0, 0.18)",
                buttonShadowStrong: "rgba(0, 0, 0, 0.24)"
            }}
        />
    );
};

export default BasicLogin;
