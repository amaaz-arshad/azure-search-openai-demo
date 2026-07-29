// Hidden control markers in an assessment message ([[PLAN ...]] run anchor, [[MODULE m=.. attempt=..]]
// module-attempt anchor, [[SCORE ...]], [[PROV ...]] (the backend's pinned first-attempt verdict, written
// when the single correction is offered so a declined correction cannot be re-graded upward), the model's
// [[ASK]] placement token, the backend's [[ASKED q=K]] record, the backend's [[MODPASS m=..]] /
// [[MODFAIL m=..]] module-boundary signals, the model's final-turn [[SUMMARY]] separator, the backend's
// [[BREAK]] bubble split point, the backend's [[PROGRESS value=N]] final-pass signal, and the backend's
// [[DONE]] completion signal). They must stay in the stored message so they replay into the next request's
// history (the backend reconstructs the authoritative per-module tally + which question was already
// presented + the pinned verdict + which module boundary the learner is at from them), but they must never
// be shown to the learner. This strips them for display only — see ChatbotAnswer's `preprocessAnswerText`.
// ASKED is listed before ASK, and MODPASS/MODFAIL before MODULE, so the `\b` boundary matches the longer
// name as a whole.
const ASSESSMENT_MARKER_RE =
    /\[\[\s*(?:PLAN|MODULE|SCORE|PROV|ASKED|ASK|MODPASS|MODFAIL|SUMMARY|BREAK|PROGRESS|DONE)\b[^\]]*\]\]/gi;

// The backend emits these once at a module boundary (not the final module): MODPASS when the learner
// passed the module (the frontend shows a "Continue to next module" button) and MODFAIL when they did
// not reach 80% (the frontend shows a "Retry module" button). They replay from history, so a reopened
// session at a boundary shows the right button.
const MODULE_PASS_MARKER_RE = /\[\[\s*MODPASS\b[^\]]*\]\]/i;
const MODULE_FAIL_MARKER_RE = /\[\[\s*MODFAIL\b[^\]]*\]\]/i;

// The backend emits this once, only on a passed completion, to hand the result back to the
// Lemon app (fired as lemon://save_progress?value=N — see lemonBridge.reportLemonProgress).
const PROGRESS_MARKER_RE = /\[\[\s*PROGRESS\b[^\]]*\bvalue\s*=\s*(\d+)[^\]]*\]\]/i;

// The backend joins end-of-assessment sections (final question's evaluation, the final
// module's own result line, cumulative result, topic summary, motivational message, closing
// message) with [[BREAK]] so each renders as its own chat bubble. The count is not fixed —
// splitAssessmentBubbles renders one bubble per non-empty [[BREAK]] segment.
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

// True once the assessment has completed, detected via the backend's hidden [[DONE]] marker on the
// final message (emitted only when the final module is passed — completion always means a pass). Replays
// from history, so a reopened completed session is also detected. Used to remove the question input.
export function hasAssessmentDoneMarker(text: string): boolean {
    if (!text) {
        return false;
    }
    return DONE_MARKER_RE.test(text);
}

// True when this message is a passed-module boundary (not the final module): the learner should be shown
// a "Continue to next module" button. Checked on the latest message only.
export function hasModulePassMarker(text: string): boolean {
    if (!text) {
        return false;
    }
    return MODULE_PASS_MARKER_RE.test(text);
}

// True when this message is a failed-module boundary: the learner should be shown a "Retry module"
// button. Checked on the latest message only.
export function hasModuleFailMarker(text: string): boolean {
    if (!text) {
        return false;
    }
    return MODULE_FAIL_MARKER_RE.test(text);
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
