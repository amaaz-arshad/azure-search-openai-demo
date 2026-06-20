export { ChatbotAnswer } from "./ChatbotAnswer";
export { createBotAnswer } from "./createBotAnswer";
export { AnswerOptions } from "./AnswerOptions";
export type { CitationDetail } from "./answerParsing";
export {
    buildOptionTexts,
    isOptionSelectionTurn,
    matchesChoiceValue,
    parseChoiceMarker,
    resolveChoiceOptions,
    splitBubbleSegments,
    stripChoiceMarker
} from "./optionMarkers";
export type { ChoiceKind, ChoiceOption, OptionTexts, ParsedChoice } from "./optionMarkers";
