import { createInstance } from "i18next";
import HttpApi from "i18next-http-backend";
import { initReactI18next } from "react-i18next";

import deTranslation from "../locales/de/translation.json";

// Breitband.Tirol is a German-only bot: breitband.tirol is a German-language site and the backend
// locks the answer language to German (language_locale="German" in the bot's config.py). The UI is
// therefore pinned to `de` regardless of the browser locale, exactly as publishone pins `en`. The
// en/nl bundles are kept under locales/ for repo parity but are deliberately not registered.
export const supportedLngs: { [key: string]: { name: string; locale: string } } = {
    de: {
        name: "Deutsch",
        locale: "de-DE"
    }
};

const i18next = createInstance();

i18next.use(HttpApi).use(initReactI18next).init({
    resources: {
        de: { translation: deTranslation }
    },
    lng: "de",
    supportedLngs: Object.keys(supportedLngs),
    fallbackLng: "de",
    load: "languageOnly",
    interpolation: {
        escapeValue: false
    }
});

export default i18next;
