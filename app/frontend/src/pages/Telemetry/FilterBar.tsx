import { useEffect, useRef, useState } from "react";

import { formatChatbotLabel } from "../shared/chatbotDisplay";
import { timeZoneLabel } from "./charts/scales";
import styles from "./TelemetryPage.module.css";
import { TelemetryFilters } from "./telemetryApi";
import { PATH_LABELS, RANGE_OPTIONS, STATUS_OPTIONS, TelemetryQueryState } from "./useTelemetryQuery";

/**
 * The page-level filter surface. Everything here narrows the whole page.
 *
 * Bucket granularity is deliberately NOT here: it changes the x axis of one chart and nothing else,
 * so among controls that all filter every panel it would advertise a reach it does not have. Its
 * control sits on the chart it governs.
 *
 * Every non-default choice also renders as a removable chip directly beneath the bar, so the active
 * filters are never hidden inside a collapsed popover — the failure mode where somebody reads a
 * number, forgets a bot filter is on, and draws the wrong conclusion. The chip row is height-capped
 * and scrolls rather than wrapping indefinitely, so it cannot push the KPI row below the fold.
 */

interface MultiSelectProps {
    label: string;
    options: { value: string; label: string; hint?: string }[];
    selected: string[];
    onToggle: (value: string) => void;
    onClear: () => void;
    searchable?: boolean;
}

function MultiSelect({ label, options, selected, onToggle, onClear, searchable }: MultiSelectProps) {
    const [open, setOpen] = useState(false);
    const [search, setSearch] = useState("");
    const containerRef = useRef<HTMLDivElement | null>(null);

    useEffect(() => {
        if (!open) return;
        const onPointerDown = (event: MouseEvent) => {
            if (containerRef.current && !containerRef.current.contains(event.target as Node)) setOpen(false);
        };
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === "Escape") setOpen(false);
        };
        document.addEventListener("mousedown", onPointerDown);
        document.addEventListener("keydown", onKeyDown);
        return () => {
            document.removeEventListener("mousedown", onPointerDown);
            document.removeEventListener("keydown", onKeyDown);
        };
    }, [open]);

    const summary =
        selected.length === 0 ? `All ${label.toLowerCase()}` : selected.length === 1 ? options.find(option => option.value === selected[0])?.label ?? selected[0] : `${selected.length} ${label.toLowerCase()}`;

    const visible = search ? options.filter(option => option.label.toLowerCase().includes(search.toLowerCase())) : options;

    return (
        <div className={styles.popoverHost} ref={containerRef}>
            <button
                type="button"
                className={`${styles.control} ${selected.length ? styles.controlActive : ""}`}
                aria-haspopup="dialog"
                aria-expanded={open}
                onClick={() => setOpen(value => !value)}
            >
                <span className={styles.controlLabel}>{label}</span>
                <span className={styles.controlValue}>{summary}</span>
            </button>
            {open ? (
                <div className={styles.popover} role="dialog" aria-label={`Filter by ${label.toLowerCase()}`}>
                    {searchable ? (
                        <input
                            className={styles.popoverSearch}
                            type="search"
                            placeholder={`Search ${label.toLowerCase()}`}
                            value={search}
                            onChange={event => setSearch(event.target.value)}
                            autoFocus
                        />
                    ) : null}
                    <div className={styles.popoverList}>
                        {visible.map(option => (
                            <label key={option.value} className={styles.popoverOption}>
                                <input
                                    type="checkbox"
                                    checked={selected.includes(option.value)}
                                    onChange={() => onToggle(option.value)}
                                />
                                <span>{option.label}</span>
                                {option.hint ? <span className={styles.popoverHint}>{option.hint}</span> : null}
                            </label>
                        ))}
                        {visible.length === 0 ? <p className={styles.popoverEmpty}>Nothing matches.</p> : null}
                    </div>
                    {selected.length ? (
                        <button type="button" className={styles.popoverClear} onClick={onClear}>
                            Clear selection
                        </button>
                    ) : null}
                </div>
            ) : null}
        </div>
    );
}

export interface FilterBarProps {
    state: TelemetryQueryState;
    filters: TelemetryFilters | null;
    onUpdate: (patch: Partial<TelemetryQueryState>) => void;
    onToggle: (key: "chatbots" | "models" | "paths", value: string) => void;
    onReset: () => void;
    onRefresh: () => void;
    onExport: () => void;
    hasActiveFilters: boolean;
    isBusy: boolean;
    dataThrough?: string;
    isExporting: boolean;
}

