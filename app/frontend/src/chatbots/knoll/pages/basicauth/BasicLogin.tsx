import { useTranslation } from "react-i18next";

import knollLogo from "../../assets/knoll.png";
import BasicLoginPage from "../../../shared/basicauth/BasicLoginPage";
import { login } from "./basicAuth";

const BasicLogin = ({ onSuccess }: { onSuccess: () => void }) => {
    const { t } = useTranslation();

    return (
        <BasicLoginPage
            logoSrc={knollLogo}
            logoAlt="Logo"
            title={t("loginPage.title")}
            usernamePlaceholder={t("loginPage.username")}
            passwordPlaceholder={t("loginPage.password")}
            loginLabel={t("loginPage.login")}
            invalidCredentials={t("loginPage.invalidCredentials")}
            onLogin={login}
            onSuccess={onSuccess}
            theme={{
                chatbotName: "Knoll",
                accent: "#0199fe",
                accentDark: "#005ecf",
                accentSoft: "rgba(1, 153, 254, 0.18)",
                highlightSoft: "rgba(125, 211, 252, 0.18)",
                pageStart: "#f3faff",
                pageMid: "#e0f1ff",
                pageEnd: "#c7e6ff",
                panelBorder: "rgba(1, 153, 254, 0.14)",
                inputBorder: "rgba(1, 153, 254, 0.18)",
                inputFocus: "rgba(1, 153, 254, 0.4)",
                focusRing: "rgba(1, 153, 254, 0.14)",
                focusRingStrong: "rgba(1, 153, 254, 0.3)",
                textStrong: "#102a43",
                textMuted: "#486581",
                textPlaceholder: "#7a8ea5",
                logoSurface: "rgba(255, 255, 255, 0.76)",
                cardBackground: "rgba(255, 255, 255, 0.76)",
                cardShadow: "rgba(1, 94, 207, 0.14)",
                buttonText: "#ffffff",
                buttonShadow: "rgba(1, 153, 254, 0.24)",
                buttonShadowStrong: "rgba(1, 153, 254, 0.3)"
            }}
        />
    );
};

export default BasicLogin;
