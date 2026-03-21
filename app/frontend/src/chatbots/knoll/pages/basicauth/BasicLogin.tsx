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
        />
    );
};

export default BasicLogin;
