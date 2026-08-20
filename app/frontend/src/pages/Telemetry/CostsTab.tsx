import { useEffect, useMemo, useState } from "react";

import { HBars, HBarRow } from "./charts/HBars";
import { assignSeriesColors } from "./charts/palette";
import { formatCost, formatCount, formatExactCount, formatRequestCount } from "./charts/scales";
import { formatChatbotLabel } from "../shared/chatbotDisplay";
import styles from "./TelemetryPage.module.css";
import { PricePayload, TelemetrySummary, getTelemetryPricingApi, saveTelemetryPricingApi } from "./telemetryApi";

/**
 * Cost, entirely from what we recorded ourselves.
 *
 * Every figure here is our own token counts priced with a versioned EUR table, which is why it can be
 * split by chatbot and by step. It is an estimate of what the chat traffic cost, not an invoice: it
 * covers only requests this dashboard recorded, so ingestion runs, the prepdocs and refresh scripts
 * and any other workload on the same Azure OpenAI resource are not in it.
 */

export interface CostsTabProps {
    summary: TelemetrySummary;
    onSelectChatbot: (name: string) => void;
}

export function CostsTab({ summary, onSelectChatbot }: CostsTabProps) {
    const currency = summary.currency;
    const chatbotColors = useMemo(() => assignSeriesColors(summary.byChatbot.map(row => row.chatbot ?? "")), [summary.byChatbot]);
    const modelColors = useMemo(() => assignSeriesColors(summary.byModel.map(row => row.model ?? "")), [summary.byModel]);

    const chatbotRows: HBarRow[] = summary.byChatbot.map(row => ({
        key: row.chatbot ?? "",
        label: formatChatbotLabel(row.chatbot ?? ""),
        value: row.estCostMicros,
        color: chatbotColors[row.chatbot ?? ""] ?? "#9a90a3",
        formatted: formatCost(row.estCostMicros, currency),
        detail: formatRequestCount(row.requests)
    }));

    const modelRows: HBarRow[] = summary.byModel.map(row => ({
        key: row.model ?? "",
        label: row.model ?? "unknown",
        value: row.estCostMicros,
        color: modelColors[row.model ?? ""] ?? "#9a90a3",
        formatted: formatCost(row.estCostMicros, currency),
        detail: `${formatCount(row.tokensIn)} in / ${formatCount(row.tokensOut)} out`,
        outline: row.unpricedCount > 0 && row.estCostMicros === 0,
        badge: row.unpricedCount > 0 ? "unpriced" : undefined
    }));

    const stepRows: HBarRow[] = useMemo(() => {
        const byStep = new Map<string, number>();
        for (const step of summary.byStep) {
            byStep.set(step.step, (byStep.get(step.step) ?? 0) + step.tokensIn + step.tokensOut);
        }
        const colors = assignSeriesColors([...byStep.keys()]);
        return [...byStep.entries()]
            .sort((a, b) => b[1] - a[1])
            .map(([step, tokens]) => ({
                key: step,
                label: step,
                value: tokens,
                color: colors[step] ?? "#9a90a3",
                formatted: formatCount(tokens)
            }));
    }, [summary.byStep]);

    return (
        <div className={styles.tabBody}>
            <div className={styles.chartGrid}>
                <HBars
                    title="Cost by chatbot"
                    subtitle="Click a row to narrow the whole page to that bot."
                    summary="Estimated cost per chatbot over the selected range."
                    rows={chatbotRows}
                    valueColumn={`Estimated cost (${currency})`}
                    onSelect={onSelectChatbot}
                    emptyMessage="No chat requests in this range."
                />
                <HBars
                    title="Cost by model"
                    summary="Estimated cost per model over the selected range."
                    rows={modelRows}
                    valueColumn={`Estimated cost (${currency})`}
                    emptyMessage="No model usage in this range."
                    footnote={
                        summary.unpricedModels.length
                            ? `${summary.unpricedModels.length} model(s) have no price yet, so their requests are excluded from every cost figure. Add a price below.`
                            : undefined
                    }
                />
            </div>

            <HBars
                title="Tokens by step"
                subtitle="Which stage of a turn actually spends the tokens."
                summary="Total tokens per pipeline step over the selected range."
                rows={stepRows}
                valueColumn="Tokens"
                emptyMessage="No step data in this range."
            />

            <section className={styles.panelInner}>
                <h3 className={styles.sectionTitle}>What this covers</h3>
                <p className={styles.sectionSubtitle}>
                    These figures are computed from the tokens this dashboard recorded, priced with the table below.
                    They cover chat requests only — ingestion embeddings, the prepdocs and refresh scripts and any
                    other workload sharing the Azure OpenAI resource are not included, so this is not a bill.
                </p>
                <dl className={styles.factGrid}>
                    <div>
                        <dt>Estimated cost</dt>
                        <dd>{formatCost(summary.kpis.estCostMicros, currency)}</dd>
                    </div>
                    <div>
                        <dt>Requests recorded</dt>
                        <dd>{formatExactCount(summary.kpis.requests)}</dd>
                    </div>
                    <div>
                        <dt>Tokens in / out</dt>
                        <dd>
                            {formatCount(summary.kpis.tokensIn)} / {formatCount(summary.kpis.tokensOut)}
                        </dd>
                    </div>
                    <div>
                        <dt>Cached input tokens</dt>
                        <dd>{formatCount(summary.kpis.tokensCached)}</dd>
                    </div>
                </dl>
                {summary.kpis.unpricedCount > 0 ? (
                    <p className={styles.warningLine} role="status">
                        {formatExactCount(summary.kpis.unpricedCount)} request(s) ran on a model with no price and are
                        excluded from the totals above.
                    </p>
                ) : null}
            </section>

            <PriceEditor currency={currency} />
        </div>
    );
}

