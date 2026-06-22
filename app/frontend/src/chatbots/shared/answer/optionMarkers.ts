// Interactive option markers for tutor-mode bots.
//
// Tutor bots constantly ask the user closed-choice questions (Tutor vs Q&A,
// which topic, knowledge level 1–5, how many questions, yes/no follow-ups). To
// render those as buttons instead of free text, the model appends a hidden
// control marker at the end of the message:
//
//   [[CHOICES kind=topic allowOther=1]]Selektion | Abrufvergleich | …[[/CHOICES]]
//
// The marker is stripped from the displayed text (see ChatbotAnswer) but kept in
// the stored content so it replays into history — the same approach the HYROX
// assessment uses for its [[…]] markers (see assessmentMarkers.ts).
//
// - kind=mode|level|count carry an EMPTY body; the frontend supplies the
//   localized labels (and, for level, the descriptions) from i18n. The model
//   only signals the moment.
// - kind=topic|generic carry the option labels in the body (dynamic), pipe-separated.
//
// A separate hidden marker, [[SPLIT]], is a bubble separator (not a choice): content
// after it renders as its own assistant bubble. The tutor performance-summary close
// uses it so the summary and the "another topic or Q&A?" prompt (with mode buttons)
// land in two bubbles, mirroring the welcome message. See splitBubbleSegments().
//
// This module is pure (no i18n/React import) — callers pass in the resolved
// OptionTexts so the same option set drives both rendering (AnswerOptions) and
// the "was this turn an option click?" suppression check used by each Chat page.

import type { TFunction } from "i18next";

export type ChoiceKind = "mode" | "level" | "count" | "topic" | "generic";

const CHOICE_KINDS: ChoiceKind[] = ["mode", "level", "count", "topic", "generic"];

export interface ParsedChoice {
    kind: ChoiceKind;
    allowOther: boolean;
    // Labels parsed from the marker body (used for topic/generic; empty otherwise).
    rawOptions: string[];
}

export interface ChoiceOption {
    value: string;
    label: string;
    description?: string;
}

export interface LevelText {
    label: string;
    description: string;
}

// Localized strings the frontend owns for the static-kind option sets. Built once
// per bot from its i18n bundle via buildOptionTexts().
export interface OptionTexts {
    other: string;
    mode: { checkKnowledge: string; askQuestions: string };
    count: { "3": string; "5": string; "10": string };
    level: Record<"1" | "2" | "3" | "4" | "5", LevelText>;
}

