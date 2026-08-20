import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";

/**
 * The page's entire filter state lives in the URL.
 *
 * Not in component state: an operator who has narrowed to one bot, one model and an error status is
 * holding a question, and that question has to survive a reload and be shareable with whoever they
 * are about to ask about it. It also means the browser Back button does what it looks like it does.
 */

export type TelemetryView = "overview" | "costs" | "requests";

export interface TelemetryQueryState {
    view: TelemetryView;
    range: string;
    from: string;
    to: string;
    granularity: string;
    chatbots: string[];
    models: string[];
    paths: string[];
    status: string;
    search: string;
}

export const DEFAULT_RANGE = "7d";

export const RANGE_OPTIONS = [
    { value: "24h", label: "24 h" },
    { value: "7d", label: "7 d" },
    { value: "30d", label: "30 d" },
    { value: "90d", label: "90 d" },
    { value: "month", label: "This month" },
    { value: "all", label: "All time" }
] as const;

/**
 * Bucket width for the traffic chart. It lives in the URL with the filters so a shared link renders
 * the same picture, but it is NOT a filter: it changes one chart's x axis and nothing else, which is
 * why its control sits on that chart rather than in the page-level filter bar.
 */
export const GRANULARITY_OPTIONS = [
    { value: "auto", label: "Auto" },
    { value: "hour", label: "Hourly" },
    { value: "day", label: "Daily" },
    { value: "week", label: "Weekly" },
    { value: "month", label: "Monthly" }
] as const;

/**
 * Widest range Hourly is offered for. Must stay in lockstep with `HOURLY_MAX_DAYS` in
 * `core/telemetry/aggregate.py`: the backend clamps an hourly range past it (an hour axis cannot come
 * from a rollup, so it costs one raw day listing per day), and this constant is what greys the
 * control out instead of letting the clamp happen silently.
 */
export const HOURLY_MAX_RANGE_DAYS = 7;

/** Inclusive day count, matching the backend's `span_days`. */
export function rangeSpanDays(from: string, to: string): number {
    const start = Date.parse(`${from}T00:00:00Z`);
    const end = Date.parse(`${to}T00:00:00Z`);
    if (!Number.isFinite(start) || !Number.isFinite(end)) return Number.POSITIVE_INFINITY;
    return Math.round((end - start) / 86_400_000) + 1;
}

/** Rows per page in the request explorer. The API caps `limit` at 200, so all of these are servable. */
export const PAGE_SIZE_OPTIONS = [25, 50, 100] as const;
export const DEFAULT_PAGE_SIZE = 50;

export const STATUS_OPTIONS = [
    { value: "all", label: "All" },
    { value: "ok", label: "Success" },
    { value: "error", label: "Errors" },
    { value: "aborted", label: "Abandoned" },
    { value: "rejected", label: "Rejected" }
] as const;

export const PATH_LABELS: Record<string, string> = {
    classic: "Classic search",
    agentic: "Agentic retrieval",
    "agentic-web": "Agentic (web answer)",
    wiki: "LLM wiki",
    assessment: "Assessment",
    unknown: "Unknown"
};

function readList(params: URLSearchParams, key: string): string[] {
    const raw = params.get(key);
    if (!raw) return [];
    return raw
        .split(",")
        .map(value => value.trim())
        .filter(Boolean);
}

export function useTelemetryQuery() {
    const [searchParams, setSearchParams] = useSearchParams();

    const state = useMemo<TelemetryQueryState>(
        () => ({
            view: (searchParams.get("view") as TelemetryView) || "overview",
            range: searchParams.get("range") || DEFAULT_RANGE,
            from: searchParams.get("from") || "",
            to: searchParams.get("to") || "",
            granularity: searchParams.get("granularity") || "auto",
            chatbots: readList(searchParams, "chatbot"),
            models: readList(searchParams, "model"),
            paths: readList(searchParams, "path"),
            status: searchParams.get("status") || "all",
            search: searchParams.get("q") || ""
        }),
        [searchParams]
    );

    const update = useCallback(
        (patch: Partial<TelemetryQueryState>) => {
            setSearchParams(
                previous => {
                    const next = new URLSearchParams(previous);
                    const write = (key: string, value: string | undefined, fallback = "") => {
                        if (value === undefined) return;
                        if (!value || value === fallback) next.delete(key);
                        else next.set(key, value);
                    };
                    write("view", patch.view, "overview");
                    write("range", patch.range, DEFAULT_RANGE);
                    write("from", patch.from);
                    write("to", patch.to);
                    write("granularity", patch.granularity, "auto");
                    write("status", patch.status, "all");
                    write("q", patch.search);
                    if (patch.chatbots) write("chatbot", patch.chatbots.join(","));
                    if (patch.models) write("model", patch.models.join(","));
                    if (patch.paths) write("path", patch.paths.join(","));
                    // A custom range and a named range are mutually exclusive; keeping both would let
                    // the two controls disagree about what is on screen.
                    if (patch.range) {
                        next.delete("from");
                        next.delete("to");
                    }
                    if (patch.from || patch.to) next.delete("range");
                    return next;
                },
                { replace: true }
            );
        },
        [setSearchParams]
    );

    const reset = useCallback(() => {
        setSearchParams(
            previous => {
                const next = new URLSearchParams();
                const view = previous.get("view");
                if (view) next.set("view", view);
                return next;
            },
            { replace: true }
        );
    }, [setSearchParams]);

    /** The query string the API takes. Only non-default facets are sent. */
    const apiQuery = useMemo(() => {
        const params = new URLSearchParams();
        if (state.from && state.to) {
            params.set("from", state.from);
            params.set("to", state.to);
        } else {
            params.set("range", state.range);
        }
        if (state.granularity !== "auto") params.set("granularity", state.granularity);
        if (state.chatbots.length) params.set("chatbot", state.chatbots.join(","));
        if (state.models.length) params.set("model", state.models.join(","));
        if (state.paths.length) params.set("path", state.paths.join(","));
        if (state.status !== "all") params.set("status", state.status);
        return params;
    }, [state]);

    // Granularity is deliberately absent: it is a chart display option, not a filter, so it must not
    // light up "Reset filters". `reset` still clears it, because it clears the whole query string.
    const hasActiveFilters =
        state.chatbots.length > 0 ||
        state.models.length > 0 ||
        state.paths.length > 0 ||
        state.status !== "all" ||
        state.range !== DEFAULT_RANGE ||
        Boolean(state.from) ||
        Boolean(state.search);

    const toggleInList = useCallback(
        (key: "chatbots" | "models" | "paths", value: string) => {
            const current = state[key];
            const next = current.includes(value) ? current.filter(item => item !== value) : [...current, value];
            update({ [key]: next } as Partial<TelemetryQueryState>);
        },
        [state, update]
    );

    return { state, update, reset, apiQuery, hasActiveFilters, toggleInList };
}
