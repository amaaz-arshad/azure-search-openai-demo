import { createInstance, type i18n as I18nInstance } from "i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import { initReactI18next } from "react-i18next";

import type { BotConfig } from "../../../api/models";
import baseDe from "../../shared/i18n/locales/de/translation.json";
import baseEn from "../../shared/i18n/locales/en/translation.json";
import baseNl from "../../shared/i18n/locales/nl/translation.json";

// The standard locale set — matches the built-in bots (en/de/nl). A dynamic bot's UI chrome localizes
// across all of these and follows the browser locale (like built-in bots), rather than being locked to
// the provisioned default. Exposed for the LanguagePicker.
export const GENERIC_SUPPORTED_LANGUAGES: { [code: string]: { name: string } } = {
    de: { name: "Deutsch" },
    en: { name: "English" },
    nl: { name: "Nederlands" }
};

const BASE_BUNDLES: Record<string, Record<string, any>> = {
    de: baseDe,
    en: baseEn,
    nl: baseNl
};

/**
 * Build a runtime i18next instance for a dynamic (provisioned) bot. The UI chrome comes from the shared
 * base bundle for EACH supported locale and follows the browser locale via LanguageDetector — same as a
 * built-in bot — with the provisioned default language as the fallback. The per-bot greeting / disclaimer
 * / display name are overlaid per language where the control panel provided them.
 */
export function createGenericI18n(config: BotConfig): I18nInstance {
    const fallback = GENERIC_SUPPORTED_LANGUAGES[config.defaultLanguage] ? config.defaultLanguage : "en";

    const resources: Record<string, { translation: Record<string, any> }> = {};
    for (const code of Object.keys(GENERIC_SUPPORTED_LANGUAGES)) {
        const base = BASE_BUNDLES[code];
        const greeting = config.greeting?.[code];
        const disclaimerMessage = config.disclaimer?.[code];
        resources[code] = {
            translation: {
                ...base,
                pageTitle: config.displayName || base.pageTitle,
                headerTitle: config.displayName || base.headerTitle,
                ...(greeting ? { initialAssistantMsg: greeting } : {}),
                disclaimer: {
                    ...(base.disclaimer ?? {}),
                    ...(disclaimerMessage ? { message: disclaimerMessage } : {})
                }
            }
        };
    }

    const instance = createInstance();
    instance.use(LanguageDetector).use(initReactI18next).init({
        resources,
        supportedLngs: Object.keys(GENERIC_SUPPORTED_LANGUAGES),
        fallbackLng: fallback,
        load: "languageOnly",
        detection: {
            order: ["navigator"],
            caches: []
        },
        interpolation: { escapeValue: false }
    });
    return instance;
}
