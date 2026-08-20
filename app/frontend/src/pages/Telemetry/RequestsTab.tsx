import { useEffect, useMemo, useRef, useState } from "react";

import { StackedBar } from "./charts/Sparkline";
import { assignSeriesColors, statusColor, stepTypeColor } from "./charts/palette";
import { formatCost, formatCount, formatDuration, formatExactCount, formatTimestamp } from "./charts/scales";
import { formatChatbotLabel } from "../shared/chatbotDisplay";
import styles from "./TelemetryPage.module.css";
import { TelemetryRequestRow } from "./telemetryApi";
import { PAGE_SIZE_OPTIONS, PATH_LABELS } from "./useTelemetryQuery";

/**
 * The request explorer.
 *
 * A row is clickable as a mouse affordance, but the trailing Open button is the keyboard and
 * screen-reader target — one accessible name per row, rather than a whole row pretending to be a
 * button and reading out every cell as its label.
 */

export interface RequestsTabProps {
    rows: TelemetryRequestRow[];
    currency: string;
    hasMore: boolean;
    isLoadingPage: boolean;
    pageIndex: number;
    pageSize: number;
    firstRowNumber: number;
    /** Total matching rows, or null when a search is active -- see the note in the pager below. */
    totalRows: number | null;
    onPage: (index: number) => void;
    onPageSize: (size: number) => void;
    onOpen: (row: TelemetryRequestRow) => void;
    search: string;
    onSearch: (value: string) => void;
    selectedTraceId: string | null;
    storesBodies: boolean;
}

/**
 * The search field owns the text being typed.
 *
 * It used to render `value={search}`, which is the debounced URL state -- so any re-render landing
 * mid-word (a completing fetch is the obvious one) reset the field to the last value that had made it
 * into the URL and ate the characters typed since. Holding the draft locally means typing is never
 * interrupted; the debounce then decides when the API hears about it.
 */
function SearchField({ search, onSearch }: { search: string; onSearch: (value: string) => void }) {
    const [draft, setDraft] = useState(search);
    const emitted = useRef(search);

    useEffect(() => {
        // Adopt an external change -- Reset, or a pasted link -- but never echo our own debounced
        // write back into the field, which is the loop that clobbered live typing.
        if (search !== emitted.current) {
            emitted.current = search;
            setDraft(search);
        }
    }, [search]);

    return (
        <label className={styles.searchField}>
            <span className={styles.visuallyHidden}>Search requests</span>
            <input
                type="search"
                placeholder="Search prompt, chatbot, model or trace id"
                value={draft}
                onChange={event => {
                    setDraft(event.target.value);
                    emitted.current = event.target.value;
                    onSearch(event.target.value);
                }}
            />
        </label>
    );
}

