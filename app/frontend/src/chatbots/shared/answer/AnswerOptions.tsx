import { useEffect, useMemo, useState } from "react";

import styles from "./AnswerOptions.module.css";
import { OptionTexts, ParsedChoice, resolveChoiceOptions } from "./optionMarkers";

interface AnswerOptionsProps {
    parsed: ParsedChoice;
    texts: OptionTexts;
    // The value chosen on the following turn (answers[i + 1]?.[0]); undefined while
    // this is the latest message and still awaiting a choice.
    selectedValue?: string;
    // Read-only once a newer turn exists / while loading. The group still shows the
    // selection but is no longer interactive.
    locked: boolean;
    onSelect: (value: string) => void;
    onOther?: () => void;
}

const CheckIcon = () => (
    <svg className={styles.checkIcon} viewBox="0 0 20 20" aria-hidden="true" focusable="false">
        <path d="M16.7 5.3a1 1 0 0 1 0 1.4l-7.5 7.5a1 1 0 0 1-1.4 0L3.3 9.7a1 1 0 0 1 1.4-1.4l3.8 3.8 6.8-6.8a1 1 0 0 1 1.4 0Z" />
    </svg>
);

// Topic and knowledge-level choices read best as a vertical list (long labels,
// descriptions); mode/count/generic are compact enough for a wrapping row.
const isListLayout = (kind: ParsedChoice["kind"]) => kind === "level" || kind === "topic";

export const AnswerOptions = ({ parsed, texts, selectedValue, locked, onSelect, onOther }: AnswerOptionsProps) => {
    const options = useMemo(() => resolveChoiceOptions(parsed, texts), [parsed, texts]);
    const markerKey = useMemo(() => `${parsed.kind}|${parsed.allowOther}|${parsed.rawOptions.join("\u001f")}`, [parsed]);
    const [optimisticSelectedValue, setOptimisticSelectedValue] = useState<string | undefined>();
    const [optimisticOtherSelected, setOptimisticOtherSelected] = useState(false);
    const displaySelectedValue = selectedValue ?? optimisticSelectedValue;
    const hasMatch = displaySelectedValue !== undefined && options.some(option => option.value === displaySelectedValue);
    // A locked turn whose selection matches no predefined value (and Other was
    // available) means the user typed a free answer via "Andere Option".
    const otherSelected = parsed.allowOther && (selectedValue !== undefined ? !hasMatch : optimisticOtherSelected);
    const list = isListLayout(parsed.kind);

    useEffect(() => {
        setOptimisticSelectedValue(undefined);
        setOptimisticOtherSelected(false);
    }, [markerKey]);

    return (
        <div className={`${styles.group} ${list ? styles.groupList : styles.groupRow} ${locked ? styles.groupLocked : ""}`} role="group">
            {options.map(option => {
                const selected = option.value === displaySelectedValue;
                return (
                    <button
                        key={option.value}
                        type="button"
                        className={`${styles.option} ${selected ? styles.optionSelected : ""}`}
                        aria-pressed={selected}
                        disabled={locked}
                        onClick={() => {
                            setOptimisticSelectedValue(option.value);
                            setOptimisticOtherSelected(false);
                            onSelect(option.value);
                        }}
                    >
                        {list ? <span className={styles.radio} aria-hidden="true" /> : selected ? <CheckIcon /> : null}
                        <span className={styles.optionBody}>
                            <span className={styles.optionLabel}>{option.label}</span>
                            {option.description && <span className={styles.optionDescription}>{option.description}</span>}
                        </span>
                    </button>
                );
            })}

            {parsed.allowOther && onOther && (
                <button
                    type="button"
                    className={`${styles.option} ${styles.optionOther} ${otherSelected ? styles.optionSelected : ""}`}
                    aria-pressed={otherSelected}
                    disabled={locked}
                    onClick={() => {
                        setOptimisticSelectedValue(undefined);
                        setOptimisticOtherSelected(true);
                        onOther();
                    }}
                >
                    {list ? <span className={styles.radio} aria-hidden="true" /> : otherSelected ? <CheckIcon /> : null}
                    <span className={styles.optionBody}>
                        <span className={styles.optionLabel}>{texts.other}</span>
                    </span>
                </button>
            )}
        </div>
    );
};
