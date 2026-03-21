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
        />
    );
};

export default BasicLogin;
