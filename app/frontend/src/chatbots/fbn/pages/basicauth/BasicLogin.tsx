import { useTranslation } from "react-i18next";

import fbnLogo from "../../assets/fbn.png";
import BasicLoginPage from "../../../shared/basicauth/BasicLoginPage";
import { login } from "./basicAuth";

const BasicLogin = ({ onSuccess }: { onSuccess: () => void }) => {
    const { t } = useTranslation();

    return (
        <BasicLoginPage
            logoSrc={fbnLogo}
            logoAlt="Logo"
            title={t("loginPage.title")}
            usernamePlaceholder={t("loginPage.username")}
            passwordPlaceholder={t("loginPage.password")}
            loginLabel={t("loginPage.login")}
            invalidCredentials={t("loginPage.invalidCredentials")}
            onLogin={login}
            onSuccess={onSuccess}
            theme={{
                chatbotName: "FBN",
                accent: "#00cc96",
                accentDark: "#008e69",
                accentSoft: "rgba(0, 204, 150, 0.16)",
                highlightSoft: "rgba(144, 251, 186, 0.18)",
                pageStart: "#f2fff9",
                pageMid: "#e0fff3",
                pageEnd: "#cbf8e7",
                panelBorder: "rgba(0, 204, 150, 0.14)",
                inputBorder: "rgba(0, 204, 150, 0.18)",
                inputFocus: "rgba(0, 158, 116, 0.4)",
                focusRing: "rgba(0, 204, 150, 0.14)",
                focusRingStrong: "rgba(0, 158, 116, 0.28)",
                textStrong: "#10352b",
                textMuted: "#3c6b60",
                textPlaceholder: "#709387",
                logoSurface: "rgba(255, 255, 255, 0.78)",
                cardBackground: "rgba(255, 255, 255, 0.78)",
                cardShadow: "rgba(0, 142, 105, 0.14)",
                buttonText: "#ffffff",
                buttonShadow: "rgba(0, 204, 150, 0.24)",
                buttonShadowStrong: "rgba(0, 142, 105, 0.28)"
            }}
        />
    );
};

export default BasicLogin;
