import { useCallback, useEffect, useMemo, useState } from "react";
import { Helmet } from "react-helmet-async";

import { ALL_MONTHS, HyroxVisitsResponse, downloadHyroxVisitsCsvApi, listHyroxVisitsApi } from "./hyroxVisitsApi";
import { useAdminShell } from "../admin/AdminShellContext";
// Imported rather than repeated so both admin tabs that show timestamps name one zone; that module
// also explains why the conversion happens in the browser at all.
import { DISPLAY_TIME_ZONE, timeZoneLabel } from "../Telemetry/charts/scales";
import styles from "./HyroxVisitsPage.module.css";

// Rendered inside the /admin shell (see pages/admin/AdminLayout). The shell owns the auth gate;
// this page only renders content and falls back to the shell's login on a session-expiry 401.

const formatMonthLabel = (month: string) => {
    const parsed = new Date(`${month}-01T00:00:00Z`);
    if (Number.isNaN(parsed.getTime())) {
        return month;
    }
    return new Intl.DateTimeFormat(undefined, { month: "long", year: "numeric", timeZone: "UTC" }).format(parsed);
};

// Timestamps are recorded in UTC and shown in German time — the clock the admins reading this live
// in. Pinned to Europe/Berlin rather than left to the browser's own zone so a row here and the same
// row in the CSV always read the same wherever the tab is opened; the CSV carries the matching UTC
// offset per row, and the month picker slices on this same clock.
const formatTimestamp = (timestamp: string) => {
    const parsed = new Date(timestamp);
    if (Number.isNaN(parsed.getTime())) {
        return timestamp;
    }
    return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "medium", timeZone: DISPLAY_TIME_ZONE }).format(parsed);
};

