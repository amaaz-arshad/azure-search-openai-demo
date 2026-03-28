import { useTranslation } from "react-i18next";

import steuertippsLogo from "../../assets/steuertipps.jpeg";
import BasicLoginPage from "../../../shared/basicauth/BasicLoginPage";
import { login } from "./basicAuth";
import styles from "./BasicLogin.module.css";

const BasicLogin = ({ onSuccess }: { onSuccess: () => void }) => {
    const { t } = useTranslation();

    return (
        <BasicLoginPage
            logoSrc={steuertippsLogo}
            logoAlt="Steuertipps logo"
            logoFrameClassName={styles.logoFrame}
            logoClassName={styles.logo}
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
