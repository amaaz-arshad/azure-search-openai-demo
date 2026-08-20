import styles from "./charts.module.css";

/**
 * The 40x18 trend line inside a KPI tile.
 *
 * Deliberately `aria-hidden`: it carries no number a reader could act on, and the tile's value and
 * delta already say everything it does. Announcing it would be noise.
 */
export function Sparkline({ values, color, width = 56, height = 18 }: { values: number[]; color: string; width?: number; height?: number }) {
    if (values.length < 2) return null;
    const max = Math.max(...values);
    const min = Math.min(...values);
    const span = max - min || 1;
    const step = width / (values.length - 1);
    const points = values.map((value, index) => `${index * step},${height - ((value - min) / span) * (height - 2) - 1}`);

    return (
        <svg width={width} height={height} className={styles.sparkline} aria-hidden="true" focusable="false">
            <polyline points={points.join(" ")} fill="none" stroke={color} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" />
        </svg>
    );
}

export interface StepSegment {
    key: string;
    label: string;
    ms: number;
    color: string;
    detail?: string;
}

/**
 * One stacked horizontal bar of step durations — the aggregate answer to "where did the seconds go".
 *
 * Used both for the per-path profile on the Overview tab and for the per-row sparkline in the request
 * table, so the colour key means the same thing in both places.
 */
export function StackedBar({ segments, height = 14, showLabels = false }: { segments: StepSegment[]; height?: number; showLabels?: boolean }) {
    const total = segments.reduce((sum, segment) => sum + Math.max(0, segment.ms), 0);
    if (total <= 0) return <span className={styles.stackedEmpty} aria-hidden="true" />;

    return (
        <span className={styles.stacked} style={{ height }}>
            {segments.map(segment => {
                const share = Math.max(0, segment.ms) / total;
                if (share <= 0) return null;
                return (
                    <span
                        key={segment.key}
                        className={styles.stackedSegment}
                        style={{ width: `${share * 100}%`, background: segment.color }}
                        title={`${segment.label}: ${Math.round(segment.ms)} ms${segment.detail ? ` (${segment.detail})` : ""}`}
                    >
                        {showLabels && share > 0.14 ? <span className={styles.stackedLabel}>{segment.label}</span> : null}
                    </span>
                );
            })}
        </span>
    );
}
