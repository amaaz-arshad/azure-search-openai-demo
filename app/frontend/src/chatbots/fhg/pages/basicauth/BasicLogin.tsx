import { useTranslation } from "react-i18next";

import fhgLogo from "../../assets/grafik.png";
import BasicLoginPage from "../../../shared/basicauth/BasicLoginPage";
import { login } from "./basicAuth";

const BasicLogin = ({ onSuccess }: { onSuccess: () => void }) => {
    const { t } = useTranslation();

    return (
        <BasicLoginPage
            logoSrc={fhgLogo}
            logoAlt="FHG chatbot logo"
            title={t("loginPage.title")}
            usernamePlaceholder={t("loginPage.username")}
            passwordPlaceholder={t("loginPage.password")}
            loginLabel={t("loginPage.login")}
            invalidCredentials={t("loginPage.invalidCredentials")}
            onLogin={login}
            onSuccess={onSuccess}
            theme={{
                chatbotName: "FHG",
                accent: "#669d24",
                accentDark: "#4d771b",
                accentSoft: "rgba(102, 157, 36, 0.18)",
                highlightSoft: "rgba(176, 209, 131, 0.24)",
                pageStart: "#f8fbf2",
                pageMid: "#edf5df",
                pageEnd: "#dcebbf",
                panelBorder: "rgba(102, 157, 36, 0.14)",
                inputBorder: "rgba(102, 157, 36, 0.2)",
                inputFocus: "rgba(102, 157, 36, 0.4)",
                focusRing: "rgba(102, 157, 36, 0.14)",
                focusRingStrong: "rgba(102, 157, 36, 0.3)",
                textStrong: "#264313",
                textMuted: "#516a39",
                textPlaceholder: "#778867",
                logoSurface: "rgba(255, 255, 255, 0.8)",
                cardBackground: "rgba(255, 255, 255, 0.82)",
                cardShadow: "rgba(77, 119, 27, 0.16)",
                buttonText: "#ffffff",
                buttonShadow: "rgba(102, 157, 36, 0.22)",
                buttonShadowStrong: "rgba(77, 119, 27, 0.3)"
            }}
        />
    );
};

export default BasicLogin;
