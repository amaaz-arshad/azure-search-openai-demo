/** Series colours for the telemetry charts.
 *
 * Two rules, both deliberate:
 *
 * **Red is reserved for errors** and is excluded from the rotation, so a chatbot never happens to be
 * drawn in the colour that means "something is wrong".
 *
 * **Colour is never the only channel.** Every legend carries text, every bar carries its value as
 * text, and stacked series additionally vary their hatch — so the charts stay readable for a
 * colour-blind reader and in a black-and-white print.
 *
 * Values live here as literals rather than as CSS custom properties because SVG `fill` needs a
 * concrete value at render time for the `<details>` data table's swatches to match; the page module
 * mirrors them as tokens for the surrounding chrome.
 */

export const SERIES_COLORS = [
    "#ac44c6", // accent purple, the admin shell's own
    "#0f9d76", // teal
    "#3d7dd8", // blue
    "#e08a1e", // amber
    "#7f2898", // accent dark
    "#4aa8b8", // cyan
    "#8e6bd4", // violet
    "#b3763f", // brown
    "#5d6b7a" // slate
] as const;

export const ERROR_COLOR = "#d4483b";
export const ABORTED_COLOR = "#e08a1e";
export const OK_COLOR = "#ac44c6";
export const REJECTED_COLOR = "#5d6b7a";
export const COST_LINE_COLOR = "#0f9d76";
export const MUTED_COLOR = "#9a90a3";

/** Step kinds are hued by what they are, so "was it the model or the index?" reads at a glance. */
export const STEP_TYPE_COLORS: Record<string, string> = {
    llm: "#ac44c6",
    embedding: "#3d7dd8",
    index: "#0f9d76",
    retrieval: "#4aa8b8",
    io: "#b3763f"
};

export const STATUS_COLORS: Record<string, string> = {
    ok: OK_COLOR,
    error: ERROR_COLOR,
    aborted: ABORTED_COLOR,
    rejected: REJECTED_COLOR
};

function hashString(value: string): number {
    let hash = 0;
    for (let index = 0; index < value.length; index += 1) {
        hash = (hash << 5) - hash + value.charCodeAt(index);
        hash |= 0;
    }
    return Math.abs(hash);
}

/**
 * Stable colours per key, with a collision pass over the keys actually on screen.
 *
 * Stable so a bot keeps its colour between the Overview and Costs tabs; collision-resolved so two
 * *visible* series can never share a hue just because their names happened to hash together.
 */
export function assignSeriesColors(keys: string[]): Record<string, string> {
    const assigned: Record<string, string> = {};
    const taken = new Set<string>();
    for (const key of keys) {
        let index = hashString(key) % SERIES_COLORS.length;
        for (let attempt = 0; attempt < SERIES_COLORS.length; attempt += 1) {
            const candidate = SERIES_COLORS[(index + attempt) % SERIES_COLORS.length];
            if (!taken.has(candidate)) {
                assigned[key] = candidate;
                taken.add(candidate);
                break;
            }
        }
        if (!assigned[key]) assigned[key] = SERIES_COLORS[index];
    }
    return assigned;
}

export function stepTypeColor(type: string | undefined): string {
    return STEP_TYPE_COLORS[type ?? ""] ?? MUTED_COLOR;
}

export function statusColor(status: string | undefined): string {
    return STATUS_COLORS[status ?? ""] ?? MUTED_COLOR;
}
