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
 * base bundle, but ONLY the provisioned `languages` are served: resource bundles are registered for
 * exactly those locales, so a bot provisioned with one language always renders in it regardless of the
 * browser locale, while a multi-language bot follows the browser locale among the provisioned set
 * (falling back to the provisioned default). The chat request's `language` override follows the same
 * resolved locale, so LLM answers are restricted alongside the UI. Only the per-bot identity
 * (display name → title, greeting → welcome message, disclaimer text) is overlaid per language.
 */
export function createGenericI18n(config: BotConfig): I18nInstance {
    const provisioned = (config.languages ?? []).filter(code => SUPPORTED.includes(code));
    // Defensive only: /bot-config always sends a non-empty `languages`; keep every locale usable if
    // a malformed payload ever slips through rather than hard-forcing one.
    const allowed = provisioned.length > 0 ? provisioned : SUPPORTED;
    const fallback = allowed.includes(config.defaultLanguage) ? config.defaultLanguage : allowed[0];

    const resources: Record<string, { translation: Record<string, any> }> = {};
    for (const code of allowed) {
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
        supportedLngs: allowed,
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
