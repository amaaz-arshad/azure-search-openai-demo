// Hidden control markers in an assessment message ([[PLAN ...]], [[SCORE ...]],
// [[RESULT ...]], the model's [[ASK]] placement token, and the backend's [[ASKED q=K]]
// record). They must stay in the stored message so they replay into the next request's
// history (the backend reconstructs the authoritative tally + which question was already
// presented from them), but they must never be shown to the learner. This strips them for
// display only — see ChatbotAnswer's `preprocessAnswerText`. ASKED is listed before ASK so
// the `\b` boundary matches "[[ASKED ...]]" as a whole.
const ASSESSMENT_MARKER_RE = /\[\[\s*(?:PLAN|SCORE|RESULT|ASKED|ASK)\b[^\]]*\]\]/gi;

export function stripAssessmentMarkers(text: string): string {
    if (!text) {
        return text;
    }
    return text
        .replace(ASSESSMENT_MARKER_RE, "")
        .replace(/[ \t]+\n/g, "\n")
        .replace(/\n{3,}/g, "\n\n")
        .trim();
}
