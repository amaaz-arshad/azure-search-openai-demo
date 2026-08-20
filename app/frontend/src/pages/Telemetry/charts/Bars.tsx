import { useState } from "react";

import { ChartFrame, ChartTable, ChartTooltip, LegendItem, TooltipState, usePlotKeyboard } from "./ChartFrame";
import { bandScale, formatBucket, formatCount, linearScale, niceCeiling, thinTicks } from "./scales";
import styles from "./charts.module.css";

/**
 * Stacked or grouped columns, with an optional line overlaid on its own right-hand axis.
 *
 * One component covers both the traffic-and-cost chart (columns = requests, line = cost) and the
 * estimated-versus-actual chart (grouped columns, line = ratio), because they are the same geometry
 * with different data. The second axis is drawn in the line's own colour so nobody reads the line
 * against the left scale.
 */

export interface BarSeries {
    key: string;
    label: string;
    color: string;
    values: number[];
    /** Drawn with a diagonal hatch as well as its colour — used for provisional/lagging data. */
    hatched?: boolean;
}

export interface BarLine {
    key: string;
    label: string;
    color: string;
    values: (number | null)[];
    format: (value: number) => string;
    /** A dashed horizontal reference, e.g. the 1.0 line on a ratio axis. */
    reference?: number;
}

export interface BarsProps {
    title: string;
    subtitle?: string;
    summary: string;
    buckets: string[];
    granularity: string;
    series: BarSeries[];
    line?: BarLine;
    height?: number;
    grouped?: boolean;
    actions?: React.ReactNode;
    footnote?: React.ReactNode;
    valueLabel?: string;
    formatValue?: (value: number) => string;
    /** Buckets before recording began are left blank rather than zero-filled. */
    onAnnounce?: (message: string) => void;
}

const MARGIN = { top: 12, right: 52, bottom: 28, left: 44 };