export function FilterBar({
    state,
    filters,
    onUpdate,
    onToggle,
    onReset,
    onRefresh,
    onExport,
    hasActiveFilters,
    isBusy,
    dataThrough,
    isExporting
}: FilterBarProps) {
    const usingCustomRange = Boolean(state.from && state.to);
    const [customOpen, setCustomOpen] = useState(usingCustomRange);

    const chatbotOptions = (filters?.chatbots ?? []).map(entry => ({
        value: entry.name,
        label: entry.displayName || formatChatbotLabel(entry.name),
        hint: entry.kind === "dynamic" ? "provisioned" : undefined
    }));
    const modelOptions = (filters?.models ?? []).map(model => ({ value: model, label: model }));

    const chips: { key: string; label: string; onRemove: () => void }[] = [];
    for (const name of state.chatbots) {
        chips.push({
            key: `chatbot-${name}`,
            label: chatbotOptions.find(option => option.value === name)?.label ?? name,
            onRemove: () => onToggle("chatbots", name)
        });
    }
    for (const model of state.models) {
        chips.push({ key: `model-${model}`, label: model, onRemove: () => onToggle("models", model) });
    }
    for (const path of state.paths) {
        chips.push({ key: `path-${path}`, label: PATH_LABELS[path] ?? path, onRemove: () => onToggle("paths", path) });
    }
    if (state.status !== "all") {
        chips.push({
            key: "status",
            label: STATUS_OPTIONS.find(option => option.value === state.status)?.label ?? state.status,
            onRemove: () => onUpdate({ status: "all" })
        });
    }
    if (state.search) {
        chips.push({ key: "search", label: `"${state.search}"`, onRemove: () => onUpdate({ search: "" }) });
    }

    return (
        <div className={styles.filterBar}>
            <div className={styles.filterRow}>
                <div className={styles.segmented} role="group" aria-label="Date range">
                    {RANGE_OPTIONS.map(option => (
                        <button
                            key={option.value}
                            type="button"
                            className={styles.segment}
                            aria-pressed={!usingCustomRange && state.range === option.value}
                            onClick={() => {
                                setCustomOpen(false);
                                onUpdate({ range: option.value });
                            }}
                        >
                            {option.label}
                        </button>
                    ))}
                    <button
                        type="button"
                        className={styles.segment}
                        aria-pressed={usingCustomRange}
                        onClick={() => setCustomOpen(value => !value)}
                    >
                        Custom
                    </button>
                </div>

                {customOpen ? (
                    <div className={styles.customRange}>
                        <label className={styles.inlineLabel}>
                            From
                            <input
                                type="date"
                                value={state.from}
                                max={state.to || undefined}
                                onChange={event => onUpdate({ from: event.target.value, to: state.to || event.target.value })}
                            />
                        </label>
                        <label className={styles.inlineLabel}>
                            To
                            <input
                                type="date"
                                value={state.to}
                                min={state.from || undefined}
                                onChange={event => onUpdate({ to: event.target.value, from: state.from || event.target.value })}
                            />
                        </label>
                    </div>
                ) : null}

                <MultiSelect
                    label="Chatbots"
                    options={chatbotOptions}
                    selected={state.chatbots}
                    onToggle={value => onToggle("chatbots", value)}
                    onClear={() => onUpdate({ chatbots: [] })}
                    searchable
                />
                <MultiSelect
                    label="Models"
                    options={modelOptions}
                    selected={state.models}
                    onToggle={value => onToggle("models", value)}
                    onClear={() => onUpdate({ models: [] })}
                />
                <MultiSelect
                    label="Paths"
                    options={(filters?.paths ?? []).map(path => ({ value: path, label: PATH_LABELS[path] ?? path }))}
                    selected={state.paths}
                    onToggle={value => onToggle("paths", value)}
                    onClear={() => onUpdate({ paths: [] })}
                />

                <div className={styles.segmented} role="group" aria-label="Status">
                    {STATUS_OPTIONS.map(option => (
                        <button
                            key={option.value}
                            type="button"
                            className={styles.segment}
                            aria-pressed={state.status === option.value}
                            onClick={() => onUpdate({ status: option.value })}
                        >
                            {option.label}
                        </button>
                    ))}
                </div>

                <div className={styles.filterActions}>
                    {hasActiveFilters ? (
                        <button type="button" className={styles.secondaryButton} onClick={onReset}>
                            Reset
                        </button>
                    ) : null}
                    <button type="button" className={styles.secondaryButton} onClick={onRefresh} disabled={isBusy}>
                        Refresh
                    </button>
                    <button type="button" className={styles.primaryButton} onClick={onExport} disabled={isExporting}>
                        {isExporting ? "Preparing…" : "Export CSV"}
                    </button>
                </div>
            </div>

            {chips.length ? (
                <div className={styles.chipRow}>
                    {chips.map(chip => (
                        <button key={chip.key} type="button" className={styles.chip} onClick={chip.onRemove}>
                            {chip.label}
                            <span aria-hidden="true">×</span>
                            <span className={styles.visuallyHidden}>Remove this filter</span>
                        </button>
                    ))}
                </div>
            ) : null}

            <p className={styles.filterCaption}>
                Times are shown in German time ({timeZoneLabel()}); day buckets are UTC calendar days.
                Filters combine as OR within a group and AND across groups.
                {dataThrough ? ` Data through ${dataThrough}.` : ""}
            </p>
        </div>
    );
}
