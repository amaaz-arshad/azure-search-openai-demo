import { useMemo, useState } from "react";

import { Bars, BarSeries } from "./charts/Bars";
import { HBars, HBarRow } from "./charts/HBars";
import { Histogram } from "./charts/Histogram";
import { StackedBar } from "./charts/Sparkline";
import { assignSeriesColors, COST_LINE_COLOR, ERROR_COLOR, statusColor, stepTypeColor } from "./charts/palette";
import { formatCost, formatCount, formatDay, formatDuration, formatExactCount, formatTimestamp } from "./charts/scales";
import { formatChatbotLabel } from "../shared/chatbotDisplay";
import styles from "./TelemetryPage.module.css";
import { TelemetrySummary } from "./telemetryApi";
import { GRANULARITY_OPTIONS, HOURLY_MAX_RANGE_DAYS, PATH_LABELS, rangeSpanDays } from "./useTelemetryQuery";

type GroupBy = "status" | "chatbot" | "model" | "path";
type Measure = "cost" | "requests" | "tokens" | "latency";

export interface OverviewTabProps {
    summary: TelemetrySummary;
    granularity: string;
    onGranularityChange: (value: string) => void;
    onSelectChatbot: (name: string) => void;
    onOpenTrace: (traceId: string) => void;
    onAnnounce: (message: string) => void;
}

/**
 * Pipeline order, so the profile bar reads left to right as the turn actually ran. Sorting by
 * duration instead would put the answer call first and make the bar look like a ranking rather than
 * a sequence.
 */
const STEP_ORDER = [
    "query_rewrite",
    "embedding",
    "image_embedding",
    "search",
    "agentic_retrieve",
    "agentic.query_planning",
    "agentic.search",
    "agentic.answer_synthesis",
    "wiki_index_read",
    "wiki_navigate",
    "wiki_pages_load",
    "answer"
];

function stepRank(step: string): number {
    const index = STEP_ORDER.indexOf(step);
    return index < 0 ? STEP_ORDER.length : index;
}

/** Top N series plus an "Other" roll-up — a legend with 22 entries helps nobody. */
function topSeries(rows: { key: string; total: number }[], limit = 6): { keys: string[]; hasOther: boolean } {
    const sorted = [...rows].sort((a, b) => b.total - a.total);
    return { keys: sorted.slice(0, limit).map(row => row.key), hasOther: sorted.length > limit };
}

