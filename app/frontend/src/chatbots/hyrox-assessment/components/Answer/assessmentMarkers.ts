// Hidden control markers the assessment model emits ([[PLAN ...]], [[SCORE ...]],
// [[RESULT ...]]). They must stay in the stored message so they replay into the
// next request's history (the backend reconstructs the authoritative tally from
// them), but they must never be shown to the learner. This strips them for display
// only — see ChatbotAnswer's `preprocessAnswerText`.
const ASSESSMENT_MARKER_RE = /\[\[\s*(?:PLAN|SCORE|RESULT|ASK)\b[^\]]*\]\]/gi;

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
