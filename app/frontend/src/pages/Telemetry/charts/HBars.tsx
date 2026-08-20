import { useState } from "react";

import { ChartFrame, ChartTable } from "./ChartFrame";
import styles from "./charts.module.css";

/**
 * The leaderboard shape: one horizontal bar per key, on a shared baseline, sorted descending.
 *
 * Rows are real buttons when `onSelect` is given, because clicking a bot to filter the whole page is
 * the single most-used interaction on this dashboard and it must be reachable from the keyboard. The
 * exact value always renders as text next to the bar, so a bar too short to see (or a reader who
 * cannot see it at all) still gets the number.
 */

export interface HBarRow {
    key: string;
    label: string;
    value: number;
    color: string;
    formatted: string;
    /** A muted second line, e.g. "412 requests" under a cost bar. */
    detail?: string;
    /** Drawn as a dashed outline instead of a fill, for a model with no price. */
    outline?: boolean;
    badge?: string;
}

export interface HBarsProps {
    title: string;
    subtitle?: string;
    summary: string;
    rows: HBarRow[];
    actions?: React.ReactNode;
    footnote?: React.ReactNode;
    valueColumn: string;
    maxRows?: number;
    onSelect?: (key: string) => void;
    emptyMessage?: string;
}

export function HBars({
    title,
    subtitle,
    summary,
    rows,
    actions,
    footnote,
    valueColumn,
    maxRows = 10,
    onSelect,
    emptyMessage
}: HBarsProps) {
    const [showAll, setShowAll] = useState(false);
    const visible = showAll ? rows : rows.slice(0, maxRows);
    const max = Math.max(1, ...rows.map(row => row.value));

    const table: ChartTable = {
        columns: ["Name", valueColumn],
        rows: rows.map(row => [row.label, row.formatted])
    };

    return (
        <ChartFrame
            title={title}
            subtitle={subtitle}
            summary={summary}
            height={Math.max(120, visible.length * 40 + 12)}
            actions={actions}
            footnote={footnote}
            table={table}
            isEmpty={rows.length === 0}
            emptyMessage={emptyMessage}
        >
            {() => (
                <div className={styles.hbars}>
                    {visible.map(row => {
                        // A 2px floor so a real-but-tiny value is still visibly present rather than
                        // rendering as nothing at all.
                        const width = `${Math.max(2, (row.value / max) * 100)}%`;
                        const content = (
                            <>
                                <span className={styles.hbarChip} style={{ background: row.color }} aria-hidden="true" />
                                <span className={styles.hbarLabel}>
                                    {row.label}
                                    {row.badge ? <span className={styles.hbarBadge}>{row.badge}</span> : null}
                                </span>
                                <span className={styles.hbarTrack}>
                                    <span
                                        className={`${styles.hbarFill} ${row.outline ? styles.hbarFillOutline : ""}`}
                                        style={row.outline ? { width, borderColor: row.color } : { width, background: row.color }}
                                    />
                                </span>
                                <span className={styles.hbarValue}>
                                    {row.formatted}
                                    {row.detail ? <span className={styles.hbarDetail}>{row.detail}</span> : null}
                                </span>
                            </>
                        );

                        return onSelect ? (
                            <button
                                key={row.key}
                                type="button"
                                className={`${styles.hbarRow} ${styles.hbarRowInteractive}`}
                                onClick={() => onSelect(row.key)}
                                title={`Filter this page to ${row.label}`}
                            >
                                {content}
                            </button>
                        ) : (
                            <div key={row.key} className={styles.hbarRow}>
                                {content}
                            </div>
                        );
                    })}
                    {rows.length > maxRows ? (
                        <button type="button" className={styles.showAll} onClick={() => setShowAll(value => !value)}>
                            {showAll ? "Show top " + maxRows : `Show all ${rows.length}`}
                        </button>
                    ) : null}
                </div>
            )}
        </ChartFrame>
    );
}
