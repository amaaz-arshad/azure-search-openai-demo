// Hidden control markers in an assessment message ([[PLAN ...]], [[SCORE ...]],
// [[RESULT ...]], the model's [[ASK]] placement token, the backend's [[ASKED q=K]]
// record, the model's final-turn [[SUMMARY]] separator, the backend's [[BREAK]]
// bubble split point, the backend's [[PROGRESS value=N]] pass signal, and the backend's
// [[DONE]] completion signal). They must stay in the stored message so they replay into the
// next request's history (the backend reconstructs the authoritative tally + which question
// was already presented from them), but they must never be shown to the learner. This strips
// them for display only — see ChatbotAnswer's `preprocessAnswerText`. ASKED is listed before
// ASK so the `\b` boundary matches "[[ASKED ...]]" as a whole.
const ASSESSMENT_MARKER_RE = /\[\[\s*(?:PLAN|SCORE|RESULT|ASKED|ASK|SUMMARY|BREAK|PROGRESS|DONE)\b[^\]]*\]\]/gi;

// The backend emits this once, only on a passed completion, to hand the result back to the
// Lemon app (fired as lemon://save_progress?value=N — see lemonBridge.reportLemonProgress).
const PROGRESS_MARKER_RE = /\[\[\s*PROGRESS\b[^\]]*\bvalue\s*=\s*(\d+)[^\]]*\]\]/i;

// The backend joins end-of-assessment sections (final question's evaluation, cumulative
// result, topic summary, motivational message, closing message) with [[BREAK]] so each
// renders as its own chat bubble.
const BUBBLE_BREAK_RE = /\[\[\s*BREAK\s*\]\]/i;

// The backend emits this once, on ANY completion (pass OR fail), on the turn the final question is
// graded. The frontend hides it at render and uses it to remove the question input, since a
// completed run is terminal in this session regardless of outcome. Retaking happens only by starting
// a fresh session (on a fail, the chat's in-app restart button; or a fresh Lemon-app launch), never
// by sending another message. Unlike PROGRESS (pass only), this is present for both pass and fail.
const DONE_MARKER_RE = /\[\[\s*DONE\s*\]\]/i;

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

// Return the value of the backend's [[PROGRESS value=N]] pass signal, or null when absent.
// Used to fire the Lemon save_progress hand-off once on a freshly received passed completion.
export function parseProgressValue(text: string): number | null {
    if (!text) {
        return null;
    }
    const match = PROGRESS_MARKER_RE.exec(text);
    if (!match) {
        return null;
    }
    const value = Number.parseInt(match[1], 10);
    return Number.isNaN(value) ? null : value;
}

// True once the assessment has completed (pass OR fail), detected via the backend's hidden
// [[DONE]] marker on the final message. Replays from history, so a reopened completed session is
// also detected. Used to remove the question input, since a completed run is terminal in-session.
export function hasAssessmentDoneMarker(text: string): boolean {
    if (!text) {
        return false;
    }
    return DONE_MARKER_RE.test(text);
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