/** Editing a price never rewrites history: stored rows keep the cost computed at the time. */
function PriceEditor({ currency }: { currency: string }) {
    const [payload, setPayload] = useState<PricePayload | null>(null);
    const [draft, setDraft] = useState<Record<string, { input: string; cachedInput: string; output: string }>>({});
    const [status, setStatus] = useState("");
    const [isSaving, setIsSaving] = useState(false);
    const [newModel, setNewModel] = useState("");
    const [newPrice, setNewPrice] = useState({ input: "", cachedInput: "", output: "" });

    useEffect(() => {
        const controller = new AbortController();
        getTelemetryPricingApi(controller.signal)
            .then(result => {
                setPayload(result);
                setDraft(
                    Object.fromEntries(
                        Object.entries(result.prices).map(([model, price]) => [
                            model,
                            { input: String(price.input), cachedInput: String(price.cachedInput), output: String(price.output) }
                        ])
                    )
                );
            })
            .catch(error => {
                if (error instanceof DOMException && error.name === "AbortError") return;
                setStatus(error instanceof Error ? error.message : String(error));
            });
        return () => controller.abort();
    }, []);

    if (!payload) return null;

    const save = async () => {
        setIsSaving(true);
        setStatus("");
        try {
            const entries = Object.entries(draft);
            const trimmed = newModel.trim();
            if (trimmed) {
                // A new model only needs an input price to be worth saving; the backend fills the
                // rest, and an omitted cached rate is better than a guessed one.
                entries.push([trimmed, newPrice]);
            }
            const prices = Object.fromEntries(
                entries.map(([model, values]) => [
                    model,
                    { input: Number(values.input), cachedInput: Number(values.cachedInput), output: Number(values.output) }
                ])
            );
            const saved = await saveTelemetryPricingApi(prices, "edited from the telemetry dashboard");
            setPayload(saved);
            setNewModel("");
            setNewPrice({ input: "", cachedInput: "", output: "" });
            setStatus("Prices saved. Existing records keep the cost they were written with.");
        } catch (error) {
            setStatus(error instanceof Error ? error.message : String(error));
        } finally {
            setIsSaving(false);
        }
    };

    return (
        <details className={styles.panelInner}>
            <summary className={styles.sectionTitle}>Price table</summary>
            <p className={styles.sectionSubtitle}>
                {currency} per million tokens. A model that is not listed here counts as unpriced and its requests are
                left out of every cost figure rather than being reported as free — add it here to price it.
            </p>
            <div className={styles.tableWrap}>
                <table className={styles.table}>
                    <thead>
                        <tr>
                            <th scope="col">Model</th>
                            <th scope="col">Input</th>
                            <th scope="col">Cached input</th>
                            <th scope="col">Output</th>
                            <th scope="col">Source</th>
                        </tr>
                    </thead>
                    <tbody>
                        {Object.entries(payload.prices).map(([model, price]) => (
                            <tr key={model}>
                                <th scope="row">{model}</th>
                                {(["input", "cachedInput", "output"] as const).map(field => (
                                    <td key={field}>
                                        <input
                                            className={styles.priceInput}
                                            type="number"
                                            min="0"
                                            step="0.0001"
                                            value={draft[model]?.[field] ?? ""}
                                            onChange={event =>
                                                setDraft(previous => ({
                                                    ...previous,
                                                    [model]: { ...previous[model], [field]: event.target.value }
                                                }))
                                            }
                                            aria-label={`${model} ${field} price`}
                                        />
                                    </td>
                                ))}
                                <td className={styles.mutedCell}>{price.source}</td>
                            </tr>
                        ))}
                        {/* Without this row the editor cannot do the job the docs give it: an
                            unpriced model is by construction absent from `payload.prices`, so it
                            never appears above, and there is no other way to add a price. */}
                        <tr>
                            <th scope="row">
                                <input
                                    className={styles.priceInput}
                                    type="text"
                                    placeholder="new model id"
                                    value={newModel}
                                    onChange={event => setNewModel(event.target.value)}
                                    aria-label="New model id"
                                />
                            </th>
                            {(["input", "cachedInput", "output"] as const).map(field => (
                                <td key={field}>
                                    <input
                                        className={styles.priceInput}
                                        type="number"
                                        min="0"
                                        step="0.0001"
                                        value={newPrice[field]}
                                        onChange={event =>
                                            setNewPrice(previous => ({ ...previous, [field]: event.target.value }))
                                        }
                                        aria-label={`New model ${field} price`}
                                    />
                                </td>
                            ))}
                            <td className={styles.mutedCell}>new</td>
                        </tr>
                    </tbody>
                </table>
            </div>
            <div className={styles.inlineActions}>
                <button type="button" className={styles.primaryButton} onClick={save} disabled={isSaving}>
                    {isSaving ? "Saving\u2026" : "Save prices"}
                </button>
                <span className={styles.kpiHint} role="status">
                    {status}
                </span>
            </div>
        </details>
    );
}
