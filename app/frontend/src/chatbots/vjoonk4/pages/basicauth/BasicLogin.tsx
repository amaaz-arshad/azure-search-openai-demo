import { useTranslation } from "react-i18next";

import vjoonk4Logo from "../../../../assets/Snap.svg";
import BasicLoginPage from "../../../shared/basicauth/BasicLoginPage";
import { login } from "./basicAuth";

const BasicLogin = ({ onSuccess }: { onSuccess: () => void }) => {
    const { t } = useTranslation();

    return (
        <BasicLoginPage
            logoSrc={vjoonk4Logo}
            logoAlt="VJOON K4 logo"
            title={t("loginPage.title")}
            usernamePlaceholder={t("loginPage.username")}
            passwordPlaceholder={t("loginPage.password")}
            loginLabel={t("loginPage.login")}
            invalidCredentials={t("loginPage.invalidCredentials")}
            onLogin={login}
            onSuccess={onSuccess}
            theme={{
                chatbotName: "VJOON K4",
                accent: "#00cc96",
                accentDark: "#009c73",
                accentSoft: "rgba(0, 204, 150, 0.18)",
                highlightSoft: "rgba(102, 234, 195, 0.18)",
                pageStart: "#f2fffb",
                pageMid: "#ddfbf3",
                pageEnd: "#c5f7e8",
                panelBorder: "rgba(0, 204, 150, 0.14)",
                inputBorder: "rgba(0, 204, 150, 0.18)",
                inputFocus: "rgba(0, 204, 150, 0.4)",
                focusRing: "rgba(0, 204, 150, 0.14)",
                focusRingStrong: "rgba(0, 204, 150, 0.3)",
                textStrong: "#0f3b30",
                textMuted: "#47665d",
                textPlaceholder: "#748f88",
                logoSurface: "rgba(255, 255, 255, 0.76)",
                cardBackground: "rgba(255, 255, 255, 0.76)",
                cardShadow: "rgba(0, 156, 115, 0.14)",
                buttonText: "#ffffff",
                buttonShadow: "rgba(0, 204, 150, 0.24)",
                buttonShadowStrong: "rgba(0, 204, 150, 0.3)"
            }}
        />
    );
};

export default BasicLogin;
