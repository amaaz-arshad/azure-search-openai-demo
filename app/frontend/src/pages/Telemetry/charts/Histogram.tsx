import { ChartFrame, ChartTable } from "./ChartFrame";
import { formatCount, formatDuration, linearScale, niceCeiling } from "./scales";
import styles from "./charts.module.css";

/**
 * Latency distribution, with the median and p95 drawn as labelled reference lines.
 *
 * The backend stores 72 log-spaced buckets for percentile accuracy but folds them to a dozen for
 * display: nobody reads a 72-bar chart, and the storage resolution exists for the arithmetic rather
 * than for the picture.
 */

export interface HistogramBucket {
    fromMs: number;
    toMs: number | null;
    count: number;
}

export interface HistogramProps {
    title: string;
    subtitle?: string;
    summary: string;
    buckets: HistogramBucket[];
    medianMs?: number | null;
    p95Ms?: number | null;
    color: string;
    footnote?: React.ReactNode;
}

const MARGIN = { top: 16, right: 12, bottom: 42, left: 44 };

function bucketLabel(bucket: HistogramBucket): string {
    if (bucket.toMs === null) return `${Math.round(bucket.fromMs / 1000)} s+`;
    if (bucket.fromMs === 0) return `< ${bucket.toMs / 1000} s`;
    return `${bucket.fromMs / 1000}-${bucket.toMs / 1000} s`;
}

export function Histogram({ title, subtitle, summary, buckets, medianMs, p95Ms, color, footnote }: HistogramProps) {
    const max = niceCeiling(Math.max(1, ...buckets.map(bucket => bucket.count)));
    const total = buckets.reduce((sum, bucket) => sum + bucket.count, 0);

    const table: ChartTable = {
        columns: ["Duration", "Requests"],
        rows: buckets.map(bucket => [bucketLabel(bucket), formatCount(bucket.count)])
    };

    return (
        <ChartFrame
            title={title}
            subtitle={subtitle}
            summary={summary}
            height={220}
            table={table}
            isEmpty={total === 0}
            footnote={footnote}
        >
            {(width, height) => {
                const plotWidth = Math.max(10, width - MARGIN.left - MARGIN.right);
                const plotHeight = Math.max(10, height - MARGIN.top - MARGIN.bottom);
                const step = plotWidth / Math.max(1, buckets.length);
                const y = linearScale([0, max], [plotHeight, 0]);

                // The reference lines are positioned against the same folded bucket edges the bars
                // use, so a marker can never sit somewhere the bars say nothing happened.
                const positionFor = (ms: number) => {
                    const index = buckets.findIndex(bucket => (bucket.toMs === null ? true : ms < bucket.toMs));
                    if (index < 0) return plotWidth;
                    const bucket = buckets[index];
                    const span = (bucket.toMs ?? bucket.fromMs * 2) - bucket.fromMs || 1;
                    const within = Math.max(0, Math.min(1, (ms - bucket.fromMs) / span));
                    return index * step + within * step;
                };

                return (
                    <svg width={width} height={height} role="img" aria-label={summary} className={styles.plot}>
                        <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
                            {y.ticks(3).map(tick => (
                                <g key={tick}>
                                    <line x1={0} x2={plotWidth} y1={y(tick)} y2={y(tick)} className={styles.gridLine} />
                                    <text x={-8} y={y(tick)} dy="0.32em" textAnchor="end" className={styles.axisLabel}>
                                        {formatCount(tick)}
                                    </text>
                                </g>
                            ))}

                            {buckets.map((bucket, index) => {
                                const barHeight = Math.max(0, plotHeight - y(bucket.count));
                                return (
                                    <rect
                                        key={index}
                                        x={index * step + 2}
                                        y={plotHeight - barHeight}
                                        width={Math.max(1, step - 4)}
                                        height={barHeight}
                                        fill={color}
                                        rx={3}
                                    >
                                        <title>{`${bucketLabel(bucket)}: ${formatCount(bucket.count)} requests`}</title>
                                    </rect>
                                );
                            })}

                            {[
                                { value: medianMs, label: "median" },
                                { value: p95Ms, label: "p95" }
                            ].map(marker =>
                                marker.value === null || marker.value === undefined ? null : (
                                    <g key={marker.label} transform={`translate(${positionFor(marker.value)},0)`}>
                                        <line y1={0} y2={plotHeight} className={styles.referenceLine} />
                                        <text y={-4} textAnchor="middle" className={styles.referenceLabel}>
                                            {marker.label} {formatDuration(marker.value)}
                                        </text>
                                    </g>
                                )
                            )}

                            {buckets.map((bucket, index) =>
                                index % 2 === 0 ? (
                                    <text
                                        key={`label-${index}`}
                                        x={index * step + step / 2}
                                        y={plotHeight + 18}
                                        textAnchor="middle"
                                        className={styles.axisLabel}
                                    >
                                        {bucketLabel(bucket)}
                                    </text>
                                ) : null
                            )}
                        </g>
                    </svg>
                );
            }}
        </ChartFrame>
    );
}
