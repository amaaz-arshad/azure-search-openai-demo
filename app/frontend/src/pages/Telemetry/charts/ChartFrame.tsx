import { ReactNode, useCallback, useEffect, useRef, useState } from "react";

import styles from "./charts.module.css";

/**
 * The one frame every chart on this page draws inside.
 *
 * It owns width measurement, the header, the legend, the tooltip layer, the empty state and — the
 * part that earns it — a `<details>` data table generated from **the same array the marks consume**.
 * That table is what makes a hand-rolled SVG chart usable with a screen reader, and it is generated
 * rather than hand-written precisely so it cannot drift from what is drawn. It doubles as a
 * copy-paste affordance for anyone who wants the numbers rather than the picture.
 */

export interface LegendItem {
    key: string;
    label: string;
    color: string;
    /** Rendered as a hatch overlay as well as a colour, so colour is never the only channel. */
    hatched?: boolean;
    value?: string;
}

export interface ChartTable {
    columns: string[];
    rows: (string | number)[][];
}

export interface ChartFrameProps {
    title: string;
    subtitle?: string;
    /** One sentence describing what the chart shows; becomes the SVG's accessible name. */
    summary: string;
    height?: number;
    legend?: LegendItem[];
    hiddenKeys?: Set<string>;
    onToggleSeries?: (key: string) => void;
    actions?: ReactNode;
    footnote?: ReactNode;
    table?: ChartTable;
    isEmpty?: boolean;
    emptyMessage?: string;
    className?: string;
    children: (width: number, height: number) => ReactNode;
}

/** Measures the plot area. A chart that renders before it has a width would lay out at zero. */
export function useMeasuredWidth<T extends HTMLElement>() {
    const ref = useRef<T | null>(null);
    const [width, setWidth] = useState(0);

    useEffect(() => {
        const element = ref.current;
        if (!element) return;
        const observer = new ResizeObserver(entries => {
            for (const entry of entries) {
                setWidth(entry.contentRect.width);
            }
        });
        observer.observe(element);
        setWidth(element.getBoundingClientRect().width);
        return () => observer.disconnect();
    }, []);

    return { ref, width };
}

export function ChartFrame({
    title,
    subtitle,
    summary,
    height = 260,
    legend,
    hiddenKeys,
    onToggleSeries,
    actions,
    footnote,
    table,
    isEmpty,
    emptyMessage = "No data in this range.",
    className,
    children
}: ChartFrameProps) {
    const { ref, width } = useMeasuredWidth<HTMLDivElement>();

    return (
        <section className={`${styles.chartCard} ${className ?? ""}`}>
            <header className={styles.chartHeader}>
                <div>
                    <h3 className={styles.chartTitle}>{title}</h3>
                    {subtitle ? <p className={styles.chartSubtitle}>{subtitle}</p> : null}
                </div>
                {actions ? <div className={styles.chartActions}>{actions}</div> : null}
            </header>

            <div className={styles.chartBody} ref={ref} style={{ minHeight: height }}>
                {isEmpty ? (
                    <p className={styles.chartEmpty}>{emptyMessage}</p>
                ) : width > 0 ? (
                    children(width, height)
                ) : null}
            </div>

            {legend && legend.length > 0 ? (
                <ul className={styles.legend}>
                    {legend.map(item => {
                        const hidden = hiddenKeys?.has(item.key) ?? false;
                        const swatch = (
                            <span
                                className={`${styles.legendSwatch} ${item.hatched ? styles.legendSwatchHatched : ""}`}
                                style={{ background: item.color }}
                                aria-hidden="true"
                            />
                        );
                        return (
                            <li key={item.key}>
                                {onToggleSeries ? (
                                    <button
                                        type="button"
                                        className={`${styles.legendItem} ${hidden ? styles.legendItemHidden : ""}`}
                                        aria-pressed={!hidden}
                                        onClick={() => onToggleSeries(item.key)}
                                    >
                                        {swatch}
                                        <span>{item.label}</span>
                                        {item.value ? <span className={styles.legendValue}>{item.value}</span> : null}
                                    </button>
                                ) : (
                                    <span className={styles.legendItem}>
                                        {swatch}
                                        <span>{item.label}</span>
                                        {item.value ? <span className={styles.legendValue}>{item.value}</span> : null}
                                    </span>
                                )}
                            </li>
                        );
                    })}
                </ul>
            ) : null}

            {footnote ? <p className={styles.chartFootnote}>{footnote}</p> : null}

            {table && table.rows.length > 0 ? (
                <details className={styles.dataTable}>
                    <summary>View data as a table</summary>
                    <div className={styles.dataTableWrap}>
                        <table>
                            <caption className={styles.visuallyHidden}>{summary}</caption>
                            <thead>
                                <tr>
                                    {table.columns.map(column => (
                                        <th key={column} scope="col">
                                            {column}
                                        </th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody>
                                {table.rows.map((row, index) => (
                                    <tr key={index}>
                                        {row.map((cell, cellIndex) => (
                                            <td key={cellIndex}>{cell}</td>
                                        ))}
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </details>
            ) : null}
        </section>
    );
}

export interface TooltipState {
    x: number;
    y: number;
    content: ReactNode;
}

/** A glass tooltip that flips before it can cross the panel edge. */
export function ChartTooltip({ tooltip, containerWidth }: { tooltip: TooltipState | null; containerWidth: number }) {
    if (!tooltip) return null;
    const flip = tooltip.x > containerWidth * 0.6;
    return (
        <div
            className={styles.tooltip}
            style={{ left: tooltip.x, top: tooltip.y, transform: flip ? "translate(-100%, -50%)" : "translate(12px, -50%)" }}
            role="presentation"
        >
            {tooltip.content}
        </div>
    );
}

/**
 * Keyboard navigation for a plot area: left/right step between data points, Home/End jump to the
 * ends. The focused datum is announced through the page's single live region — several competing
 * live regions on one page fight each other and end up announcing nothing.
 */
export function usePlotKeyboard(count: number, onFocusChange: (index: number | null) => void) {
    const [index, setIndex] = useState<number | null>(null);

    const move = useCallback(
        (next: number | null) => {
            setIndex(next);
            onFocusChange(next);
        },
        [onFocusChange]
    );

    const onKeyDown = useCallback(
        (event: React.KeyboardEvent) => {
            if (count === 0) return;
            const current = index ?? -1;
            if (event.key === "ArrowRight") {
                event.preventDefault();
                move(Math.min(count - 1, current + 1));
            } else if (event.key === "ArrowLeft") {
                event.preventDefault();
                move(Math.max(0, current <= 0 ? 0 : current - 1));
            } else if (event.key === "Home") {
                event.preventDefault();
                move(0);
            } else if (event.key === "End") {
                event.preventDefault();
                move(count - 1);
            } else if (event.key === "Escape") {
                move(null);
            }
        },
        [count, index, move]
    );

    return { focusedIndex: index, onKeyDown, onBlur: () => move(null), setFocusedIndex: move };
}
