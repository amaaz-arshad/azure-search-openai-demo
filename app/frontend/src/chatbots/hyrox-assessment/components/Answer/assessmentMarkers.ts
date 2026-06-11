// Hidden control markers in an assessment message ([[PLAN ...]], [[SCORE ...]],
// [[RESULT ...]], the model's [[ASK]] placement token, the backend's [[ASKED q=K]]
// record, the model's final-turn [[SUMMARY]] separator, and the backend's [[BREAK]]
// bubble split point). They must stay in the stored message so they replay into the next
// request's history (the backend reconstructs the authoritative tally + which question was
// already presented from them), but they must never be shown to the learner. This strips
// them for display only — see ChatbotAnswer's `preprocessAnswerText`. ASKED is listed before
// ASK so the `\b` boundary matches "[[ASKED ...]]" as a whole.
const ASSESSMENT_MARKER_RE = /\[\[\s*(?:PLAN|SCORE|RESULT|ASKED|ASK|SUMMARY|BREAK)\b[^\]]*\]\]/gi;

// The backend joins end-of-assessment sections (final question's evaluation, cumulative
// result, topic summary, motivational message, closing message) with [[BREAK]] so each
// renders as its own chat bubble.
const BUBBLE_BREAK_RE = /\[\[\s*BREAK\s*\]\]/i;

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

// Split one stored assistant message into its display bubbles at the backend's [[BREAK]]
// markers. Display-only: the stored message keeps the full joined content so it replays
// into the next request's history unchanged.
export function splitAssessmentBubbles(text: string): string[] {
    if (!text) {
        return [text];
    }
    const segments = text
        .split(new RegExp(BUBBLE_BREAK_RE.source, "gi"))
        .map(segment => segment.trim())
        .filter(segment => segment !== "");
    return segments.length > 0 ? segments : [text];
}
