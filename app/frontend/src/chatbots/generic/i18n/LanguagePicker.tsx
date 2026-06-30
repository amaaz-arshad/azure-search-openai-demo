import type { CSSProperties, FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { LocalLanguage24Regular } from "@fluentui/react-icons";
import { Dropdown, IDropdownOption } from "@fluentui/react";
import { useId } from "@fluentui/react-hooks";

import { GENERIC_SUPPORTED_LANGUAGES } from "./createGenericI18n";

/** Language selector for dynamic bots — mirrors the built-in bots' picker, driven by the shared
 * supported-language set and i18next's active language. */
export function LanguagePicker() {
    const { t, i18n } = useTranslation();
    const pickerId = useId("genericLanguagePicker");

    const onChange = (_ev: FormEvent<HTMLDivElement>, option?: IDropdownOption<string>) => {
        const code = (option?.data as string) || i18n.language;
        void i18n.changeLanguage(code);
    };

    return (
        <div style={wrapperStyle}>
            <LocalLanguage24Regular />
            <Dropdown
                id={pickerId}
                selectedKey={i18n.language}
                options={Object.entries(GENERIC_SUPPORTED_LANGUAGES).map(([code, details]) => ({
                    key: code,
                    text: details.name,
                    data: code
                }))}
                onChange={onChange}
                ariaLabel={t("labels.languagePicker")}
            />
        </div>
    );
}

const wrapperStyle: CSSProperties = { display: "flex", alignItems: "center", gap: 8 };
