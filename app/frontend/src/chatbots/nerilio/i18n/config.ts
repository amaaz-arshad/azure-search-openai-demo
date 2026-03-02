import { createInstance } from "i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import HttpApi from "i18next-http-backend";
import { initReactI18next } from "react-i18next";

import daTranslation from "../locales/da/translation.json";
import deTranslation from "../locales/de/translation.json";
import enTranslation from "../locales/en/translation.json";
import esTranslation from "../locales/es/translation.json";
import frTranslation from "../locales/fr/translation.json";
import itTranslation from "../locales/it/translation.json";
import jaTranslation from "../locales/ja/translation.json";
import nlTranslation from "../locales/nl/translation.json";
import plTranslation from "../locales/pl/translation.json";
import ptBRTranslation from "../locales/ptBR/translation.json";
import trTranslation from "../locales/tr/translation.json";

export const supportedLngs: { [key: string]: { name: string; locale: string } } = {
    da: {
        name: "Dansk",
        locale: "da-DK"
    },
    de: {
        name: "Deutsch",
        locale: "de-DE"
    },
    en: {
        name: "English",
        locale: "en-US"
    },
    es: {
        name: "Español",
        locale: "es-ES"
    },
    fr: {
        name: "Français",
        locale: "fr-FR"
    },
    it: {
        name: "Italiano",
        locale: "it-IT"
    },
    ja: {
        name: "日本語",
        locale: "ja-JP"
    },
    nl: {
        name: "Nederlands",
        locale: "nl-NL"
    },
    pl: {
        name: "Polski",
        locale: "pl-PL"
    },
    ptBR: {
        name: "Português Brasileiro",
        locale: "pt-BR"
    },
    tr: {
        name: "Türkçe",
        locale: "tr-TR"
    }
};

const i18next = createInstance();

i18next.use(HttpApi).use(LanguageDetector).use(initReactI18next).init({
    resources: {
        da: { translation: daTranslation },
        de: { translation: deTranslation },
        en: { translation: enTranslation },
        es: { translation: esTranslation },
        fr: { translation: frTranslation },
        it: { translation: itTranslation },
        ja: { translation: jaTranslation },
        nl: { translation: nlTranslation },
        pl: { translation: plTranslation },
        ptBR: { translation: ptBRTranslation },
        tr: { translation: trTranslation }
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
