import i18next from "i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import HttpApi from "i18next-http-backend";
import { initReactI18next } from "react-i18next";

import daTranslation from "../locales/da/translation.json";
import enTranslation from "../locales/en/translation.json";
import esTranslation from "../locales/es/translation.json";
import frTranslation from "../locales/fr/translation.json";
import jaTranslation from "../locales/ja/translation.json";
import nlTranslation from "../locales/nl/translation.json";
import ptBRTranslation from "../locales/ptBR/translation.json";
import trTranslation from "../locales/tr/translation.json";
import itTranslation from "../locales/it/translation.json";
import plTranslation from "../locales/pl/translation.json";
import deTranslation from "../locales/de/translation.json";

/* =======================
   🔍 BROWSER LANGUAGE LOGS
   ======================= */
console.log("navigator.language:", navigator.language);
console.log("navigator.languages:", navigator.languages);

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
    // da: {
    //     name: "Dansk",
    //     locale: "da-DK"
    // },
    // es: {
    //     name: "Español",
    //     locale: "es-ES"
    // },
    // fr: {
    //     name: "Français",
    //     locale: "fr-FR"
    // },
    // ja: {
    //     name: "日本語",
    //     locale: "ja-JP"
    // },
    //     ptBR: {
    //         name: "Português Brasileiro",
    //         locale: "pt-BR"
    //     },
    //     tr: {
    //         name: "Türkçe",
    //         locale: "tr-TR"
    //     },
    //     it: {
    //         name: "Italiano",
    //         locale: "it-IT"
    //     },
    //     pl: {
    //         name: "Polski",
    //         locale: "pl-PL"
    //     }
};

i18next
    .use(HttpApi)
    .use(LanguageDetector)
    .use(initReactI18next)
    // init i18next
    // for all options read: https://www.i18next.com/overview/configuration-options
    .init({
        resources: {
            de: { translation: deTranslation },
            en: { translation: enTranslation },
            nl: { translation: nlTranslation }
            // da: { translation: daTranslation },
            // es: { translation: esTranslation },
            // fr: { translation: frTranslation },
            // ja: { translation: jaTranslation },
            // ptBR: { translation: ptBRTranslation },
            // tr: { translation: trTranslation },
            // it: { translation: itTranslation },
            // pl: { translation: plTranslation }
        },
        supportedLngs: Object.keys(supportedLngs),
        fallbackLng: "en",
        load: "languageOnly",
        detection: {
            order: ["navigator"], // ONLY navigator
            caches: [] // NO cookies / localStorage
        },
        interpolation: {
            escapeValue: false // not needed for react as it escapes by default
        }
    });

export default i18next;
