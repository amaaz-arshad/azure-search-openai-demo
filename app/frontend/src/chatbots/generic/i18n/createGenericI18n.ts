import { createInstance, type i18n as I18nInstance } from "i18next";
import { initReactI18next } from "react-i18next";

import type { BotConfig } from "../../../api/models";
import baseDe from "../../shared/i18n/locales/de/translation.json";
import baseEn from "../../shared/i18n/locales/en/translation.json";
import baseNl from "../../shared/i18n/locales/nl/translation.json";

// Shared base UI strings for dynamic bots, keyed by locale. Built-in bots never use these — they keep
// their own per-bot locale bundles.
const BASE_BUNDLES: Record<string, Record<string, any>> = {
    de: baseDe,
    en: baseEn,
    nl: baseNl
};

/**
 * Build a runtime i18next instance for a dynamic (provisioned) bot: the shared base bundle for each
 * of the bot's languages, with the per-bot greeting / disclaimer / display name overlaid on top so
 * t("initialAssistantMsg"), t("disclaimer.message") and t("headerTitle") resolve to provisioned text.
 */
export function createGenericI18n(config: BotConfig): I18nInstance {
    const fallback = config.defaultLanguage || "en";
    const languages = config.languages.length ? config.languages : [fallback];

    const resources: Record<string, { translation: Record<string, any> }> = {};
    for (const code of languages) {
        const base = BASE_BUNDLES[code] ?? BASE_BUNDLES[fallback] ?? baseEn;
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
    instance.use(initReactI18next).init({
        resources,
        lng: fallback,
        supportedLngs: languages,
        fallbackLng: fallback,
        interpolation: { escapeValue: false }
    });
    return instance;
}