export function Bars({
    title,
    subtitle,
    summary,
    buckets,
    granularity,
    series,
    line,
    height = 260,
    grouped = false,
    actions,
    footnote,
    valueLabel = "Requests",
    formatValue = formatCount,
    onAnnounce
}: BarsProps) {
    const [hidden, setHidden] = useState<Set<string>>(new Set());
    const [tooltip, setTooltip] = useState<TooltipState | null>(null);

    const visible = series.filter(item => !hidden.has(item.key));

    const totals = buckets.map((_bucket, index) =>
        grouped
            ? Math.max(0, ...visible.map(item => item.values[index] ?? 0))
            : visible.reduce((sum, item) => sum + (item.values[index] ?? 0), 0)
    );
    const maxValue = niceCeiling(Math.max(1, ...totals));
    const lineValues = (line?.values ?? []).filter((value): value is number => value !== null && Number.isFinite(value));
    const maxLine = niceCeiling(Math.max(0.0001, ...lineValues));

    const legend: LegendItem[] = series.map(item => ({
        key: item.key,
        label: item.label,
        color: item.color,
        hatched: item.hatched
    }));
    if (line) legend.push({ key: line.key, label: line.label, color: line.color });

    const table: ChartTable = {
        columns: [granularity === "hour" ? "Hour" : "Date", ...series.map(item => item.label), ...(line ? [line.label] : [])],
        rows: buckets.map((bucket, index) => [
            formatBucket(bucket, granularity),
            ...series.map(item => formatValue(item.values[index] ?? 0)),
            ...(line ? [line.values[index] === null || line.values[index] === undefined ? "no data" : line.format(line.values[index] as number)] : [])
        ])
    };

    const { focusedIndex, onKeyDown, onBlur, setFocusedIndex } = usePlotKeyboard(buckets.length, index => {
        if (index === null || !onAnnounce) return;
        const bucket = buckets[index];
        const parts = visible.map(item => `${item.label} ${formatValue(item.values[index] ?? 0)}`);
        onAnnounce(`${formatBucket(bucket, granularity)}: ${parts.join(", ")}`);
    });

    return (
        <ChartFrame
            title={title}
            subtitle={subtitle}
            summary={summary}
            height={height}
            legend={legend}
            hiddenKeys={hidden}
            onToggleSeries={key => {
                if (line && key === line.key) return;
                setHidden(previous => {
                    const next = new Set(previous);
                    if (next.has(key)) next.delete(key);
                    else next.add(key);
                    return next;
                });
            }}
            actions={actions}
            footnote={footnote}
            table={table}
            isEmpty={buckets.length === 0}
        >
            {(width, frameHeight) => {
                const plotWidth = Math.max(10, width - MARGIN.left - MARGIN.right);
                const plotHeight = Math.max(10, frameHeight - MARGIN.top - MARGIN.bottom);
                const x = bandScale(buckets.length, plotWidth, 0.22);
                const y = linearScale([0, maxValue], [plotHeight, 0]);
                const yLine = linearScale([0, maxLine], [plotHeight, 0]);
                const groupWidth = grouped && visible.length > 0 ? x.bandwidth / visible.length : x.bandwidth;

                const linePoints = line
                    ? buckets
                          .map((bucket, index) => {
                              const value = line.values[index];
                              if (value === null || value === undefined || !Number.isFinite(value)) return null;
                              return { x: x(index) + x.bandwidth / 2, y: yLine(value), index };
                          })
                          .filter((point): point is { x: number; y: number; index: number } => point !== null)
                    : [];

                return (
                    <div className={styles.plotWrap}>
                        <svg
                            width={width}
                            height={frameHeight}
                            role="img"
                            aria-label={summary}
                            tabIndex={0}
                            onKeyDown={onKeyDown}
                            onBlur={onBlur}
                            className={styles.plot}
                        >
                            <defs>
                                <pattern id="bars-hatch" width="6" height="6" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
                                    <line x1="0" y1="0" x2="0" y2="6" stroke="rgba(255,255,255,0.65)" strokeWidth="3" />
                                </pattern>
                            </defs>
                            <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
                                {y.ticks(4).map(tick => (
                                    <g key={tick}>
                                        <line x1={0} x2={plotWidth} y1={y(tick)} y2={y(tick)} className={styles.gridLine} />
                                        <text x={-8} y={y(tick)} dy="0.32em" textAnchor="end" className={styles.axisLabel}>
                                            {formatValue(tick)}
                                        </text>
                                    </g>
                                ))}

                                {line
                                    ? yLine.ticks(4).map(tick => (
                                          <text
                                              key={`line-${tick}`}
                                              x={plotWidth + 8}
                                              y={yLine(tick)}
                                              dy="0.32em"
                                              className={styles.axisLabel}
                                              style={{ fill: line.color }}
                                          >
                                              {line.format(tick)}
                                          </text>
                                      ))
                                    : null}

                                {buckets.map((bucket, index) => {
                                    let offset = 0;
                                    return (
                                        <g key={bucket}>
                                            {visible.map((item, seriesIndex) => {
                                                const value = item.values[index] ?? 0;
                                                const barHeight = Math.max(0, plotHeight - y(value));
                                                const barX = grouped ? x(index) + seriesIndex * groupWidth : x(index);
                                                const barY = grouped ? plotHeight - barHeight : plotHeight - offset - barHeight;
                                                if (!grouped) offset += barHeight;
                                                if (value <= 0) return null;
                                                return (
                                                    <g key={item.key}>
                                                        <rect
                                                            x={barX}
                                                            y={barY}
                                                            width={grouped ? Math.max(1, groupWidth - 2) : x.bandwidth}
                                                            height={barHeight}
                                                            fill={item.color}
                                                            rx={3}
                                                        />
                                                        {item.hatched ? (
                                                            <rect
                                                                x={barX}
                                                                y={barY}
                                                                width={grouped ? Math.max(1, groupWidth - 2) : x.bandwidth}
                                                                height={barHeight}
                                                                fill="url(#bars-hatch)"
                                                                rx={3}
                                                            />
                                                        ) : null}
                                                    </g>
                                                );
                                            })}
                                        </g>
                                    );
                                })}

                                {linePoints.length > 1 ? (
                                    <polyline
                                        points={linePoints.map(point => `${point.x},${point.y}`).join(" ")}
                                        fill="none"
                                        stroke={line!.color}
                                        strokeWidth={2}
                                        strokeLinecap="round"
                                        strokeLinejoin="round"
                                    />
                                ) : null}
                                {line?.reference !== undefined ? (
                                    <line
                                        x1={0}
                                        x2={plotWidth}
                                        y1={yLine(line.reference)}
                                        y2={yLine(line.reference)}
                                        stroke={line.color}
                                        strokeDasharray="4 4"
                                        strokeOpacity={0.5}
                                    />
                                ) : null}

                                {thinTicks(buckets, Math.max(2, Math.floor(plotWidth / 90))).map(({ item, index }) => (
                                    <text
                                        key={item}
                                        x={x(index) + x.bandwidth / 2}
                                        y={plotHeight + 18}
                                        textAnchor="middle"
                                        className={styles.axisLabel}
                                    >
                                        {formatBucket(item, granularity)}
                                    </text>
                                ))}

                                {buckets.map((bucket, index) => (
                                    <rect
                                        key={`hit-${bucket}`}
                                        x={x(index) - (x.step - x.bandwidth) / 2}
                                        y={0}
                                        width={x.step}
                                        height={plotHeight}
                                        fill="transparent"
                                        className={focusedIndex === index ? styles.hitFocused : undefined}
                                        onMouseEnter={event => {
                                            const bounds = (event.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect();
                                            setTooltip({
                                                x: event.clientX - bounds.left,
                                                y: event.clientY - bounds.top,
                                                content: (
                                                    <>
                                                        <strong>{formatBucket(bucket, granularity)}</strong>
                                                            {visible.map(item => (
                                                                <div key={item.key} className={styles.tooltipRow}>
                                                                    <span className={styles.tooltipSwatch} style={{ background: item.color }} />
                                                                    {item.label}
                                                                    <span className={styles.tooltipValue}>
                                                                        {formatValue(item.values[index] ?? 0)}
                                                                    </span>
                                                                </div>
                                                            ))}
                                                            {line && line.values[index] !== null && line.values[index] !== undefined ? (
                                                                <div className={styles.tooltipRow}>
                                                                    <span className={styles.tooltipSwatch} style={{ background: line.color }} />
                                                                    {line.label}
                                                                    <span className={styles.tooltipValue}>
                                                                        {line.format(line.values[index] as number)}
                                                                    </span>
                                                                </div>
                                                            ) : null}
                                                    </>
                                                )
                                            });
                                            setFocusedIndex(index);
                                        }}
                                        onMouseLeave={() => {
                                            setTooltip(null);
                                            setFocusedIndex(null);
                                        }}
                                    />
                                ))}
                            </g>
                        </svg>
                        <ChartTooltip tooltip={tooltip} containerWidth={width} />
                        <span className={styles.visuallyHidden}>{valueLabel}</span>
                    </div>
                );
            }}
        </ChartFrame>
    );
}