// One complete [[CHOICES …]]…[[/CHOICES]] block. Requires the closing tag so a
// half-streamed marker never matches (and therefore never renders mid-stream).
const CHOICES_BLOCK_RE = /\[\[\s*CHOICES\b([^\]]*)\]\]([\s\S]*?)\[\[\s*\/\s*CHOICES\s*\]\]/i;
const CHOICES_BLOCK_RE_GLOBAL = new RegExp(CHOICES_BLOCK_RE.source, "gi");
// A still-streaming opener with no closing tag yet — stripped from display only.
const CHOICES_OPEN_TRAILING_RE = /\[\[\s*CHOICES\b[\s\S]*$/i;

// Bubble separator (tutor end-of-flow). Everything after a [[SPLIT]] marker is
// rendered as a new assistant bubble, so the performance summary and the closing
// "another topic or Q&A?" prompt land in two separate bubbles (the latter carrying
// the mode option buttons, exactly like the welcome message).
const BUBBLE_SPLIT_RE = /\[\[\s*SPLIT\s*\]\]/i;
const BUBBLE_SPLIT_RE_GLOBAL = new RegExp(BUBBLE_SPLIT_RE.source, "gi");
// A still-streaming separator with no closing tag yet — stripped from display only.
const BUBBLE_SPLIT_OPEN_TRAILING_RE = /\[\[\s*SPLIT\b[\s\S]*$/i;

const KIND_RE = /\bkind\s*=\s*"?([a-z]+)"?/i;
const ALLOW_OTHER_RE = /\ballowOther\s*=\s*"?(0|1|true|false|yes|no)"?/i;
const DUPLICATE_TOPIC_LINE_RE = /^\s*(?:[-*•]|\d+[.)])\s+(.+?)\s*$/;
const TOPIC_LIST_INTRO_RE =
    /\b(materials?|lernmaterialien|cover|covers|covered|decken|verf[üu]gbar|available|following|folgenden)\b/i;
const QUESTION_LINE_RE = /[?؟]\s*$/;

// A tutor running-counter heading in any of the three supported locales: German
// "Frage N von Total:", English "Question N of Total:", Dutch "Vraag N van Total:".
// COUNTER_HEADING_RE matches it anywhere in a line (the heading may sit inline with
// its question text); COUNTER_HEADING_LINE_RE matches a line that is ONLY the heading
// (optionally bolded) — the redundant form a tutor turn stacks above the real question.
const COUNTER_HEADING_RE = /(?:Frage|Question|Vraag)\s+\d+\s+(?:von|of|van)\s+\d+\s*:/i;
const COUNTER_HEADING_LINE_RE = /^\*{0,2}\s*(?:Frage|Question|Vraag)\s+\d+\s+(?:von|of|van)\s+\d+\s*:\s*\*{0,2}$/i;

function isChoiceKind(value: string): value is ChoiceKind {
    return (CHOICE_KINDS as string[]).includes(value);
}

// Topic and mode default to offering "Andere Option"; yes/no generics and the
// fixed level/count sets do not.
function defaultAllowOther(kind: ChoiceKind): boolean {
    return kind === "mode" || kind === "topic";
}

function normalizeChoiceLabel(value: string): string {
    return value
        .replace(/\*\*/g, "")
        .replace(/^["'“”„]+|["'“”„]+$/g, "")
        .replace(/\s+/g, " ")
        .trim()
        .toLocaleLowerCase();
}

function stripDuplicateTopicList(text: string, parsed: ParsedChoice | null): string {
    if (!parsed || parsed.kind !== "topic" || parsed.rawOptions.length === 0) {
        return text;
    }

    const topicLabels = new Set(parsed.rawOptions.map(normalizeChoiceLabel));
    const lines = text.split(/\r?\n/);
    const keepLines = lines.map(line => {
        const bulletMatch = DUPLICATE_TOPIC_LINE_RE.exec(line);
        if (!bulletMatch) {
            return true;
        }

        return !topicLabels.has(normalizeChoiceLabel(bulletMatch[1]));
    });

    if (keepLines.every(Boolean)) {
        return text;
    }

    for (let index = 0; index < keepLines.length; index += 1) {
        if (keepLines[index]) {
            continue;
        }

        for (let previous = index - 1; previous >= 0; previous -= 1) {
            const previousLine = lines[previous].trim();
            if (previousLine === "") {
                continue;
            }
            if (TOPIC_LIST_INTRO_RE.test(previousLine) && !QUESTION_LINE_RE.test(previousLine)) {
                keepLines[previous] = false;
            }
            break;
        }
    }

    return lines.filter((_, index) => keepLines[index]).join("\n");
}

// Tutor turns that reveal an answer and then move on sometimes emit the next
// question's running-counter heading TWICE: once spuriously at the top of the turn
// (above the previous answer's feedback) and once correctly right before the next
// question. Each rendered bubble shows exactly one question, so the real heading is
// always the LAST counter occurrence. Drop any standalone heading line that precedes
// a later counter occurrence; the final heading (standalone or inline) is preserved.
function dropDuplicateCounterHeadings(text: string): string {
    if (!text) {
        return text;
    }
    const lines = text.split(/\r?\n/);
    let lastCounterIdx = -1;
    for (let index = 0; index < lines.length; index += 1) {
        if (COUNTER_HEADING_RE.test(lines[index])) {
            lastCounterIdx = index;
        }
    }
    if (lastCounterIdx <= 0) {
        return text;
    }

    const kept = lines.filter((line, index) => !(index < lastCounterIdx && COUNTER_HEADING_LINE_RE.test(line.trim())));
    if (kept.length === lines.length) {
        return text;
    }
    return kept.join("\n");
}

export function parseChoiceMarker(text: string | null | undefined): ParsedChoice | null {
    if (!text) {
        return null;
    }
    const match = CHOICES_BLOCK_RE.exec(text);
    if (!match) {
        return null;
    }

    const attrs = match[1] ?? "";
    const body = match[2] ?? "";
    const kindRaw = (KIND_RE.exec(attrs)?.[1] ?? "").toLowerCase();
    if (!isChoiceKind(kindRaw)) {
        return null;
    }

    const allowRaw = ALLOW_OTHER_RE.exec(attrs)?.[1]?.toLowerCase();
    // level (1–5) and count (3/5/10) are fixed sets — there is never a "type your own"
    // choice for them, so force Other off regardless of what the model emitted.
    const allowOther =
        kindRaw === "level" || kindRaw === "count"
            ? false
            : allowRaw
              ? ["1", "true", "yes"].includes(allowRaw)
              : defaultAllowOther(kindRaw);

    const rawOptions = body
        .split("|")
        .map(option => option.trim())
        .filter(option => option !== "");

    return { kind: kindRaw, allowOther, rawOptions };
}

// Remove every complete CHOICES/SPLIT marker (and any still-streaming opener) for display.
export function stripChoiceMarker(text: string): string {
    if (!text) {
        return text;
    }
    const parsed = parseChoiceMarker(text);
    const displayText = text
        .replace(CHOICES_BLOCK_RE_GLOBAL, "")
        .replace(BUBBLE_SPLIT_RE_GLOBAL, "")
        .replace(CHOICES_OPEN_TRAILING_RE, "")
        .replace(BUBBLE_SPLIT_OPEN_TRAILING_RE, "")
        .replace(/[ \t]+\n/g, "\n")
        .replace(/\n{3,}/g, "\n\n")
        .trim();

    return dropDuplicateCounterHeadings(stripDuplicateTopicList(displayText, parsed))
        .replace(/[ \t]+\n/g, "\n")
        .replace(/\n{3,}/g, "\n\n")
        .trim();
}

// Split raw assistant content into bubble segments on complete [[SPLIT]] markers.
// Returns the trimmed, non-empty segments (always at least one). A still-streaming
// `[[SPLIT` (no closing `]]` yet) does NOT split, so the message stays a single
// bubble until the separator fully arrives.
export function splitBubbleSegments(text: string | null | undefined): string[] {
    if (!text) {
        return [text ?? ""];
    }
    const segments = text
        .split(BUBBLE_SPLIT_RE_GLOBAL)
        .map(segment => segment.trim())
        .filter(segment => segment !== "");
    return segments.length > 0 ? segments : [text];
}

// Resolve the marker into concrete options. Static kinds (mode/level/count) read
// their labels from OptionTexts; dynamic kinds (topic/generic) use the marker body.
// The `value` is what gets sent back to the model on click — a localized label for
// mode/topic/generic, the bare number for level/count.
export function resolveChoiceOptions(parsed: ParsedChoice, texts: OptionTexts): ChoiceOption[] {
    switch (parsed.kind) {
        case "mode":
            return [
                { value: texts.mode.checkKnowledge, label: texts.mode.checkKnowledge },
                { value: texts.mode.askQuestions, label: texts.mode.askQuestions }
            ];
        case "count":
            return (["3", "5", "10"] as const).map(n => ({ value: n, label: texts.count[n] }));
        case "level":
            return (["1", "2", "3", "4", "5"] as const).map(n => ({
                value: n,
                label: texts.level[n].label,
                description: texts.level[n].description
            }));
        case "topic":
        case "generic":
            return parsed.rawOptions.map(option => ({ value: option, label: option }));
        default:
            return [];
    }
}

// True when `userText` exactly matches one of the predefined option values for the
// choice in `prevAssistantContent`. Used to detect that a turn came from clicking
// an option (so its user bubble is suppressed and the selection is shown locked in
// the assistant's option group instead). Free-typed "Andere Option" answers do not
// match a predefined value, so they still render as a normal user bubble.
export function matchesChoiceValue(prevAssistantContent: string | null | undefined, userText: string | null | undefined, texts: OptionTexts): boolean {
    const parsed = parseChoiceMarker(prevAssistantContent);
    if (!parsed) {
        return false;
    }
    const normalized = (userText ?? "").trim();
    if (normalized === "") {
        return false;
    }
    return resolveChoiceOptions(parsed, texts).some(option => option.value.trim() === normalized);
}

type AnswerPairLike = [user: string, response: { message: { content: string } }];

// True when answers[i] is a click on an option offered by answers[i-1].
export function isOptionSelectionTurn(answers: AnswerPairLike[], i: number, texts: OptionTexts): boolean {
    if (i <= 0 || i >= answers.length) {
        return false;
    }
    return matchesChoiceValue(answers[i - 1]?.[1]?.message?.content, answers[i]?.[0], texts);
}

// Build the localized option strings for a bot from its i18n bundle. The keys are a
// shared convention added to every tutor bot's translation files.
export function buildOptionTexts(t: TFunction): OptionTexts {
    return {
        other: t("options.other"),
        mode: {
            checkKnowledge: t("options.mode.checkKnowledge"),
            askQuestions: t("options.mode.askQuestions")
        },
        count: {
            "3": t("options.count.3"),
            "5": t("options.count.5"),
            "10": t("options.count.10")
        },
        level: {
            "1": { label: t("options.level.1.label"), description: t("options.level.1.description") },
            "2": { label: t("options.level.2.label"), description: t("options.level.2.description") },
            "3": { label: t("options.level.3.label"), description: t("options.level.3.description") },
            "4": { label: t("options.level.4.label"), description: t("options.level.4.description") },
            "5": { label: t("options.level.5.label"), description: t("options.level.5.description") }
        }
    };
}