export function RequestsTab({
    rows,
    currency,
    hasMore,
    isLoadingPage,
    pageIndex,
    pageSize,
    firstRowNumber,
    totalRows,
    onPage,
    onPageSize,
    onOpen,
    search,
    onSearch,
    selectedTraceId,
    storesBodies
}: RequestsTabProps) {
    const chatbotColors = useMemo(() => assignSeriesColors([...new Set(rows.map(row => row.chatbot))]), [rows]);
    const slowest = Math.max(1, ...rows.map(row => row.durationMs));
    const lastRowNumber = firstRowNumber + rows.length - 1;

    return (
        <div className={styles.tabBody}>
            <div className={styles.panelInner}>
                <div className={styles.requestsToolbar}>
                    <SearchField search={search} onSearch={onSearch} />
                    <span className={styles.kpiHint} aria-live="polite">
                        {rows.length === 0
                            ? "No requests"
                            : `Showing ${formatExactCount(firstRowNumber)}–${formatExactCount(lastRowNumber)}`}
                        {/* The summary applies the facets but not the free-text query, so its total is
                            not this list's total while a search is active -- claiming it would be a
                            wrong number rather than a missing one. */}
                        {totalRows !== null && rows.length > 0 ? ` of ${formatExactCount(totalRows)}` : ""}
                    </span>
                    <label className={styles.pageSizeField}>
                        <span className={styles.visuallyHidden}>Rows per page</span>
                        <select
                            value={pageSize}
                            onChange={event => onPageSize(Number(event.target.value))}
                            aria-label="Rows per page"
                        >
                            {PAGE_SIZE_OPTIONS.map(size => (
                                <option key={size} value={size}>
                                    {size} per page
                                </option>
                            ))}
                        </select>
                    </label>
                </div>

                {rows.length === 0 ? (
                    <div className={styles.emptyState}>
                        <p className={styles.emptyTitle}>
                            {search ? `Nothing matches “${search}”` : "No requests match these filters"}
                        </p>
                        <p className={styles.emptyText}>
                            {search
                                ? "Search covers the prompt preview, chatbot, model and trace id of requests inside the selected range."
                                : "Widen the date range, or clear a filter above."}
                        </p>
                    </div>
                ) : (
                    <>
                        <div className={styles.tableWrap}>
                            <table className={styles.table}>
                                <thead>
                                    <tr>
                                        <th scope="col">Time</th>
                                        <th scope="col">Chatbot</th>
                                        <th scope="col">Path</th>
                                        <th scope="col">Model</th>
                                        <th scope="col">Prompt</th>
                                        <th scope="col">Steps</th>
                                        <th scope="col">Tokens</th>
                                        <th scope="col">Est. cost</th>
                                        <th scope="col">Duration</th>
                                        <th scope="col">Status</th>
                                        <th scope="col">
                                            <span className={styles.visuallyHidden}>Open</span>
                                        </th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {rows.map(row => (
                                        <tr
                                            key={row.traceId + row.startedAt}
                                            className={selectedTraceId === row.traceId ? styles.rowSelected : undefined}
                                            onClick={() => onOpen(row)}
                                        >
                                            <td>{formatTimestamp(row.startedAt)}</td>
                                            <td>
                                                <span
                                                    className={styles.rowChip}
                                                    style={{ background: chatbotColors[row.chatbot] ?? "#9a90a3" }}
                                                    aria-hidden="true"
                                                />
                                                {formatChatbotLabel(row.chatbot)}
                                                {row.sourceChatbot ? (
                                                    <span className={styles.rowSubChip}>{formatChatbotLabel(row.sourceChatbot)}</span>
                                                ) : null}
                                            </td>
                                            <td>
                                                <span className={styles.pathPill}>
                                                    {PATH_LABELS[row.path] ?? row.path}
                                                    {row.streaming ? <span title="Streamed"> ~</span> : null}
                                                </span>
                                            </td>
                                            <td>
                                                {row.model ?? "—"}
                                                {row.reasoningEffort ? <span className={styles.rowSubChip}>{row.reasoningEffort}</span> : null}
                                            </td>
                                            <td className={styles.promptCell} title={row.promptPreview}>
                                                {row.promptPreview || (storesBodies ? "—" : "not stored")}
                                            </td>
                                            <td className={styles.stepsCell}>
                                                <StackedBar
                                                    height={8}
                                                    segments={row.steps.map((step, index) => ({
                                                        key: `${step.name}-${index}`,
                                                        label: step.name,
                                                        ms: step.ms,
                                                        color: stepTypeColor(step.type)
                                                    }))}
                                                />
                                            </td>
                                            <td>
                                                {formatCount(row.tokensIn)} to {formatCount(row.tokensOut)}
                                                {row.tokensCached ? (
                                                    <span className={styles.rowSubChip}>{formatCount(row.tokensCached)} cached</span>
                                                ) : null}
                                            </td>
                                            <td className={styles.numericCell}>{formatCost(row.estCostMicros, row.currency ?? currency)}</td>
                                            <td className={styles.numericCell}>
                                                {formatDuration(row.durationMs)}
                                                <span className={styles.durationBar} aria-hidden="true">
                                                    <span style={{ width: `${(row.durationMs / slowest) * 100}%` }} />
                                                </span>
                                            </td>
                                            <td>
                                                <span
                                                    className={styles.statusPill}
                                                    style={{ borderColor: statusColor(row.status), color: statusColor(row.status) }}
                                                >
                                                    {row.status}
                                                    {row.errorType ? `: ${row.errorType}` : ""}
                                                </span>
                                            </td>
                                            <td>
                                                <button
                                                    type="button"
                                                    className={styles.linkButton}
                                                    onClick={event => {
                                                        event.stopPropagation();
                                                        onOpen(row);
                                                    }}
                                                >
                                                    Open
                                                    <span className={styles.visuallyHidden}>
                                                        {` request from ${formatTimestamp(row.startedAt)} on ${formatChatbotLabel(row.chatbot)}`}
                                                    </span>
                                                </button>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </>
                )}

                {/* Outside the empty-state branch on purpose: the day-scan cap can report "more" and
                    then hand back an empty last page, and a pager that vanished with the rows would
                    strand the reader on it with no way back. */}
                {rows.length > 0 || pageIndex > 0 ? (
                    <nav className={styles.pager} aria-label="Request pages">
                        <button
                            type="button"
                            className={styles.secondaryButton}
                            onClick={() => onPage(pageIndex - 1)}
                            disabled={pageIndex === 0 || isLoadingPage}
                        >
                            Previous
                        </button>
                        <span className={styles.pageNumber} aria-live="polite">
                            {isLoadingPage ? "Loading…" : `Page ${pageIndex + 1}`}
                        </span>
                        <button
                            type="button"
                            className={styles.secondaryButton}
                            onClick={() => onPage(pageIndex + 1)}
                            disabled={!hasMore || rows.length === 0 || isLoadingPage}
                        >
                            Next
                        </button>
                    </nav>
                ) : null}
            </div>
        </div>
    );
}
