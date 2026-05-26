import { useState } from "react";
import { Helmet } from "react-helmet-async";
import { Link, useParams } from "react-router-dom";

import {
    ChevronDownIcon,
    ChevronLeftIcon,
    PillCloseIcon,
    PlusIcon,
    SectionAssessFormatIcon,
    SectionDesignIcon,
    SectionDisclaimerIcon,
    SectionFeaturesIcon,
    SectionGeneralIcon,
    SectionGreetingIcon,
    SectionLanguagesIcon,
    SectionLlmIcon,
    SectionLoginIcon,
    SectionModesIcon,
    SectionPromptIcon,
    SectionQaBehaviorIcon,
    SectionTutorLevelIcon,
    SectionTutorMethodIcon,
    ToggleAllIcon,
    UploadCloudIcon
} from "../components/icons";
import { useToast } from "../components/Toast";

/*
 * Ported from D:\working student\snap\nerilio backend\views\configure.php
 *
 * Per-chatbot configuration screen. Faithful structure:
 *   - Page header with back-link + title + customer meta
 *   - Page tabs (Allgemein / Q&A / Tutor / Assessment — last three appear when their
 *     mode checkbox is checked in the General > Modi section)
 *   - Each tab contains collapsible sections with form-row + checkbox-group + select +
 *     color picker + upload zones + language pills/tabs + toggle option group + KB list
 *   - Action bar at the bottom (Speichern / Änderungen verwerfen)
 *
 * Empty shell: form inputs are uncontrolled/defaulted; "Speichern" shows a toast.
 * Live interactions kept: section accordion, "Alle ausklappen", mode-tab visibility,
 * page-tab switching, color sync, login provider toggle, language pills.
 */

type TabId = "tab-general" | "tab-qa" | "tab-tutor" | "tab-assessment";

const ALL_SECTION_IDS = [
    "sec-general",
    "sec-languages",
    "sec-llm",
    "sec-prompt",
    "sec-modes",
    "sec-kb",
    "sec-design",
    "sec-greeting",
    "sec-disclaimer",
    "sec-flagged",
    "sec-features",
    "sec-login",
    "sec-qa-behavior",
    "sec-tutor-level",
    "sec-tutor-method",
    "sec-assess-format"
] as const;
type SectionId = (typeof ALL_SECTION_IDS)[number];

const AVAILABLE_LANGUAGES = [
    "Deutsch",
    "Englisch",
    "Französisch",
    "Spanisch",
    "Italienisch",
    "Portugiesisch",
    "Niederländisch",
    "Polnisch",
    "Russisch",
    "Arabisch",
    "Chinesisch (vereinfacht)",
    "Japanisch",
    "Koreanisch",
    "Türkisch"
];

const LANG_CODE: Record<string, string> = {
    Deutsch: "DE",
    Englisch: "EN",
    Französisch: "FR",
    Spanisch: "ES",
    Italienisch: "IT",
    Portugiesisch: "PT",
    Niederländisch: "NL",
    Polnisch: "PL",
    Russisch: "RU",
    Arabisch: "AR",
    "Chinesisch (vereinfacht)": "ZH",
    Japanisch: "JA",
    Koreanisch: "KO",
    Türkisch: "TR"
};

type LangTextareaKey = "greeting" | "disclaimer" | "flagged";

