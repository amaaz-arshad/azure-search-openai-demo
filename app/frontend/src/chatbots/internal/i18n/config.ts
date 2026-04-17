import { createInstance } from "i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import HttpApi from "i18next-http-backend";
import { initReactI18next } from "react-i18next";

import deTranslation from "../locales/de/translation.json";
import enTranslation from "../locales/en/translation.json";
import nlTranslation from "../locales/nl/translation.json";

export const supportedLngs: { [key: string]: { name: string; locale: string } } = {
    de: {
        name: "Deutsch",
        locale: "de-DE"
    },
    en: {
        name: "English",
        locale: "en-US"
    },
    nl: {
        name: "Nederlands",
        locale: "nl-NL"
    }
};

const i18next = createInstance();

i18next.use(HttpApi).use(LanguageDetector).use(initReactI18next).init({
    resources: {
        de: { translation: deTranslation },
        en: { translation: enTranslation },
        nl: { translation: nlTranslation }
    },
    supportedLngs: Object.keys(supportedLngs),
    fallbackLng: "en",
    load: "languageOnly",
    detection: {
        order: ["navigator"],
        caches: []
    },
    interpolation: {
        escapeValue: false
    }
});

export default i18next;
