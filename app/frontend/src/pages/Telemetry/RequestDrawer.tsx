import { useEffect, useRef, useState } from "react";

import { StepTimeline } from "./StepTimeline";
import { statusColor } from "./charts/palette";
import { formatCost, formatCount, formatDuration, formatTimestamp, timeZoneLabel } from "./charts/scales";
import { formatChatbotLabel } from "../shared/chatbotDisplay";
import styles from "./TelemetryPage.module.css";
import { TelemetryRecord, TelemetryRequestRow, downloadTelemetryRecordUrl } from "./telemetryApi";
import { PATH_LABELS } from "./useTelemetryQuery";

/**
 * One request, in full.
 *
 * **Everything here renders as text, never as markdown or HTML.** This is a forensic view: rendering
 * would hide exactly the hidden markers an operator opens it to inspect ([[CHOICES]], [[SCORE]],
 * [[SPLIT]], the assessment markers), and it would turn stored end-user input into an injection
 * surface inside the admin tool.
 */

export interface RequestDrawerProps {
    row: TelemetryRequestRow;
    record: TelemetryRecord | null;
    isLoading: boolean;
    error: string | null;
    currency: string;
    onClose: () => void;
    onStep: (direction: 1 | -1) => void;
    hasPrevious: boolean;
    hasNext: boolean;
}

function MessageBlock({ role, content, truncated }: { role: string; content: string; truncated?: boolean }) {
    const [expanded, setExpanded] = useState(false);
    // A tutor turn's history plus fifty retrieved sources is megabytes of text; rendering all of it
    // into the DOM by default would lock up the drawer.
    const isLong = content.length > 1200;
    const shown = expanded || !isLong ? content : `${content.slice(0, 1200)}\n...`;

    return (
        <div className={styles.message}>
            <div className={styles.messageHeader}>
                <span className={styles.messageRole}>{role}</span>
                <span className={styles.kpiHint}>{formatCount(content.length)} chars</span>
                <button
                    type="button"
                    className={styles.linkButton}
                    onClick={() => navigator.clipboard?.writeText(content)}
                    title="Copy this message"
                >
                    Copy
                </button>
            </div>
            <pre className={styles.codeBlock}>{shown}</pre>
            {isLong ? (
                <button type="button" className={styles.linkButton} onClick={() => setExpanded(value => !value)}>
                    {expanded ? "Show less" : `Show all ${formatCount(content.length)} characters`}
                </button>
            ) : null}
            {truncated ? <p className={styles.kpiHint}>Stored truncated at the recording cap.</p> : null}
        </div>
    );
}