export function ConfigurePage() {
    const params = useParams<{ botId?: string }>();
    const botId = params.botId ?? "?";
    const { showToast, toastNode } = useToast();

    const [activeTab, setActiveTab] = useState<TabId>("tab-general");
    const [collapsed, setCollapsed] = useState<Record<SectionId, boolean>>(() =>
        Object.fromEntries(ALL_SECTION_IDS.map(id => [id, true])) as Record<SectionId, boolean>
    );

    const [modes, setModes] = useState({ qa: true, tutor: false, assessment: false });

    const [primaryHex, setPrimaryHex] = useState("#AC44C6");
    const [secondaryHex, setSecondaryHex] = useState("#00cc96");

    const [loginRequired, setLoginRequired] = useState(false);

    const [selectedLangs, setSelectedLangs] = useState<string[]>(["Deutsch"]);
    const [langToAdd, setLangToAdd] = useState("");
    const [activeLangTab, setActiveLangTab] = useState<Record<LangTextareaKey, string>>({
        greeting: "Deutsch",
        disclaimer: "Deutsch",
        flagged: "Deutsch"
    });
    const [langContent, setLangContent] = useState<Record<LangTextareaKey, Record<string, string>>>({
        greeting: { Deutsch: "Willkommen! Wie kann ich Ihnen helfen?" },
        disclaimer: {
            Deutsch: "KI-gestützter Assistent. Antworten werden automatisiert generiert, verbindlich sind offizielle Quellen."
        },
        flagged: { Deutsch: "" }
    });

    const toggleSection = (id: SectionId) => setCollapsed(prev => ({ ...prev, [id]: !prev[id] }));

    const allCollapsed = ALL_SECTION_IDS.every(id => collapsed[id]);

    const toggleAll = () => {
        const next = allCollapsed;
        setCollapsed(Object.fromEntries(ALL_SECTION_IDS.map(id => [id, !next])) as Record<SectionId, boolean>);
    };

    const addLanguage = () => {
        if (!langToAdd || selectedLangs.includes(langToAdd)) return;
        setSelectedLangs(prev => [...prev, langToAdd]);
        setLangToAdd("");
    };

    const removeLanguage = (lang: string) => {
        if (selectedLangs.length === 1) return;
        setSelectedLangs(prev => prev.filter(l => l !== lang));
        setActiveLangTab(prev => {
            const next = { ...prev };
            (["greeting", "disclaimer", "flagged"] as const).forEach(key => {
                if (next[key] === lang) {
                    next[key] = selectedLangs.find(l => l !== lang) ?? "Deutsch";
                }
            });
            return next;
        });
    };

    const handleSave = () => {
        showToast("Änderungen gespeichert (Demo)");
    };

    const handleDiscard = () => {
        // Source uses confirm() + reload — in this empty shell we just toast.
        showToast("Änderungen verworfen (Demo)");
    };

    const renderLangTabs = (key: LangTextareaKey) => (
        <div className="lang-tabs-wrap">
            <div className="lang-tabs">
                {selectedLangs.map(lang => (
                    <button
                        key={lang}
                        type="button"
                        className={"lang-tab" + (activeLangTab[key] === lang ? " active" : "")}
                        onClick={() => setActiveLangTab(prev => ({ ...prev, [key]: lang }))}
                    >
                        {LANG_CODE[lang] ?? lang.slice(0, 2).toUpperCase()}
                    </button>
                ))}
            </div>
            <div>
                {selectedLangs.map(lang => (
                    <div key={lang} className={"lang-panel" + (activeLangTab[key] === lang ? " active" : "")}>
                        <textarea
                            rows={3}
                            value={langContent[key][lang] ?? ""}
                            onChange={event =>
                                setLangContent(prev => ({
                                    ...prev,
                                    [key]: { ...prev[key], [lang]: event.target.value }
                                }))
                            }
                        />
                    </div>
                ))}
            </div>
        </div>
    );

    const sectionClass = (id: SectionId) => "section" + (collapsed[id] ? " collapsed" : "");

    return (
        <div className="configure-content">
            <div className="page-header">
                <Link to="/verwaltung/dashboard" className="back-link">
                    <ChevronLeftIcon />
                    Zurück zum Dashboard
                </Link>
                <h1>Chatbot konfigurieren</h1>
                <p className="page-header-meta">Bot-ID: {botId}</p>
            </div>

            <div className="page-tabs">
                <button
                    type="button"
                    className={"page-tab" + (activeTab === "tab-general" ? " active" : "")}
                    onClick={() => setActiveTab("tab-general")}
                >
                    <span className="tab-dot" /> Allgemein
                </button>
                {modes.qa && (
                    <button
                        type="button"
                        className={"page-tab" + (activeTab === "tab-qa" ? " active" : "")}
                        onClick={() => setActiveTab("tab-qa")}
                    >
                        <span className="tab-dot" /> Q&amp;A
                    </button>
                )}
                {modes.tutor && (
                    <button
                        type="button"
                        className={"page-tab" + (activeTab === "tab-tutor" ? " active" : "")}
                        onClick={() => setActiveTab("tab-tutor")}
                    >
                        <span className="tab-dot" /> Tutor
                    </button>
                )}
                {modes.assessment && (
                    <button
                        type="button"
                        className={"page-tab" + (activeTab === "tab-assessment" ? " active" : "")}
                        onClick={() => setActiveTab("tab-assessment")}
                    >
                        <span className="tab-dot" /> Assessment
                    </button>
                )}
            </div>

            {/* TAB: Allgemein */}
            <div className={"tab-panel" + (activeTab === "tab-general" ? " active" : "")}>
                <div className="sections-toolbar">
                    <button type="button" className="toggle-all-btn" onClick={toggleAll}>
                        <ToggleAllIcon expanded={!allCollapsed} />
                        <span>{allCollapsed ? "Alle ausklappen" : "Alle schließen"}</span>
                    </button>
                </div>

                <div className="config-form">
                    {/* Allgemein */}
                    <div className={sectionClass("sec-general")}>
                        <button type="button" className="section-toggle" onClick={() => toggleSection("sec-general")}>
                            <div className="section-toggle-left">
                                <div className="section-icon">
                                    <SectionGeneralIcon />
                                </div>
                                <span className="section-title">Allgemein</span>
                            </div>
                            <ChevronDownIcon className="chevron" />
                        </button>
                        <div className="section-body">
                            <div className="form-row">
                                <div className="form-group">
                                    <label htmlFor="vw-bot-name">Name</label>
                                    <input type="text" id="vw-bot-name" defaultValue="" />
                                </div>
                                <div className="form-group">
                                    <label htmlFor="vw-bot-botname">Botname (URL)</label>
                                    <div className="botname-wrap">
                                        <span className="botname-prefix">chat.nerilio.ai/</span>
                                        <input type="text" className="botname-field" id="vw-bot-botname" autoComplete="off" spellCheck={false} />
                                    </div>
                                    <div className="botname-preview" />
                                </div>
                                <div className="form-group">
                                    <label>Kunde</label>
                                    <input type="text" defaultValue="" readOnly />
                                </div>
                                <div className="form-group">
                                    <label htmlFor="vw-bot-ansprache">Ansprache</label>
                                    <div className="select-wrap">
                                        <select id="vw-bot-ansprache" defaultValue="informal">
                                            <option value="informal">Informell (Du)</option>
                                            <option value="formal">Formell (Sie)</option>
                                        </select>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    {/* Sprachen */}
                    <div className={sectionClass("sec-languages")}>
                        <button type="button" className="section-toggle" onClick={() => toggleSection("sec-languages")}>
                            <div className="section-toggle-left">
                                <div className="section-icon">
                                    <SectionLanguagesIcon />
                                </div>
                                <span className="section-title">Sprachen</span>
                            </div>
                            <ChevronDownIcon className="chevron" />
                        </button>
                        <div className="section-body">
                            <div className="form-group">
                                <label>Sprache hinzufügen</label>
                                <div className="lang-row">
                                    <div className="select-wrap">
                                        <select value={langToAdd} onChange={event => setLangToAdd(event.target.value)}>
                                            <option value="">Sprache wählen …</option>
                                            {AVAILABLE_LANGUAGES.filter(lang => !selectedLangs.includes(lang)).map(lang => (
                                                <option key={lang} value={lang}>
                                                    {lang}
                                                </option>
                                            ))}
                                        </select>
                                    </div>
                                    <button type="button" className="lang-add-btn" onClick={addLanguage}>
                                        Hinzufügen
                                    </button>
                                </div>
                                <div className="pills">
                                    {selectedLangs.map(lang => (
                                        <span key={lang} className="pill">
                                            {lang}
                                            <button
                                                type="button"
                                                className="pill-remove"
                                                aria-label={`${lang} entfernen`}
                                                onClick={() => removeLanguage(lang)}
                                            >
                                                <PillCloseIcon />
                                            </button>
                                        </span>
                                    ))}
                                </div>
                            </div>
                        </div>
                    </div>

                    {/* LLM */}
                    <div className={sectionClass("sec-llm")}>
                        <button type="button" className="section-toggle" onClick={() => toggleSection("sec-llm")}>
                            <div className="section-toggle-left">
                                <div className="section-icon">
                                    <SectionLlmIcon />
                                </div>
                                <span className="section-title">Sprachmodell (LLM)</span>
                            </div>
                            <ChevronDownIcon className="chevron" />
                        </button>
                        <div className="section-body">
                            <div className="form-group" style={{ maxWidth: 360 }}>
                                <label htmlFor="vw-llm-select">Modell</label>
                                <div className="select-wrap">
                                    <select id="vw-llm-select" defaultValue="gpt-5">
                                        <option value="gpt-5">GPT-5 (OpenAI)</option>
                                        <option value="gpt-4o">GPT-4o (OpenAI)</option>
                                        <option value="claude-opus-4">Claude Opus 4 (Anthropic)</option>
                                        <option value="claude-sonnet-4">Claude Sonnet 4 (Anthropic)</option>
                                        <option value="gemini-2-pro">Gemini 2.0 Pro (Google)</option>
                                        <option value="gemini-2-flash">Gemini 2.0 Flash (Google)</option>
                                        <option value="llama-3-70b">Llama 3 70B (Meta)</option>
                                        <option value="mistral-large">Mistral Large</option>
                                    </select>
                                </div>
                            </div>
                        </div>
                    </div>

                    {/* Prompt */}
                    <div className={sectionClass("sec-prompt")}>
                        <button type="button" className="section-toggle" onClick={() => toggleSection("sec-prompt")}>
                            <div className="section-toggle-left">
                                <div className="section-icon">
                                    <SectionPromptIcon />
                                </div>
                                <span className="section-title">Prompt</span>
                            </div>
                            <ChevronDownIcon className="chevron" />
                        </button>
                        <div className="section-body">
                            <div className="form-group">
                                <label htmlFor="vw-bot-prompt">System-Prompt</label>
                                <textarea
                                    id="vw-bot-prompt"
                                    rows={12}
                                    placeholder="Du bist ein hilfreicher Assistent …"
                                    style={{ fontFamily: "ui-monospace, monospace", fontSize: 13, lineHeight: 1.65, minHeight: 220 }}
                                />
                            </div>
                        </div>
                    </div>

                    {/* Modi */}
                    <div className={sectionClass("sec-modes")}>
                        <button type="button" className="section-toggle" onClick={() => toggleSection("sec-modes")}>
                            <div className="section-toggle-left">
                                <div className="section-icon">
                                    <SectionModesIcon />
                                </div>
                                <span className="section-title">Modi</span>
                            </div>
                            <ChevronDownIcon className="chevron" />
                        </button>
                        <div className="section-body">
                            <div className="checkbox-group">
                                <label className="checkbox-item">
                                    <input
                                        type="checkbox"
                                        checked={modes.qa}
                                        onChange={event => setModes(prev => ({ ...prev, qa: event.target.checked }))}
                                    />
                                    <div>
                                        <div className="checkbox-label">Q&amp;A</div>
                                        <div className="checkbox-desc">Der Bot beantwortet Fragen direkt aus der Wissensdatenbank.</div>
                                    </div>
                                </label>
                                <label className="checkbox-item">
                                    <input
                                        type="checkbox"
                                        checked={modes.tutor}
                                        onChange={event => setModes(prev => ({ ...prev, tutor: event.target.checked }))}
                                    />
                                    <div>
                                        <div className="checkbox-label">Tutor</div>
                                        <div className="checkbox-desc">Der Bot erklärt Themen schrittweise.</div>
                                    </div>
                                </label>
                                <label className="checkbox-item">
                                    <input
                                        type="checkbox"
                                        checked={modes.assessment}
                                        onChange={event => setModes(prev => ({ ...prev, assessment: event.target.checked }))}
                                    />
                                    <div>
                                        <div className="checkbox-label">Assessment</div>
                                        <div className="checkbox-desc">Der Bot prüft das Wissen des Nutzers.</div>
                                    </div>
                                </label>
                            </div>
                        </div>
                    </div>

                    {/* Wissensdatenbanken */}
                    <div className={sectionClass("sec-kb")}>
                        <button type="button" className="section-toggle" onClick={() => toggleSection("sec-kb")}>
                            <div className="section-toggle-left">
                                <div className="section-icon">
                                    <SectionGeneralIcon />
                                </div>
                                <span className="section-title">Wissensdatenbanken</span>
                            </div>
                            <ChevronDownIcon className="chevron" />
                        </button>
                        <div className="section-body">
                            <div className="kb-list">
                                <div className="kb-empty">Noch keine Wissensdatenbank zugewiesen.</div>
                            </div>
                            <Link to="/verwaltung/knowledge-bases" className="kb-manage">
                                <PlusIcon />
                                Wissensdatenbanken verwalten
                            </Link>
                        </div>
                    </div>

                    {/* Design */}
                    <div className={sectionClass("sec-design")}>
                        <button type="button" className="section-toggle" onClick={() => toggleSection("sec-design")}>
                            <div className="section-toggle-left">
                                <div className="section-icon">
                                    <SectionDesignIcon />
                                </div>
                                <span className="section-title">Design</span>
                            </div>
                            <ChevronDownIcon className="chevron" />
                        </button>
                        <div className="section-body">
                            <div className="form-row">
                                <div className="form-group">
                                    <label>Hauptfarbe</label>
                                    <div className="color-row">
                                        <div className="color-swatch">
                                            <input
                                                type="color"
                                                value={primaryHex}
                                                onChange={event => setPrimaryHex(event.target.value)}
                                            />
                                        </div>
                                        <input
                                            type="text"
                                            className="color-hex"
                                            value={primaryHex}
                                            maxLength={7}
                                            onChange={event => {
                                                const v = event.target.value;
                                                setPrimaryHex(v);
                                            }}
                                        />
                                    </div>
                                </div>
                                <div className="form-group">
                                    <label>Zweitfarbe</label>
                                    <div className="color-row">
                                        <div className="color-swatch">
                                            <input
                                                type="color"
                                                value={secondaryHex}
                                                onChange={event => setSecondaryHex(event.target.value)}
                                            />
                                        </div>
                                        <input
                                            type="text"
                                            className="color-hex"
                                            value={secondaryHex}
                                            maxLength={7}
                                            onChange={event => setSecondaryHex(event.target.value)}
                                        />
                                    </div>
                                </div>
                            </div>
                            <div className="form-row">
                                <div className="form-group">
                                    <label>Logo (Querformat)</label>
                                    <div className="upload-zone">
                                        <input type="file" accept="image/*" />
                                        <div className="upload-icon">
                                            <UploadCloudIcon width={24} height={24} />
                                        </div>
                                        <div className="upload-label">Datei auswählen</div>
                                        <div className="upload-hint">PNG, SVG, JPG · 400 × 100 px</div>
                                    </div>
                                </div>
                                <div className="form-group">
                                    <label>Icon (Quadratisch)</label>
                                    <div className="upload-zone">
                                        <input type="file" accept="image/*" />
                                        <div className="upload-icon">
                                            <UploadCloudIcon width={24} height={24} />
                                        </div>
                                        <div className="upload-label">Datei auswählen</div>
                                        <div className="upload-hint">PNG, SVG · 256 × 256 px</div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    {/* Begrüßungstext */}
                    <div className={sectionClass("sec-greeting")}>
                        <button type="button" className="section-toggle" onClick={() => toggleSection("sec-greeting")}>
                            <div className="section-toggle-left">
                                <div className="section-icon">
                                    <SectionGreetingIcon />
                                </div>
                                <span className="section-title">Begrüßungstext</span>
                            </div>
                            <ChevronDownIcon className="chevron" />
                        </button>
                        <div className="section-body">
                            <div className="form-group">
                                <label>Startnachricht des Bots</label>
                                {renderLangTabs("greeting")}
                            </div>
                        </div>
                    </div>

                    {/* Disclaimer */}
                    <div className={sectionClass("sec-disclaimer")}>
                        <button type="button" className="section-toggle" onClick={() => toggleSection("sec-disclaimer")}>
                            <div className="section-toggle-left">
                                <div className="section-icon">
                                    <SectionDisclaimerIcon />
                                </div>
                                <span className="section-title">Disclaimer</span>
                            </div>
                            <ChevronDownIcon className="chevron" />
                        </button>
                        <div className="section-body">
                            <div className="form-group">
                                <label>Disclaimer-Text</label>
                                {renderLangTabs("disclaimer")}
                            </div>
                        </div>
                    </div>

                    {/* Blockierte Nachrichten */}
                    <div className={sectionClass("sec-flagged")}>
                        <button type="button" className="section-toggle" onClick={() => toggleSection("sec-flagged")}>
                            <div className="section-toggle-left">
                                <div className="section-icon">
                                    <SectionDisclaimerIcon />
                                </div>
                                <span className="section-title">Blockierte Nachrichten</span>
                            </div>
                            <ChevronDownIcon className="chevron" />
                        </button>
                        <div className="section-body">
                            <div className="form-group">
                                <label>Hinweis bei blockierter Nachricht</label>
                                {renderLangTabs("flagged")}
                            </div>
                        </div>
                    </div>

                    {/* Funktionen */}
                    <div className={sectionClass("sec-features")}>
                        <button type="button" className="section-toggle" onClick={() => toggleSection("sec-features")}>
                            <div className="section-toggle-left">
                                <div className="section-icon">
                                    <SectionFeaturesIcon />
                                </div>
                                <span className="section-title">Funktionen</span>
                            </div>
                            <ChevronDownIcon className="chevron" />
                        </button>
                        <div className="section-body">
                            <div className="checkbox-group">
                                <label className="checkbox-item">
                                    <input type="checkbox" defaultChecked />
                                    <div>
                                        <div className="checkbox-label">Disclaimer anzeigen</div>
                                        <div className="checkbox-desc">Der Disclaimer-Text wird dem Nutzer sichtbar im Chat angezeigt.</div>
                                    </div>
                                </label>
                                <label className="checkbox-item">
                                    <input type="checkbox" defaultChecked />
                                    <div>
                                        <div className="checkbox-label">Verlauf anzeigen &amp; leeren</div>
                                        <div className="checkbox-desc">Nutzer können den Gesprächsverlauf einsehen und löschen.</div>
                                    </div>
                                </label>
                                <label className="checkbox-item">
                                    <input type="checkbox" />
                                    <div>
                                        <div className="checkbox-label">Quellenangaben anzeigen</div>
                                        <div className="checkbox-desc">Zu jeder Antwort werden die verwendeten Quellen eingeblendet.</div>
                                    </div>
                                </label>
                            </div>
                        </div>
                    </div>

                    {/* Zugang */}
                    <div className={sectionClass("sec-login")}>
                        <button type="button" className="section-toggle" onClick={() => toggleSection("sec-login")}>
                            <div className="section-toggle-left">
                                <div className="section-icon">
                                    <SectionLoginIcon />
                                </div>
                                <span className="section-title">Zugang &amp; Login</span>
                            </div>
                            <ChevronDownIcon className="chevron" />
                        </button>
                        <div className="section-body">
                            <div className="form-group">
                                <label>Login erforderlich?</label>
                                <div className="toggle-option-group">
                                    <button
                                        type="button"
                                        className={"toggle-option" + (!loginRequired ? " active" : "")}
                                        onClick={() => setLoginRequired(false)}
                                    >
                                        Nein – öffentlich zugänglich
                                    </button>
                                    <button
                                        type="button"
                                        className={"toggle-option" + (loginRequired ? " active" : "")}
                                        onClick={() => setLoginRequired(true)}
                                    >
                                        Ja – Login erforderlich
                                    </button>
                                </div>
                            </div>
                            {loginRequired && (
                                <div className="form-group">
                                    <label htmlFor="vw-login-provider">Login-Methode</label>
                                    <div className="select-wrap" style={{ maxWidth: 360 }}>
                                        <select id="vw-login-provider" defaultValue="email">
                                            <option value="email">E-Mail &amp; Passwort</option>
                                            <option value="sso">SSO / SAML</option>
                                            <option value="oauth-google">Google OAuth</option>
                                            <option value="oauth-microsoft">Microsoft OAuth</option>
                                            <option value="magic-link">Magic Link (passwortlos)</option>
                                        </select>
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>
                </div>

                <div className="action-bar">
                    <button type="button" className="btn-save" onClick={handleSave}>
                        Speichern
                    </button>
                    <button type="button" className="btn-discard" onClick={handleDiscard}>
                        Änderungen verwerfen
                    </button>
                </div>
            </div>

            {/* TAB: Q&A */}
            <div className={"tab-panel" + (activeTab === "tab-qa" ? " active" : "")}>
                <div className="config-form">
                    <div className={sectionClass("sec-qa-behavior")}>
                        <button type="button" className="section-toggle" onClick={() => toggleSection("sec-qa-behavior")}>
                            <div className="section-toggle-left">
                                <div className="section-icon">
                                    <SectionQaBehaviorIcon />
                                </div>
                                <span className="section-title">Antwortverhalten</span>
                            </div>
                            <ChevronDownIcon className="chevron" />
                        </button>
                        <div className="section-body">
                            <div className="form-row">
                                <div className="form-group">
                                    <label htmlFor="vw-qa-confidence">Mindestkonfidenz für Antworten</label>
                                    <div className="select-wrap">
                                        <select id="vw-qa-confidence" defaultValue="medium">
                                            <option value="low">Niedrig – auch unsichere Antworten</option>
                                            <option value="medium">Mittel (empfohlen)</option>
                                            <option value="high">Hoch – nur bei hoher Sicherheit</option>
                                        </select>
                                    </div>
                                </div>
                                <div className="form-group">
                                    <label htmlFor="vw-qa-fallback">Fallback bei fehlender Antwort</label>
                                    <div className="select-wrap">
                                        <select id="vw-qa-fallback" defaultValue="apologize">
                                            <option value="apologize">Höfliche Entschuldigung</option>
                                            <option value="redirect">An Ansprechpartner verweisen</option>
                                            <option value="search">Weitersuche vorschlagen</option>
                                        </select>
                                    </div>
                                </div>
                            </div>
                            <div className="checkbox-group">
                                <label className="checkbox-item">
                                    <input type="checkbox" defaultChecked />
                                    <div>
                                        <div className="checkbox-label">Nachfragen erlauben</div>
                                        <div className="checkbox-desc">Der Bot kann Rückfragen stellen, wenn die Anfrage unklar ist.</div>
                                    </div>
                                </label>
                                <label className="checkbox-item">
                                    <input type="checkbox" defaultChecked />
                                    <div>
                                        <div className="checkbox-label">Verwandte Fragen vorschlagen</div>
                                        <div className="checkbox-desc">Nach jeder Antwort werden ähnliche Fragen als Schnellauswahl angezeigt.</div>
                                    </div>
                                </label>
                            </div>
                        </div>
                    </div>
                </div>
                <div className="action-bar">
                    <button type="button" className="btn-save" onClick={handleSave}>
                        Speichern
                    </button>
                    <button type="button" className="btn-discard" onClick={handleDiscard}>
                        Änderungen verwerfen
                    </button>
                </div>
            </div>

            {/* TAB: Tutor */}
            <div className={"tab-panel" + (activeTab === "tab-tutor" ? " active" : "")}>
                <div className="config-form">
                    <div className={sectionClass("sec-tutor-level")}>
                        <button type="button" className="section-toggle" onClick={() => toggleSection("sec-tutor-level")}>
                            <div className="section-toggle-left">
                                <div className="section-icon">
                                    <SectionTutorLevelIcon />
                                </div>
                                <span className="section-title">Niveau</span>
                            </div>
                            <ChevronDownIcon className="chevron" />
                        </button>
                        <div className="section-body">
                            <div className="form-row">
                                <div className="form-group">
                                    <label htmlFor="vw-tutor-level">Wissensniveau der Lernenden</label>
                                    <div className="select-wrap">
                                        <select id="vw-tutor-level" defaultValue="intermediate">
                                            <option value="beginner">Einsteiger – keine Vorkenntnisse</option>
                                            <option value="intermediate">Fortgeschrittene – Grundkenntnisse vorhanden</option>
                                            <option value="advanced">Experten – tiefes Fachwissen</option>
                                            <option value="adaptive">Adaptiv – passt sich automatisch an</option>
                                        </select>
                                    </div>
                                </div>
                                <div className="form-group">
                                    <label htmlFor="vw-tutor-pace">Lerntempo</label>
                                    <div className="select-wrap">
                                        <select id="vw-tutor-pace" defaultValue="medium">
                                            <option value="slow">Langsam &amp; schrittweise</option>
                                            <option value="medium">Moderat</option>
                                            <option value="fast">Schnell &amp; komprimiert</option>
                                            <option value="user">Nutzerkontrolliert</option>
                                        </select>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div className={sectionClass("sec-tutor-method")}>
                        <button type="button" className="section-toggle" onClick={() => toggleSection("sec-tutor-method")}>
                            <div className="section-toggle-left">
                                <div className="section-icon">
                                    <SectionTutorMethodIcon />
                                </div>
                                <span className="section-title">Lernmethode</span>
                            </div>
                            <ChevronDownIcon className="chevron" />
                        </button>
                        <div className="section-body">
                            <div className="form-group" style={{ maxWidth: 360 }}>
                                <label htmlFor="vw-tutor-method">Didaktischer Ansatz</label>
                                <div className="select-wrap">
                                    <select id="vw-tutor-method" defaultValue="explanation">
                                        <option value="explanation">Erklärend – Konzepte &amp; Beispiele</option>
                                        <option value="socratic">Sokratisch – durch Fragen führen</option>
                                        <option value="step-by-step">Schritt-für-Schritt-Anleitungen</option>
                                        <option value="mixed">Gemischt</option>
                                    </select>
                                </div>
                            </div>
                            <div className="checkbox-group">
                                <label className="checkbox-item">
                                    <input type="checkbox" defaultChecked />
                                    <div>
                                        <div className="checkbox-label">Beispiele verwenden</div>
                                        <div className="checkbox-desc">Der Bot illustriert Konzepte mit konkreten Beispielen.</div>
                                    </div>
                                </label>
                                <label className="checkbox-item">
                                    <input type="checkbox" defaultChecked />
                                    <div>
                                        <div className="checkbox-label">Zusammenfassung am Ende</div>
                                        <div className="checkbox-desc">Nach einer Einheit fasst der Bot das Gelernte kurz zusammen.</div>
                                    </div>
                                </label>
                                <label className="checkbox-item">
                                    <input type="checkbox" />
                                    <div>
                                        <div className="checkbox-label">Fortschrittsanzeige</div>
                                        <div className="checkbox-desc">Lernende sehen, wie weit sie im Thema fortgeschritten sind.</div>
                                    </div>
                                </label>
                            </div>
                        </div>
                    </div>
                </div>
                <div className="action-bar">
                    <button type="button" className="btn-save" onClick={handleSave}>
                        Speichern
                    </button>
                    <button type="button" className="btn-discard" onClick={handleDiscard}>
                        Änderungen verwerfen
                    </button>
                </div>
            </div>

            {/* TAB: Assessment */}
            <div className={"tab-panel" + (activeTab === "tab-assessment" ? " active" : "")}>
                <div className="config-form">
                    <div className={sectionClass("sec-assess-format")}>
                        <button type="button" className="section-toggle" onClick={() => toggleSection("sec-assess-format")}>
                            <div className="section-toggle-left">
                                <div className="section-icon">
                                    <SectionAssessFormatIcon />
                                </div>
                                <span className="section-title">Prüfungsformat</span>
                            </div>
                            <ChevronDownIcon className="chevron" />
                        </button>
                        <div className="section-body">
                            <div className="form-row">
                                <div className="form-group">
                                    <label htmlFor="vw-assess-type">Fragetyp</label>
                                    <div className="select-wrap">
                                        <select id="vw-assess-type" defaultValue="mc">
                                            <option value="mc">Multiple Choice</option>
                                            <option value="open">Offene Fragen</option>
                                            <option value="truefalse">Wahr / Falsch</option>
                                            <option value="mixed">Gemischt</option>
                                        </select>
                                    </div>
                                </div>
                                <div className="form-group">
                                    <label htmlFor="vw-assess-count">Anzahl Fragen pro Session</label>
                                    <div className="select-wrap">
                                        <select id="vw-assess-count" defaultValue="10">
                                            <option value="5">5 Fragen</option>
                                            <option value="10">10 Fragen</option>
                                            <option value="15">15 Fragen</option>
                                            <option value="20">20 Fragen</option>
                                            <option value="unlimited">Unbegrenzt</option>
                                        </select>
                                    </div>
                                </div>
                            </div>
                            <div className="form-row">
                                <div className="form-group">
                                    <label htmlFor="vw-assess-difficulty">Schwierigkeitsgrad</label>
                                    <div className="select-wrap">
                                        <select id="vw-assess-difficulty" defaultValue="medium">
                                            <option value="easy">Einfach</option>
                                            <option value="medium">Mittel</option>
                                            <option value="hard">Schwer</option>
                                            <option value="adaptive">Adaptiv</option>
                                        </select>
                                    </div>
                                </div>
                                <div className="form-group">
                                    <label htmlFor="vw-assess-feedback">Feedback nach Antwort</label>
                                    <div className="select-wrap">
                                        <select id="vw-assess-feedback" defaultValue="immediate">
                                            <option value="immediate">Sofort nach jeder Frage</option>
                                            <option value="end">Am Ende der Session</option>
                                            <option value="none">Kein Feedback</option>
                                        </select>
                                    </div>
                                </div>
                            </div>
                            <div className="checkbox-group">
                                <label className="checkbox-item">
                                    <input type="checkbox" defaultChecked />
                                    <div>
                                        <div className="checkbox-label">Ergebnis anzeigen</div>
                                        <div className="checkbox-desc">Am Ende der Prüfung wird das Gesamtergebnis als Punktzahl angezeigt.</div>
                                    </div>
                                </label>
                                <label className="checkbox-item">
                                    <input type="checkbox" />
                                    <div>
                                        <div className="checkbox-label">Wiederholung erlauben</div>
                                        <div className="checkbox-desc">Nutzende können die Prüfung erneut starten.</div>
                                    </div>
                                </label>
                            </div>
                        </div>
                    </div>
                </div>
                <div className="action-bar">
                    <button type="button" className="btn-save" onClick={handleSave}>
                        Speichern
                    </button>
                    <button type="button" className="btn-discard" onClick={handleDiscard}>
                        Änderungen verwerfen
                    </button>
                </div>
            </div>

            {toastNode}

            <Helmet>
                <title>Konfigurieren – nerilio</title>
            </Helmet>
        </div>
    );
}

export default ConfigurePage;
