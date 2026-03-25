import { useTranslation } from "react-i18next";

import sartoriusLogo from "../../../../assets/sartorius-logo.svg";
import BasicLoginPage from "../../../shared/basicauth/BasicLoginPage";
import { login } from "./basicAuth";
import brandingStyles from "./BasicLogin.module.css";

const BasicLogin = ({ onSuccess }: { onSuccess: () => void }) => {
    const { t } = useTranslation();

    return (
        <BasicLoginPage
            logoSrc={sartoriusLogo}
            logoAlt="Sartorius logo"
            logoFrameClassName={brandingStyles.logoFrame}
            logoClassName={brandingStyles.logo}
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
