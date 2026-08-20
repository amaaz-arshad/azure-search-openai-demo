import { Sparkline } from "./charts/Sparkline";
import { formatCost, formatCount, formatDuration, formatExactCount, formatPercent } from "./charts/scales";
import { COST_LINE_COLOR, ERROR_COLOR, OK_COLOR } from "./charts/palette";
import styles from "./TelemetryPage.module.css";
import { TelemetrySummary } from "./telemetryApi";

/**
 * The first screenful's answer to "is anything wrong, and what are we spending".
 *
 * Two rules run through every tile. A delta is rendered with a glyph AND a sign AND a colour, so it
 * is never colour alone; and a value the backend could not compute renders as a stated condition
 * ("no comparison period", "under N requests") rather than as a zero, because a zero on a cost
 * dashboard reads as a fact.
 */

export interface KpiRowProps {
    summary: TelemetrySummary;
    onSelectErrors: () => void;
    onSelectCosts: () => void;
}

function Delta({ current, previous, invert }: { current: number; previous: number | null | undefined; invert?: boolean }) {
    if (previous === null || previous === undefined) return null;
    if (previous === 0 && current === 0) return <span className={styles.kpiDeltaFlat}>no change</span>;
    if (previous === 0) return <span className={styles.kpiDeltaFlat}>new</span>;
    const change = (current - previous) / previous;
    if (Math.abs(change) < 0.005) return <span className={styles.kpiDeltaFlat}>no change</span>;
    const rising = change > 0;
    // "Good" depends on the metric: more requests is neutral-to-good, more errors is bad.
    const tone = invert ? (rising ? styles.kpiDeltaBad : styles.kpiDeltaGood) : styles.kpiDeltaNeutral;
    return (
        <span className={`${styles.kpiDelta} ${tone}`}>
            <span aria-hidden="true">{rising ? "\u25b2" : "\u25bc"}</span> {rising ? "+" : ""}
            {(change * 100).toFixed(0)}%
        </span>
    );
}

export function KpiRow({ summary, onSelectErrors, onSelectCosts }: KpiRowProps) {
    const { kpis, previousTotals, currency } = summary;
    const requestSeries = summary.series.map(point => point.requests);
    const costSeries = summary.series.map(point => point.estCostMicros);

    const errorTone = kpis.errorRate > 0.15 ? styles.kpiTileDanger : kpis.errorRate > 0.05 ? styles.kpiTileWarning : "";
    const costPerRequest = kpis.requests > 0 ? Math.round(kpis.estCostMicros / kpis.requests) : null;
    const previousCostPerRequest =
        previousTotals && previousTotals.requests > 0
            ? Math.round(previousTotals.estCostMicros / previousTotals.requests)
            : null;

    return (
        <div className={styles.kpiRow}>
            <div className={styles.kpiTile}>
                <span className={styles.kpiLabel}>Requests</span>
                <span className={styles.kpiValue}>{formatCount(kpis.requests)}</span>
                <span className={styles.kpiFooter}>
                    <Delta current={kpis.requests} previous={previousTotals?.requests} />
                    {summary.noComparisonPeriod ? <span className={styles.kpiDeltaFlat}>no comparison period</span> : null}
                </span>
                <Sparkline values={requestSeries} color={OK_COLOR} />
            </div>

            <button type="button" className={`${styles.kpiTile} ${styles.kpiTileButton}`} onClick={onSelectCosts}>
                <span className={styles.kpiLabel}>Estimated cost</span>
                <span className={styles.kpiValue}>{formatCost(kpis.estCostMicros, currency)}</span>
                <span className={styles.kpiFooter}>
                    <Delta current={kpis.estCostMicros} previous={previousTotals?.estCostMicros} />
                    <span className={styles.kpiHint}>recorded tokens x price table</span>
                </span>
                <Sparkline values={costSeries} color={COST_LINE_COLOR} />
            </button>

            <div className={styles.kpiTile}>
                <span className={styles.kpiLabel}>Cost per request</span>
                <span className={styles.kpiValue}>{formatCost(costPerRequest, currency)}</span>
                <span className={styles.kpiFooter}>
                    <Delta current={costPerRequest ?? 0} previous={previousCostPerRequest} invert />
                    <span className={styles.kpiHint}>average across the range</span>
                </span>
            </div>

            <div className={styles.kpiTile}>
                <span className={styles.kpiLabel}>Tokens</span>
                <span className={styles.kpiValue}>{formatCount(kpis.tokensIn + kpis.tokensOut)}</span>
                <span className={styles.tokenBar} aria-hidden="true">
                    <span
                        style={{
                            width: `${(kpis.tokensIn / Math.max(1, kpis.tokensIn + kpis.tokensOut)) * 100}%`,
                            background: OK_COLOR
                        }}
                    />
                    <span style={{ flex: 1, background: "#7f2898" }} />
                </span>
                <span className={styles.kpiFooter}>
                    <span className={styles.kpiHint}>
                        {formatCount(kpis.tokensIn)} in / {formatCount(kpis.tokensOut)} out
                        {kpis.tokensCached ? ` / ${formatCount(kpis.tokensCached)} cached` : ""}
                    </span>
                </span>
            </div>

            <div className={styles.kpiTile}>
                <span className={styles.kpiLabel}>Median latency</span>
                <span className={styles.kpiValue}>{formatDuration(kpis.p50Ms)}</span>
                <span className={styles.kpiFooter}>
                    <span className={styles.kpiHint}>
                        {kpis.p95Ms === null
                            ? `under ${summary.minSamplesForPercentile} requests`
                            : `p95 ${formatDuration(kpis.p95Ms)}`}
                    </span>
                </span>
            </div>

            <button type="button" className={`${styles.kpiTile} ${styles.kpiTileButton} ${errorTone}`} onClick={onSelectErrors}>
                <span className={styles.kpiLabel}>Error rate</span>
                <span className={styles.kpiValue}>{formatPercent(kpis.errorRate)}</span>
                <span className={styles.kpiFooter}>
                    <Delta current={kpis.errorRate} previous={previousTotals?.errorRate} invert />
                    <span className={styles.kpiHint}>
                        {kpis.errorRate > 0.05 ? "elevated \u2014 " : ""}
                        {formatExactCount(kpis.errors)} of {formatExactCount(kpis.requests)}
                    </span>
                </span>
                <Sparkline values={summary.series.map(point => point.errors)} color={ERROR_COLOR} />
            </button>
        </div>
    );
}
