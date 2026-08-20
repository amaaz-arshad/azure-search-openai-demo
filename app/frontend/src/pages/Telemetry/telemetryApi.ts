/** Typed client for the admin-gated `/internal-admin/telemetry/*` routes.
 *
 * Follows the same conventions as every other admin page folder: relative URLs, no auth headers (the
 * HttpOnly admin cookie rides along), an AbortSignal threaded through every list call, and the
 * server's message surfaced verbatim so `handleUnauthorizedError` can match its sentinel and bounce
 * to the login gate.
 */

const BASE = "/internal-admin/telemetry";

async function parseErrorMessage(response: Response, fallbackMessage: string): Promise<never> {
    const errorBody = (await response.json().catch(() => null)) as { message?: string } | null;
    throw new Error(errorBody?.message || fallbackMessage);
}

export interface TelemetryKpis {
    requests: number;
    errors: number;
    aborted: number;
    rejected: number;
    errorRate: number;
    estCostMicros: number;
    unpricedCount: number;
    tokensIn: number;
    tokensOut: number;
    tokensReasoning: number;
    tokensCached: number;
    avgMs: number;
    p50Ms: number | null;
    p90Ms: number | null;
    p95Ms: number | null;
    p99Ms: number | null;
}

export interface TelemetrySeriesPoint {
    bucket: string;
    requests: number;
    errors: number;
    aborted: number;
    rejected: number;
    estCostMicros: number;
    tokensIn: number;
    tokensOut: number;
    avgMs: number;
    p50Ms: number | null;
    p95Ms: number | null;
}

export interface TelemetrySplitPoint {
    bucket: string;
    chatbot?: string;
    model?: string;
    requests: number;
    estCostMicros: number;
    tokensIn: number;
    tokensOut: number;
}

export interface TelemetryFacetRow {
    chatbot?: string;
    model?: string;
    path?: string;
    requests: number;
    tokensIn: number;
    tokensOut: number;
    tokensReasoning: number;
    tokensCached: number;
    estCostMicros: number;
    unpricedCount: number;
    avgMs: number;
    maxMs: number;
    shareOfCost: number;
    shareOfRequests: number;
    p50Ms: number | null;
    p90Ms: number | null;
    p95Ms: number | null;
    p99Ms: number | null;
}

export interface TelemetryStepRow {
    path: string;
    step: string;
    type: string;
    calls: number;
    avgMs: number;
    totalMs: number;
    maxMs: number;
    tokensIn: number;
    tokensOut: number;
    p50Ms: number | null;
    p95Ms: number | null;
}

export interface TelemetrySummary {
    range: { from: string; to: string; granularity: string; resolvedGranularity: string };
    generatedAt: string;
    dataStartsAt: string | null;
    currency: string;
    kpis: TelemetryKpis;
    previousTotals: TelemetryKpis | null;
    noComparisonPeriod: boolean;
    series: TelemetrySeriesPoint[];
    seriesByChatbot: TelemetrySplitPoint[];
    seriesByModel: TelemetrySplitPoint[];
    byChatbot: TelemetryFacetRow[];
    byModel: TelemetryFacetRow[];
    byPath: TelemetryFacetRow[];
    byStep: TelemetryStepRow[];
    latencyHistogram: { fromMs: number; toMs: number | null; count: number }[];
    errors: { type: string; count: number; lastSeen: string | null; exampleTraceId: string | null }[];
    unpricedModels: { model: string; requests: number }[];
    approximate: boolean;
    maxRelativeError: number;
    minSamplesForPercentile: number;
    partial: { rollupDaysUsed: number; rawDaysUsed: number; daysMissing: number; daysEmpty: number; truncated: boolean };
}

export interface TelemetryRequestStep {
    index: number;
    name: string;
    type: string;
    ms: number;
    tokensIn: number;
    tokensOut: number;
}

export interface TelemetryRequestRow {
    traceId: string;
    day: string;
    blobName: string;
    startedAt: string;
    chatbot: string;
    effectiveChatbot: string | null;
    sourceChatbot: string | null;
    path: string;
    model: string | null;
    deployment: string | null;
    reasoningEffort: string | null;
    streaming: boolean;
    status: string;
    errorType: string | null;
    durationMs: number;
    tokensIn: number;
    tokensOut: number;
    tokensReasoning: number;
    tokensCached: number;
    estCostMicros: number | null;
    currency: string | null;
    priceVersion: string | null;
    steps: TelemetryRequestStep[];
    promptPreview: string;
}

export interface TelemetryRequestPage {
    rows: TelemetryRequestRow[];
    cursor: string | null;
    hasMore: boolean;
    scannedDays: number;
    currency: string;
}

