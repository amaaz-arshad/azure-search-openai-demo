import { createInstance } from "i18next";
import HttpApi from "i18next-http-backend";
import { initReactI18next } from "react-i18next";

import enTranslation from "../locales/en/translation.json";

export const supportedLngs: { [key: string]: { name: string; locale: string } } = {
    en: {
        name: "English",
        locale: "en-US"
    }
};

const i18next = createInstance();

i18next.use(HttpApi).use(initReactI18next).init({
    resources: {
        en: { translation: enTranslation }
    },
    lng: "en",
    supportedLngs: Object.keys(supportedLngs),
    fallbackLng: "en",
    load: "languageOnly",
    interpolation: {
        escapeValue: false
    }
});

export default i18next;
