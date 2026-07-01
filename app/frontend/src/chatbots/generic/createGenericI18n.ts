import { createInstance, type i18n as I18nInstance } from "i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import { initReactI18next } from "react-i18next";

import type { BotConfig } from "../../api/models";
// Reuse the built-in lemon bot's translation bundles verbatim so a dynamic bot has EVERY UI key the
// forked lemon Layout/Chat and lemon components reference — the generic bot is lemon, parameterized.
import deTranslation from "../lemon/locales/de/translation.json";
import enTranslation from "../lemon/locales/en/translation.json";
import nlTranslation from "../lemon/locales/nl/translation.json";

const BASE_BUNDLES: Record<string, Record<string, any>> = {
    de: deTranslation,
    en: enTranslation,
    nl: nlTranslation
};

const SUPPORTED = ["de", "en", "nl"];

/**
 * Build a runtime i18next instance for a dynamic (provisioned) bot. The UI chrome comes from lemon's
 * base bundle for EACH supported locale and follows the browser locale via LanguageDetector — same as
 * a built-in bot — with the provisioned default language as the fallback. Only the per-bot identity
 * (display name → title, greeting → welcome message, disclaimer text) is overlaid per language.
 */
export function createGenericI18n(config: BotConfig): I18nInstance {
    const fallback = SUPPORTED.includes(config.defaultLanguage) ? config.defaultLanguage : "en";

    const resources: Record<string, { translation: Record<string, any> }> = {};
    for (const code of SUPPORTED) {
        const base = BASE_BUNDLES[code];
        const greeting = config.greeting?.[code];
        const disclaimerMessage = config.disclaimer?.[code];
        resources[code] = {
            translation: {
                ...base,
                // Never fall back to lemon's base title ("Lemon®AID"): a provisioned bot must not surface
                // another bot's brand. displayName is the provisioned title; botName (the route slug) is the
                // always-present neutral fallback if displayName is somehow empty.
                pageTitle: config.displayName || config.botName,
                headerTitle: config.displayName || config.botName,
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
        supportedLngs: SUPPORTED,
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
