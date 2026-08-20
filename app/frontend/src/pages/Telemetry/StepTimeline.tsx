import { stepTypeColor } from "./charts/palette";
import { formatCost, formatCount, formatDuration } from "./charts/scales";
import styles from "./TelemetryPage.module.css";
import { TelemetryRecordStep } from "./telemetryApi";

/**
 * One request's steps on a single shared time axis.
 *
 * A shared axis rather than a bar per row, because the question this answers is not only "how long
 * did each step take" but "what was waiting on what" — and the *gaps* are part of the answer.
 *
 * Time outside the steps is drawn explicitly and, since it is entirely made of known phases, named:
 * `request setup` before the first step and `response wrap-up` after the last. It used to be pooled
 * into one "unaccounted" bar parked at the end of the axis, which was both unreadable and, while the
 * streamed answer step was closing at the first chunk, most of the turn.
 */

export interface StepTimelineProps {
    steps: TelemetryRecordStep[];
    totalMs: number;
    currency: string;
    expanded: number | null;
    onToggle: (index: number) => void;
}

export function StepTimeline({ steps, totalMs, currency, expanded, onToggle }: StepTimelineProps) {
    if (steps.length === 0) {
        return <p className={styles.chartEmptyInline}>No steps were recorded for this request.</p>;
    }

    const span = Math.max(totalMs, ...steps.map(step => step.startMs + step.durationMs), 1);
    // Top-level steps tile the turn; a parented child's time is already inside its parent's bar.
    const topLevel = steps.filter(step => step.parent === undefined);

    /**
     * The time outside the measured steps, split into the phases it is actually made of instead of
     * one "unaccounted" bucket.
     *
     * Both are exact, not estimates: the first step's `startMs` IS the setup time, and the turn's
     * duration minus the end of the last step IS the wrap-up. They are small (tens of ms) — if one
     * is large, something in that phase is slow and worth knowing about, which is precisely why they
     * are named rather than pooled.
     */
    const firstStart = Math.min(...topLevel.map(step => step.startMs));
    const lastEnd = Math.max(...topLevel.map(step => step.startMs + step.durationMs));
    const setupMs = Math.max(0, firstStart);
    const wrapUpMs = Math.max(0, totalMs - lastEnd);

    // Anything left is genuine dead time BETWEEN steps, which is a different question again.
    const covered = topLevel.reduce((sum, step) => sum + step.durationMs, 0);
    const betweenMs = Math.max(0, totalMs - setupMs - wrapUpMs - covered);

    const phases = [
        {
            key: "setup",
            name: "request setup",
            hint: "Validating the request, loading the bot's saved prompt, auth and quota checks, rendering the prompt.",
            ms: setupMs,
            left: 0
        },
        {
            key: "between",
            name: "between steps",
            hint: "Time inside the turn that no step accounts for.",
            ms: betweenMs,
            left: (firstStart / span) * 100
        },
        {
            key: "wrapup",
            name: "response wrap-up",
            hint: "Finishing the response after the last step: follow-up parsing, serialisation, and writing this record.",
            ms: wrapUpMs,
            left: (lastEnd / span) * 100
        }
    ].filter(phase => phase.ms > 20);

    return (
        <div className={styles.timeline}>
            {steps.map(step => {
                const left = (step.startMs / span) * 100;
                const width = Math.max(0.6, (step.durationMs / span) * 100);
                const isChild = step.parent !== undefined;
                return (
                    <div key={step.index} className={styles.timelineRow}>
                        <button
                            type="button"
                            className={`${styles.timelineLabel} ${isChild ? styles.timelineLabelChild : ""}`}
                            aria-expanded={expanded === step.index}
                            onClick={() => onToggle(step.index)}
                        >
                            <span className={styles.timelineChip} style={{ background: stepTypeColor(step.type) }} aria-hidden="true" />
                            <span className={styles.timelineName}>{step.name}</span>
                        </button>
                        <div className={styles.timelineTrack}>
                            <span
                                className={styles.timelineBar}
                                style={{ left: `${left}%`, width: `${width}%`, background: stepTypeColor(step.type) }}
                            />
                        </div>
                        <span className={styles.timelineDuration}>{formatDuration(step.durationMs)}</span>
                        <span className={styles.timelineTokens}>
                            {step.usage && step.usage.totalTokens > 0
                                ? `${formatCount(step.usage.promptTokens)}/${formatCount(step.usage.completionTokens)}`
                                : ""}
                        </span>
                        <span className={styles.timelineCost}>
                            {step.costMicros === undefined || step.costMicros === null ? "" : formatCost(step.costMicros, currency)}
                        </span>

                        {expanded === step.index ? (
                            <div className={styles.timelineDetail}>
                                <dl className={styles.detailList}>
                                    {step.model ? (
                                        <div>
                                            <dt>Model</dt>
                                            <dd>
                                                {step.model}
                                                {step.reasoningEffort ? ` (${step.reasoningEffort})` : ""}
                                            </dd>
                                        </div>
                                    ) : null}
                                    <div>
                                        <dt>Starts at</dt>
                                        <dd>{formatDuration(step.startMs)} into the turn</dd>
                                    </div>
                                    {step.usage && step.usage.totalTokens > 0 ? (
                                        <div>
                                            <dt>Tokens</dt>
                                            <dd>
                                                {formatCount(step.usage.promptTokens)} in, {formatCount(step.usage.completionTokens)} out
                                                {step.usage.reasoningTokens ? `, ${formatCount(step.usage.reasoningTokens)} reasoning` : ""}
                                                {step.usage.cachedTokens ? `, ${formatCount(step.usage.cachedTokens)} cached` : ""}
                                            </dd>
                                        </div>
                                    ) : null}
                                    {typeof step.payload?.time_to_first_token_ms === "number" ? (
                                        <div>
                                            <dt>Time to first token</dt>
                                            <dd>
                                                {formatDuration(step.payload.time_to_first_token_ms)}
                                                {step.durationMs > 0
                                                    ? ` — the remaining ${formatDuration(
                                                          step.durationMs - step.payload.time_to_first_token_ms
                                                      )} was spent streaming the answer`
                                                    : ""}
                                            </dd>
                                        </div>
                                    ) : null}
                                    {step.error ? (
                                        <div>
                                            <dt>Error</dt>
                                            <dd>{step.error}</dd>
                                        </div>
                                    ) : null}
                                </dl>
                                {step.payload && Object.keys(step.payload).length > 0 ? (
                                    <pre className={styles.codeBlock}>{JSON.stringify(step.payload, null, 2)}</pre>
                                ) : null}
                            </div>
                        ) : null}
                    </div>
                );
            })}

            {phases.map(phase => (
                <div key={phase.key} className={`${styles.timelineRow} ${styles.timelineRowMuted}`} title={phase.hint}>
                    <span className={styles.timelineLabel}>
                        <span className={styles.timelineChip} style={{ background: "#9a90a3" }} aria-hidden="true" />
                        <span className={styles.timelineName}>{phase.name}</span>
                    </span>
                    <div className={styles.timelineTrack}>
                        <span
                            className={`${styles.timelineBar} ${styles.timelineBarGhost}`}
                            style={{ left: `${phase.left}%`, width: `${Math.max(0.6, (phase.ms / span) * 100)}%` }}
                        />
                    </div>
                    <span className={styles.timelineDuration}>{formatDuration(phase.ms)}</span>
                    <span className={styles.timelineTokens} />
                    <span className={styles.timelineCost} />
                </div>
            ))}
        </div>
    );
}