const HyroxVisitsPage = () => {
    const { handleUnauthorizedError } = useAdminShell();
    const [month, setMonth] = useState<string>(ALL_MONTHS);
    const [data, setData] = useState<HyroxVisitsResponse | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [isDownloading, setIsDownloading] = useState(false);
    const [statusMessage, setStatusMessage] = useState("");

    const loadVisits = useCallback(
        async (selectedMonth: string, signal?: AbortSignal) => {
            setIsLoading(true);
            try {
                const response = await listHyroxVisitsApi(selectedMonth, signal);
                setData(response);
                setStatusMessage("");
            } catch (error) {
                if (signal?.aborted) {
                    return;
                }
                if (!handleUnauthorizedError(error)) {
                    setStatusMessage(error instanceof Error ? error.message : "Loading HYROX visits failed.");
                }
            } finally {
                if (!signal?.aborted) {
                    setIsLoading(false);
                }
            }
        },
        [handleUnauthorizedError]
    );

    useEffect(() => {
        const controller = new AbortController();
        void loadVisits(month, controller.signal);
        return () => controller.abort();
    }, [loadVisits, month]);

    const handleDownload = async () => {
        setIsDownloading(true);
        try {
            const filename = await downloadHyroxVisitsCsvApi(month);
            setStatusMessage(`Downloaded ${filename}.`);
        } catch (error) {
            if (!handleUnauthorizedError(error)) {
                setStatusMessage(error instanceof Error ? error.message : "Downloading the CSV failed.");
            }
        } finally {
            setIsDownloading(false);
        }
    };

    const months = data?.months ?? [];
    const rows = data?.rows ?? [];
    const rowCount = data?.rowCount ?? 0;
    const uniqueUserCount = useMemo(() => new Set(rows.map(row => row.userId)).size, [rows]);
    const hasRows = rowCount > 0;

    return (
        <main className={styles.page}>
            <Helmet>
                <title>HYROX visits</title>
            </Helmet>

            <div className={styles.glowOne} aria-hidden="true" />
            <div className={styles.glowTwo} aria-hidden="true" />

            <section className={styles.shell}>
                <header className={styles.header}>
                    <div>
                        <span className={styles.badge}>Internal tool</span>
                        <h1 className={styles.title}>HYROX visits</h1>
                        <p className={styles.subtitle}>
                            Every time the HYROX assessment bot is opened from Lemon, the learner&rsquo;s id and the moment are recorded. Pick a month and
                            export it as a CSV of user id and timestamp.
                        </p>
                    </div>
                    <div className={styles.headerActions}>
                        <span className={styles.countPill}>{rowCount === 1 ? "1 visit" : `${rowCount} visits`}</span>
                        <span className={styles.countPill}>{`${data?.totalCount ?? 0} all time`}</span>
                    </div>
                </header>

                <section className={styles.panel}>
                    <div className={styles.toolbar}>
                        <label className={styles.label} htmlFor="hyrox-visits-month">
                            Month
                        </label>
                        <select
                            id="hyrox-visits-month"
                            className={styles.select}
                            value={month}
                            onChange={event => setMonth(event.target.value)}
                            disabled={isLoading && !data}
                        >
                            <option value={ALL_MONTHS}>All time</option>
                            {months.map(entry => (
                                <option key={entry.month} value={entry.month}>
                                    {`${formatMonthLabel(entry.month)} — ${entry.totalCount}`}
                                </option>
                            ))}
                        </select>
                        <button className={styles.primaryButton} type="button" onClick={() => void handleDownload()} disabled={isDownloading || !hasRows}>
                            {isDownloading ? "Preparing..." : "Download CSV"}
                        </button>
                        <button className={styles.secondaryButton} type="button" onClick={() => void loadVisits(month)} disabled={isLoading}>
                            {isLoading ? "Refreshing..." : "Refresh"}
                        </button>
                    </div>

                    <p className={styles.statusMessage} role="status" aria-live="polite">
                        {statusMessage}
                    </p>

                    {hasRows ? (
                        <>
                            <p className={styles.summaryLine}>
                                {`${rowCount} ${rowCount === 1 ? "entry" : "entries"} from ${uniqueUserCount} ${
                                    uniqueUserCount === 1 ? "user" : "users"
                                } in this preview.`}
                                {data?.previewTruncated
                                    ? ` Showing the newest ${data.previewLimit}; the CSV contains all ${rowCount}.`
                                    : " The CSV contains exactly these rows."}
                            </p>
                            <div className={styles.tableWrap}>
                                <table className={styles.table}>
                                    <thead>
                                        <tr>
                                            <th scope="col">User id</th>
                                            <th scope="col">Timestamp (German time)</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {rows.map((row, index) => (
                                            <tr key={`${row.timestamp}-${row.userId}-${index}`}>
                                                <td>{row.userId}</td>
                                                <td>{formatTimestamp(row.timestamp)}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </>
                    ) : (
                        <div className={styles.emptyState}>
                            <strong className={styles.emptyTitle}>{isLoading ? "Loading visits..." : "No visits recorded"}</strong>
                            <span className={styles.emptyText}>
                                {isLoading ? "Reading the visit log." : "Visits appear here as soon as a learner opens the bot from Lemon."}
                            </span>
                        </div>
                    )}

                    <details className={styles.notes}>
                        <summary className={styles.notesSummary}>What counts as a visit</summary>
                        <p className={styles.notesText}>
                            One row every time the bot is opened, timestamped at that moment — so the same learner appears once per visit, and a reload counts
                            again.
                        </p>
                        <p className={styles.notesText}>
                            Times are German time (currently {timeZoneLabel() || "CET/CEST"}), here and in the CSV, which carries each row&rsquo;s UTC offset.
                            The month picker slices on the same clock, so a visit just before midnight German time belongs to the day and month it reads as.
                        </p>
                        <p className={styles.notesText}>
                            Only launches from Lemon are counted. The LMS puts the learner&rsquo;s <code>account_id</code> on the launch URL, so opening the
                            bot&rsquo;s address directly records nothing — and neither does running the app locally. Tracking started when this tab shipped;
                            there is no history from before that.
                        </p>
                    </details>
                </section>
            </section>
        </main>
    );
};

export default HyroxVisitsPage;