export function OverviewTab({
    summary,
    granularity,
    onGranularityChange,
    onSelectChatbot,
    onOpenTrace,
    onAnnounce
}: OverviewTabProps) {
    const [groupBy, setGroupBy] = useState<GroupBy>("status");
    const [measure, setMeasure] = useState<Measure>("cost");

    const buckets = summary.series.map(point => point.bucket);
    const resolvedGranularity = summary.range.resolvedGranularity;
    const currency = summary.currency;

    // Hourly is the one bucket a rollup cannot serve, so the backend clamps it past a week. Offering
    // a control that silently does something else is worse than not offering it: grey it out and say
    // why. An hourly choice made on a narrow range is kept in the URL rather than rewritten, so
    // widening and narrowing the range again returns to it.
    const spanDays = rangeSpanDays(summary.range.from, summary.range.to);
    const hourlyAvailable = spanDays <= HOURLY_MAX_RANGE_DAYS;
    const hourlyClamped = granularity === "hour" && !hourlyAvailable;
    const activeGranularity = hourlyClamped ? "auto" : granularity;

    const chatbotColors = useMemo(
        () => assignSeriesColors(summary.byChatbot.map(row => row.chatbot ?? "")),
        [summary.byChatbot]
    );
    const modelColors = useMemo(() => assignSeriesColors(summary.byModel.map(row => row.model ?? "")), [summary.byModel]);

    const trafficSeries: BarSeries[] = useMemo(() => {
        if (groupBy === "status") {
            return [
                { key: "ok", label: "Success", color: statusColor("ok"), values: summary.series.map(p => Math.max(0, p.requests - p.errors - p.aborted - p.rejected)) },
                { key: "error", label: "Error", color: statusColor("error"), values: summary.series.map(p => p.errors) },
                { key: "aborted", label: "Abandoned", color: statusColor("aborted"), values: summary.series.map(p => p.aborted) },
                { key: "rejected", label: "Rejected", color: statusColor("rejected"), values: summary.series.map(p => p.rejected) }
            ].filter(series => series.values.some(value => value > 0));
        }

        const split = groupBy === "chatbot" ? summary.seriesByChatbot : groupBy === "model" ? summary.seriesByModel : [];
        if (groupBy === "path" || split.length === 0) {
            // The API does not split the series by path, so fall back to a single total series rather
            // than drawing something that claims a breakdown it does not have.
            return [{ key: "requests", label: "Requests", color: statusColor("ok"), values: summary.series.map(p => p.requests) }];
        }

        const keyOf = (point: { chatbot?: string; model?: string }) => (groupBy === "chatbot" ? point.chatbot : point.model) ?? "";
        const totals = new Map<string, number>();
        for (const point of split) totals.set(keyOf(point), (totals.get(keyOf(point)) ?? 0) + point.requests);
        const { keys, hasOther } = topSeries([...totals].map(([key, total]) => ({ key, total })));
        const colors = groupBy === "chatbot" ? chatbotColors : modelColors;

        const series: BarSeries[] = keys.map(key => ({
            key,
            label: groupBy === "chatbot" ? formatChatbotLabel(key) : key,
            color: colors[key] ?? "#9a90a3",
            values: buckets.map(bucket => split.find(point => point.bucket === bucket && keyOf(point) === key)?.requests ?? 0)
        }));
        if (hasOther) {
            series.push({
                key: "__other",
                label: "Other",
                color: "#9a90a3",
                values: buckets.map(bucket => {
                    const all = split.filter(point => point.bucket === bucket).reduce((sum, point) => sum + point.requests, 0);
                    const shown = series.reduce((sum, item) => sum + (item.values[buckets.indexOf(bucket)] ?? 0), 0);
                    return Math.max(0, all - shown);
                })
            });
        }
        return series;
    }, [buckets, chatbotColors, groupBy, modelColors, summary]);

    const chatbotRows: HBarRow[] = summary.byChatbot.map(row => {
        const name = row.chatbot ?? "";
        const value =
            measure === "cost"
                ? row.estCostMicros
                : measure === "requests"
                  ? row.requests
                  : measure === "tokens"
                    ? row.tokensIn + row.tokensOut
                    : (row.p50Ms ?? row.avgMs);
        const formatted =
            measure === "cost"
                ? `est. ${formatCost(row.estCostMicros, currency)}`
                : measure === "requests"
                  ? formatExactCount(row.requests)
                  : measure === "tokens"
                    ? formatCount(row.tokensIn + row.tokensOut)
                    : row.p50Ms === null
                      ? `${formatExactCount(row.requests)} requests`
                      : formatDuration(row.p50Ms);
        return {
            key: name,
            label: formatChatbotLabel(name),
            value,
            color: chatbotColors[name] ?? "#9a90a3",
            formatted,
            detail: measure === "cost" ? `${formatExactCount(row.requests)} requests` : undefined,
            badge: row.unpricedCount > 0 && measure === "cost" ? "partly unpriced" : undefined
        };
    });

    const modelRows: HBarRow[] = summary.byModel.map(row => ({
        key: row.model ?? "",
        label: row.model ?? "unknown",
        value: row.estCostMicros,
        color: modelColors[row.model ?? ""] ?? "#9a90a3",
        formatted: `est. ${formatCost(row.estCostMicros, currency)}`,
        detail: `${formatCount(row.tokensIn)} in / ${formatCount(row.tokensOut)} out`,
        outline: row.unpricedCount > 0 && row.estCostMicros === 0,
        badge: row.unpricedCount > 0 ? "unpriced" : undefined
    }));

    const stepsByPath = useMemo(() => {
        const grouped = new Map<string, typeof summary.byStep>();
        for (const step of summary.byStep) {
            const list = grouped.get(step.path) ?? [];
            list.push(step);
            grouped.set(step.path, list);
        }
        return [...grouped.entries()].map(([path, steps]) => {
            // The agentic activities run INSIDE the retrieve call, so charting both would count that
            // time twice and make agentic look about twice as slow as it is. Prefer the breakdown
            // where it exists, and fall back to the parent where it does not.
            const hasChildren = steps.some(step => step.step.startsWith("agentic."));
            const kept = hasChildren ? steps.filter(step => step.step !== "agentic_retrieve") : steps;
            return [path, [...kept].sort((a, b) => stepRank(a.step) - stepRank(b.step))] as const;
        });
    }, [summary.byStep]);

    return (
        <div className={styles.tabBody}>
            <Bars
                title="Traffic and cost over time"
                subtitle="Columns are requests on the left axis; the line is estimated cost on the right."
                summary={`Requests and estimated cost per ${resolvedGranularity} from ${summary.range.from} to ${summary.range.to}.`}
                buckets={buckets}
                granularity={resolvedGranularity}
                series={trafficSeries}
                blankBefore={summary.dataStartsAt ?? undefined}
                line={{
                    key: "cost",
                    label: "Est. cost",
                    color: COST_LINE_COLOR,
                    values: summary.series.map(point => point.estCostMicros / 1_000_000),
                    format: value => formatCost(value * 1_000_000, currency)
                }}
                onAnnounce={onAnnounce}
                actions={
                    <>
                        <div className={styles.segmentedSmall} role="group" aria-label="Group the columns by">
                            {(["status", "chatbot", "model", "path"] as GroupBy[]).map(option => (
                                <button
                                    key={option}
                                    type="button"
                                    className={styles.segment}
                                    aria-pressed={groupBy === option}
                                    onClick={() => setGroupBy(option)}
                                >
                                    {option === "status"
                                        ? "Status"
                                        : option === "chatbot"
                                          ? "Chatbot"
                                          : option === "model"
                                            ? "Model"
                                            : "Path"}
                                </button>
                            ))}
                        </div>
                        <div className={styles.segmentedSmall} role="group" aria-label="Bucket size">
                            {GRANULARITY_OPTIONS.map(option => {
                                const disabled = option.value === "hour" && !hourlyAvailable;
                                return (
                                    <button
                                        key={option.value}
                                        type="button"
                                        className={styles.segment}
                                        aria-pressed={activeGranularity === option.value}
                                        disabled={disabled}
                                        title={
                                            disabled
                                                ? `Hourly needs a range of ${HOURLY_MAX_RANGE_DAYS} days or less.`
                                                : undefined
                                        }
                                        onClick={() => onGranularityChange(option.value)}
                                    >
                                        {option.label}
                                    </button>
                                );
                            })}
                        </div>
                        {hourlyClamped ? (
                            <span className={styles.chartNote}>
                                Hourly needs a range of {HOURLY_MAX_RANGE_DAYS} days or less.
                            </span>
                        ) : null}
                    </>
                }
            />

            <div className={styles.chartGrid}>
                <HBars
                    title="By chatbot"
                    subtitle="Click a row to narrow the whole page to that bot."
                    summary={`Each chatbot's ${measure} over the selected range.`}
                    rows={chatbotRows}
                    valueColumn={measure === "cost" ? `Estimated cost (${currency})` : measure === "requests" ? "Requests" : measure === "tokens" ? "Tokens" : "Median latency"}
                    onSelect={onSelectChatbot}
                    emptyMessage="No requests from any chatbot in this range."
                    actions={
                        <div className={styles.segmentedSmall} role="group" aria-label="Measure">
                            {(["cost", "requests", "tokens", "latency"] as Measure[]).map(option => (
                                <button
                                    key={option}
                                    type="button"
                                    className={styles.segment}
                                    aria-pressed={measure === option}
                                    onClick={() => setMeasure(option)}
                                >
                                    {option === "cost" ? "Cost" : option === "requests" ? "Requests" : option === "tokens" ? "Tokens" : "Latency"}
                                </button>
                            ))}
                        </div>
                    }
                    footnote={
                        measure === "cost"
                            ? "Estimated from recorded tokens. Only this figure can be split by chatbot — Azure billing has no chatbot dimension."
                            : undefined
                    }
                />

                <HBars
                    title="By model"
                    summary="Estimated cost per model over the selected range."
                    rows={modelRows}
                    valueColumn={`Estimated cost (${currency})`}
                    emptyMessage="No model usage in this range."
                    footnote={
                        summary.unpricedModels.length
                            ? `${summary.unpricedModels.length} model(s) have no price yet, so their requests are excluded from every cost figure.`
                            : undefined
                    }
                />
            </div>

            <section className={styles.panelInner}>
                <header className={styles.chartHeaderRow}>
                    <div>
                        <h3 className={styles.sectionTitle}>Where the time goes</h3>
                        <p className={styles.sectionSubtitle}>
                            Median duration of each step, per retrieval path. Purple is a model call, teal the search
                            index, blue an embedding — so &quot;model or index?&quot; reads at a glance.
                        </p>
                    </div>
                </header>
                {stepsByPath.length === 0 ? (
                    <p className={styles.chartEmptyInline}>No step timings recorded in this range.</p>
                ) : (
                    <div className={styles.stepProfile}>
                        {stepsByPath.map(([path, ordered]) => {
                            const totalCalls = Math.max(...ordered.map(step => step.calls));
                            return (
                                <div key={path} className={styles.stepRow}>
                                    <span className={styles.stepPath}>{PATH_LABELS[path] ?? path}</span>
                                    <StackedBar
                                        height={18}
                                        showLabels
                                        segments={ordered.map(step => ({
                                            key: step.step,
                                            label: step.step.replace("agentic.", ""),
                                            ms: step.avgMs,
                                            color: stepTypeColor(step.type),
                                            detail: `${formatExactCount(step.calls)} calls`
                                        }))}
                                    />
                                    <span className={styles.stepMeta}>
                                        {formatDuration(ordered.reduce((sum, step) => sum + step.avgMs, 0))} avg
                                        <span className={styles.stepMetaMuted}> / n = {formatExactCount(totalCalls)}</span>
                                    </span>
                                </div>
                            );
                        })}
                    </div>
                )}
            </section>

            <div className={styles.chartGrid}>
                <Histogram
                    title="Latency distribution"
                    summary="How long requests took, bucketed."
                    buckets={summary.latencyHistogram}
                    medianMs={summary.kpis.p50Ms}
                    p95Ms={summary.kpis.p95Ms}
                    color={statusColor("ok")}
                    footnote={`Percentiles are interpolated from stored buckets, accurate to about ${(summary.maxRelativeError * 100).toFixed(0)}%. Suppressed below ${summary.minSamplesForPercentile} requests.`}
                />

                {summary.errors.length > 0 ? (
                    <section className={styles.panelInner}>
                        <h3 className={styles.sectionTitle}>Errors</h3>
                        <div className={styles.tableWrap}>
                            <table className={styles.table}>
                                <thead>
                                    <tr>
                                        <th scope="col">Type</th>
                                        <th scope="col">Count</th>
                                        <th scope="col">Last seen</th>
                                        <th scope="col" />
                                    </tr>
                                </thead>
                                <tbody>
                                    {summary.errors.map(error => (
                                        <tr key={error.type}>
                                            <td>
                                                <span className={styles.errorDot} style={{ background: ERROR_COLOR }} aria-hidden="true" />
                                                {error.type}
                                            </td>
                                            <td>{formatExactCount(error.count)}</td>
                                            {/* A rollup only knows the day, so rendering it as a
                                                timestamp would invent a midnight that never happened. */}
                                            <td>
                                                {!error.lastSeen
                                                    ? "—"
                                                    : /^\d{4}-\d{2}-\d{2}$/.test(error.lastSeen)
                                                      ? formatDay(error.lastSeen)
                                                      : formatTimestamp(error.lastSeen)}
                                            </td>
                                            <td>
                                                {error.exampleTraceId ? (
                                                    <button
                                                        type="button"
                                                        className={styles.linkButton}
                                                        onClick={() => onOpenTrace(error.exampleTraceId as string)}
                                                    >
                                                        See an example
                                                    </button>
                                                ) : null}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </section>
                ) : null}
            </div>
        </div>
    );
}