export interface TelemetryRecordStep {
    index: number;
    name: string;
    type: string;
    startMs: number;
    durationMs: number;
    parent?: number;
    model?: string;
    deployment?: string;
    reasoningEffort?: string;
    costMicros?: number;
    error?: string;
    usage?: { promptTokens: number; completionTokens: number; reasoningTokens: number; cachedTokens: number; totalTokens: number };
    payload?: Record<string, unknown>;
}

export interface TelemetryRecord {
    schema: number;
    traceId: string;
    startedAt: string;
    finalizedAt: string;
    route: string;
    streaming: boolean;
    chatbot: { name: string | null; effectiveName: string | null; sourceName: string | null };
    path: string;
    model: string | null;
    deployment: string | null;
    reasoningEffort: string | null;
    status: string;
    durationMs: number;
    sessionId?: string;
    usage: { promptTokens: number; completionTokens: number; reasoningTokens: number; cachedTokens: number; totalTokens: number };
    cost: { micros: number | null; currency: string | null; priceVersion: string | null; unpriced: string[] };
    steps: TelemetryRecordStep[];
    messages?: { role: string; content: string; truncated?: boolean }[];
    systemPrompt?: { sha256: string; length: number; head: string };
    response?: { content: string; truncated?: boolean; finishReason?: string; citations?: string[]; followupQuestions?: string[] };
    sources?: { citation: string; title?: string; url?: string; kind?: string }[];
    overrides?: Record<string, unknown>;
    error?: { type: string; message: string; traceback: string };
}

export interface TelemetryFilters {
    chatbots: { name: string; displayName?: string; kind: string }[];
    models: string[];
    paths: string[];
    statuses: string[];
    dataStartsAt: string | null;
    currency: string;
    timezone: string;
    storesBodies: boolean;
}

export interface PricePayload {
    version: string;
    currency: string;
    prices: Record<string, { input: number; cachedInput: number; output: number; currency: string; source: string }>;
}

async function getJson<T>(path: string, signal?: AbortSignal, fallback = "Unable to load telemetry."): Promise<T> {
    const response = await fetch(`${BASE}${path}`, { signal });
    if (!response.ok) await parseErrorMessage(response, fallback);
    return (await response.json()) as T;
}

export function getTelemetrySummaryApi(query: string, signal?: AbortSignal): Promise<TelemetrySummary> {
    return getJson<TelemetrySummary>(`/summary?${query}`, signal, "Unable to load the telemetry summary.");
}

export function listTelemetryRequestsApi(query: string, signal?: AbortSignal): Promise<TelemetryRequestPage> {
    return getJson<TelemetryRequestPage>(`/requests?${query}`, signal, "Unable to load the request list.");
}

export function getTelemetryRequestApi(traceId: string, blobName: string, signal?: AbortSignal): Promise<TelemetryRecord> {
    return getJson<TelemetryRecord>(
        `/requests/${encodeURIComponent(traceId)}?blob=${encodeURIComponent(blobName)}`,
        signal,
        "Unable to load that request."
    );
}

export function getTelemetryFiltersApi(signal?: AbortSignal): Promise<TelemetryFilters> {
    return getJson<TelemetryFilters>("/filters", signal, "Unable to load the filter options.");
}

export function getTelemetryPricingApi(signal?: AbortSignal): Promise<PricePayload> {
    return getJson<PricePayload>("/pricing", signal, "Unable to load the price table.");
}

export async function saveTelemetryPricingApi(
    prices: Record<string, { input: number; cachedInput: number; output: number }>,
    note: string
): Promise<PricePayload> {
    const response = await fetch(`${BASE}/pricing`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prices, note })
    });
    if (!response.ok) await parseErrorMessage(response, "Unable to save the price table.");
    return (await response.json()) as PricePayload;
}

/**
 * Fetched into a Blob and clicked through a synthetic anchor rather than linked directly — the same
 * choice `hyroxVisitsApi.ts` makes, and for the same reason: an expired admin session must surface as
 * a normal error message, not as raw JSON in a new tab.
 */
export async function downloadTelemetryCsvApi(query: string): Promise<string> {
    const response = await fetch(`${BASE}/export.csv?${query}`);
    if (!response.ok) await parseErrorMessage(response, "Unable to download the CSV export.");

    const filename = `telemetry-${new URLSearchParams(query).get("view") ?? "chatbot"}.csv`;
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    // Revoking immediately races the download in some browsers.
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    return filename;
}

export function downloadTelemetryRecordUrl(traceId: string, blobName: string): string {
    return `${BASE}/requests/${encodeURIComponent(traceId)}.json?blob=${encodeURIComponent(blobName)}`;
}
