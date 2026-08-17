import { cleanSpeechText } from "../../answer/ChatbotAnswer";
import { parseAnswerToMarkdown, stripCitationLinks } from "../../answer/answerParsing";
import type { ChatAppResponseLike } from "../../answer/answerParsing";

/**
 * Turn a chat response into the text the avatar should speak.
 *
 * This is the exact pipeline the per-answer speak button uses (`ChatbotAnswer` builds
 * `answerForSpeech` the same way): resolve citations into the markdown, strip the citation links
 * so the avatar doesn't read "[1]" aloud, then strip the remaining markdown syntax.
 */
export const prepareAnswerForSpeech = (answer: ChatAppResponseLike): string =>
    cleanSpeechText(stripCitationLinks(parseAnswerToMarkdown(answer, false).markdown));
