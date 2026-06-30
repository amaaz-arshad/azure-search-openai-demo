import type { i18n as I18nInstance } from "i18next";

import agindoI18n from "../agindo/i18n/config";
import bensbergI18n from "../bensberg/i18n/config";
import demoI18n from "../demo/i18n/config";
import fbnI18n from "../fbn/i18n/config";
import fhgI18n from "../fhg/i18n/config";
import knollI18n from "../knoll/i18n/config";
import lemonI18n from "../lemon/i18n/config";
import moodleI18n from "../moodle/i18n/config";
import nerilioI18n from "../nerilio/i18n/config";
import publishoneI18n from "../publishone/i18n/config";
import sartoriusI18n from "../sartorius/i18n/config";
import steuertippsI18n from "../steuertipps/i18n/config";
import vjoonk4I18n from "../vjoonk4/i18n/config";

export type SourceBotWelcome = {
    initialAssistantMsg: string;
    initialUserMsg: string;
};

const INTERNAL_SOURCE_BOT_I18N: Record<string, I18nInstance> = {
    agindo: agindoI18n,
    bensberg: bensbergI18n,
    demo: demoI18n,
    fbn: fbnI18n,
    fhg: fhgI18n,
    knoll: knollI18n,
    lemon: lemonI18n,
    moodle: moodleI18n,
    nerilio: nerilioI18n,
    publishone: publishoneI18n,
    sartorius: sartoriusI18n,
    steuertipps: steuertippsI18n,
    vjoonk4: vjoonk4I18n
};

const resolveTranslation = (botI18n: I18nInstance, key: string, language: string, fallback: string): string => {
    const normalizedLanguage = language.split("-", 1)[0];
    const candidates = Array.from(new Set([language, normalizedLanguage, "en"]));

    for (const candidate of candidates) {
        if (botI18n.exists(key, { lng: candidate })) {
            return botI18n.t(key, { lng: candidate });
        }
    }

    return botI18n.t(key) || fallback;
};

// Appended to a tutor-mode source bot's welcome so it opens with Tutor/Q&A buttons, exactly like
// that bot's standalone Chat.tsx does. The marker has an EMPTY body — the internal shell supplies the
// localized labels from its own options.mode.* i18n; it is display-stripped and never sent to backend.
const MODE_CHOICE_MARKER = "\n\n[[CHOICES kind=mode]][[/CHOICES]]";

// A source bot is dual-mode (tutor + Q&A) iff it ships the options.mode.* button labels; Q&A-only bots
// (agindo, fhg, nerilio, sartorius, vjoonk4, …) do not and must NOT get the welcome mode buttons.
const isTutorModeSourceBot = (botI18n: I18nInstance): boolean => botI18n.exists("options.mode.checkKnowledge", { lng: "en" });

export const getSourceBotWelcome = (sourceBot: string, language: string): SourceBotWelcome | null => {
    const botI18n = INTERNAL_SOURCE_BOT_I18N[sourceBot];
    if (!botI18n) {
        return null;
    }

    const initialAssistantMsg = resolveTranslation(botI18n, "initialAssistantMsg", language, "");

    return {
        initialAssistantMsg: isTutorModeSourceBot(botI18n) ? initialAssistantMsg + MODE_CHOICE_MARKER : initialAssistantMsg,
        initialUserMsg: resolveTranslation(botI18n, "initialUserMsg", language, "")
    };
};

export const getSourceBotLabel = (sourceBot: string, language: string, fallback?: string): string => {
    const botI18n = INTERNAL_SOURCE_BOT_I18N[sourceBot];
    if (!botI18n) {
        return fallback ?? sourceBot;
    }

    return resolveTranslation(botI18n, "headerTitle", language, fallback ?? sourceBot);
};