export function RequestDrawer({
    row,
    record,
    isLoading,
    error,
    currency,
    onClose,
    onStep,
    hasPrevious,
    hasNext
}: RequestDrawerProps) {
    const panelRef = useRef<HTMLDivElement | null>(null);
    const closeRef = useRef<HTMLButtonElement | null>(null);
    const [expandedStep, setExpandedStep] = useState<number | null>(null);

    useEffect(() => {
        closeRef.current?.focus();
    }, [row.traceId]);

    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === "Escape") {
                event.preventDefault();
                onClose();
                return;
            }
            // Arrow keys move between requests without closing -- that is what makes triage fast --
            // but only when focus is not inside a field where the arrows mean something else.
            const target = event.target as HTMLElement | null;
            if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
            if (event.key === "ArrowDown" && hasNext) {
                event.preventDefault();
                onStep(1);
            } else if (event.key === "ArrowUp" && hasPrevious) {
                event.preventDefault();
                onStep(-1);
            } else if (event.key === "Tab" && panelRef.current) {
                const focusable = panelRef.current.querySelectorAll<HTMLElement>(
                    'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])'
                );
                if (focusable.length === 0) return;
                const first = focusable[0];
                const last = focusable[focusable.length - 1];
                if (!event.shiftKey && document.activeElement === last) {
                    event.preventDefault();
                    first.focus();
                } else if (event.shiftKey && document.activeElement === first) {
                    event.preventDefault();
                    last.focus();
                }
            }
        };
        document.addEventListener("keydown", onKeyDown);
        return () => {
            document.removeEventListener("keydown", onKeyDown);
        };
    }, [hasNext, hasPrevious, onClose, onStep]);

    return (
        <div className={styles.drawerOverlay} onClick={onClose}>
            <div
                className={styles.drawer}
                role="dialog"
                aria-modal="true"
                aria-labelledby="telemetry-drawer-title"
                ref={panelRef}
                onClick={event => event.stopPropagation()}
            >
                <header className={styles.drawerHeader}>
                    <div>
                        <span className={styles.badgeSmall}>Request</span>
                        <h2 id="telemetry-drawer-title" className={styles.drawerTitle}>
                            {row.promptPreview || row.traceId}
                        </h2>
                        <p className={styles.drawerMeta}>
                            {formatTimestamp(record?.startedAt ?? row.startedAt)} {timeZoneLabel()} /{" "}
                            {formatChatbotLabel(record?.chatbot?.name ?? row.chatbot)} /{" "}
                            {PATH_LABELS[record?.path ?? row.path] ?? record?.path ?? row.path} /{" "}
                            {record?.model ?? row.model ?? "unknown model"}
                            {(record?.streaming ?? row.streaming) ? " / streamed" : ""}
                            <span className={styles.statusPill} style={{ borderColor: statusColor(row.status), color: statusColor(row.status) }}>
                                {row.status}
                            </span>
                        </p>
                    </div>
                    <div className={styles.drawerActions}>
                        <button type="button" className={styles.iconButton} onClick={() => onStep(-1)} disabled={!hasPrevious} title="Previous request (up arrow)">
                            <span aria-hidden="true">↑</span>
                            <span className={styles.visuallyHidden}>Previous request</span>
                        </button>
                        <button type="button" className={styles.iconButton} onClick={() => onStep(1)} disabled={!hasNext} title="Next request (down arrow)">
                            <span aria-hidden="true">↓</span>
                            <span className={styles.visuallyHidden}>Next request</span>
                        </button>
                        <a className={styles.secondaryButton} href={downloadTelemetryRecordUrl(row.traceId, row.blobName)}>
                            Download JSON
                        </a>
                        <button type="button" className={styles.iconButton} onClick={onClose} ref={closeRef} title="Close (Escape)">
                            <span aria-hidden="true">×</span>
                            <span className={styles.visuallyHidden}>Close</span>
                        </button>
                    </div>
                </header>

                <div className={styles.drawerBody}>
                    {/* Prefer the full record once it has loaded. The row's figures come from the
                        listing's metadata digest, which is size-capped, so on a turn with very many
                        steps the two can legitimately differ -- and showing the capped numbers beside
                        the complete timeline would read as a bug. */}
                    <dl className={styles.numberStrip}>
                        <div>
                            <dt>Duration</dt>
                            <dd>{formatDuration(record?.durationMs ?? row.durationMs)}</dd>
                        </div>
                        <div>
                            <dt>Tokens in</dt>
                            <dd>{formatCount(record?.usage?.promptTokens ?? row.tokensIn)}</dd>
                        </div>
                        <div>
                            <dt>Tokens out</dt>
                            <dd>{formatCount(record?.usage?.completionTokens ?? row.tokensOut)}</dd>
                        </div>
                        <div>
                            <dt>Est. cost</dt>
                            <dd>
                                {formatCost(
                                    record?.cost?.micros ?? row.estCostMicros,
                                    record?.cost?.currency ?? row.currency ?? currency
                                )}
                            </dd>
                        </div>
                        <div>
                            <dt>Steps</dt>
                            <dd>{record?.steps?.length ?? row.steps.length}</dd>
                        </div>
                    </dl>

                    {error ? (
                        <p className={styles.warningLine} role="status">
                            {error}
                        </p>
                    ) : null}

                    <section>
                        <h3 className={styles.sectionTitle}>Step timeline</h3>
                        {isLoading && !record ? (
                            <div className={styles.skeletonBlock} aria-busy="true" />
                        ) : record ? (
                            <StepTimeline
                                steps={record.steps ?? []}
                                totalMs={record.durationMs}
                                currency={record.cost?.currency ?? currency}
                                expanded={expandedStep}
                                onToggle={index => setExpandedStep(current => (current === index ? null : index))}
                            />
                        ) : (
                            // The row's own step digest still draws a timeline when the body is gone.
                            <StepTimeline
                                steps={row.steps.map((step, index) => ({
                                    index,
                                    name: step.name,
                                    type: step.type,
                                    startMs: 0,
                                    durationMs: step.ms
                                }))}
                                totalMs={row.durationMs}
                                currency={currency}
                                expanded={null}
                                onToggle={() => undefined}
                            />
                        )}
                    </section>

                    {record?.error ? (
                        <section>
                            <h3 className={styles.sectionTitle}>Error</h3>
                            <p className={styles.errorHeadline}>
                                {record.error.type}: {record.error.message}
                            </p>
                            <pre className={styles.codeBlock}>{record.error.traceback}</pre>
                        </section>
                    ) : null}

                    {record?.messages?.length ? (
                        <section>
                            <h3 className={styles.sectionTitle}>Conversation</h3>
                            <p className={styles.sectionSubtitle}>
                                Shown as plain text on purpose, so hidden control markers stay visible.
                            </p>
                            {record.systemPrompt ? (
                                <details className={styles.notice}>
                                    <summary>
                                        System prompt ({formatCount(record.systemPrompt.length)} chars, sha256{" "}
                                        {record.systemPrompt.sha256.slice(0, 12)})
                                    </summary>
                                    <pre className={styles.codeBlock}>{record.systemPrompt.head}</pre>
                                </details>
                            ) : null}
                            {record.messages.map((message, index) => (
                                <MessageBlock key={index} role={message.role} content={message.content} truncated={message.truncated} />
                            ))}
                        </section>
                    ) : null}

                    {record?.response ? (
                        <section>
                            <h3 className={styles.sectionTitle}>Response</h3>
                            <MessageBlock role="assistant" content={record.response.content} truncated={record.response.truncated} />
                            {record.response.finishReason ? (
                                <p className={styles.kpiHint}>Finish reason: {record.response.finishReason}</p>
                            ) : null}
                            {record.response.citations?.length ? (
                                <p className={styles.kpiHint}>Citations: {record.response.citations.join(", ")}</p>
                            ) : null}
                        </section>
                    ) : null}

                    {record?.sources?.length ? (
                        <details className={styles.notice}>
                            <summary>{record.sources.length} source(s) used</summary>
                            <ul>
                                {record.sources.map((source, index) => (
                                    <li key={index}>{source.title ? `${source.title} — ${source.citation}` : source.citation}</li>
                                ))}
                            </ul>
                        </details>
                    ) : null}

                    {record?.overrides && Object.keys(record.overrides).length ? (
                        <details className={styles.notice}>
                            <summary>Request settings</summary>
                            <pre className={styles.codeBlock}>{JSON.stringify(record.overrides, null, 2)}</pre>
                        </details>
                    ) : null}

                    <p className={styles.privacyNote}>
                        This view shows a verbatim end-user conversation. Records are kept indefinitely; treat what you
                        read here as you would any other customer data.
                    </p>
                </div>
            </div>
        </div>
    );
}
