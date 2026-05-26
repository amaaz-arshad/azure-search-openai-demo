import { useState } from "react";
import { Helmet } from "react-helmet-async";

import { CloseIcon, PlusIcon, PlusTinyIcon, UploadCloudIcon } from "../components/icons";
import { useToast } from "../components/Toast";

/*
 * Ported from D:\working student\snap\nerilio backend\views\knowledge_bases.php
 *
 * Knowledge base management with table + create/edit modal + delete confirm + text entry modal +
 * slide-in detail panel (usage bars, dropzone, file list, text list, URL crawl section).
 * Empty shell — open/close state only, no AJAX, no file upload behaviour.
 */

export function KnowledgeBasesPage() {
    const { showToast, toastNode } = useToast();

    const [searchQuery, setSearchQuery] = useState("");

    const [isFormOpen, setFormOpen] = useState(false);
    const [editId, setEditId] = useState<number | null>(null);

    const [deleteTarget, setDeleteTarget] = useState<{ name: string } | null>(null);

    const [isTextOpen, setTextOpen] = useState(false);
    const [textEditMode, setTextEditMode] = useState(false);

    const [isDetailOpen, setDetailOpen] = useState(false);
    const [isUrlFormOpen, setUrlFormOpen] = useState(false);
    const [crawlDepth, setCrawlDepth] = useState("2");

    const openCreate = () => {
        setEditId(null);
        setFormOpen(true);
    };
    const closeForm = () => setFormOpen(false);

    const closeDelete = () => setDeleteTarget(null);

    const openNewText = () => {
        setTextEditMode(false);
        setTextOpen(true);
    };
    const closeText = () => setTextOpen(false);

    const closeDetail = () => setDetailOpen(false);

    return (
        <>
            <div className="page-header">
                <h1>Wissensdatenbanken</h1>
                <p>Dokumente und Dateien für die Chatbot-Wissensbasis.</p>
            </div>

            <div className="table-section">
                <div className="table-header">
                    <h2 className="table-title">Übersicht</h2>
                    <button type="button" className="create-button" onClick={openCreate}>
                        <PlusIcon />
                        Neue Wissensdatenbank
                    </button>
                </div>
                <div className="table-toolbar">
                    <input
                        type="search"
                        className="search-input"
                        placeholder="Suchen …"
                        value={searchQuery}
                        onChange={event => setSearchQuery(event.target.value)}
                    />
                </div>
                <div className="table-wrap">
                    <table>
                        <thead>
                            <tr>
                                <th>Name</th>
                                <th>Bot</th>
                                <th>Dateien</th>
                                <th>Größe</th>
                                <th>Aktionen</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr>
                                <td colSpan={5} className="loading">
                                    Keine Wissensdatenbanken gefunden.
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
                <div className="table-footer">
                    <div className="table-info">Zeige 0–0 von 0 Einträgen</div>
                    <div className="pagination">
                        <button type="button" className="page-button" disabled>
                            Zurück
                        </button>
                        <button type="button" className="page-button active">
                            1
                        </button>
                        <button type="button" className="page-button" disabled>
                            Weiter
                        </button>
                    </div>
                </div>
            </div>

            {/* Create / Edit Modal */}
            <div className={"overlay" + (isFormOpen ? " open" : "")} onClick={event => event.target === event.currentTarget && closeForm()}>
                <div className="modal">
                    <div className="modal-hd">
                        <h2>{editId ? "Wissensdatenbank bearbeiten" : "Neue Wissensdatenbank"}</h2>
                        <button type="button" className="x-btn" onClick={closeForm}>
                            <CloseIcon />
                        </button>
                    </div>
                    <div className="form-body">
                        <div className="fg">
                            <label htmlFor="vw-kb-name">Name *</label>
                            <input type="text" id="vw-kb-name" placeholder="z. B. Produkthandbücher" />
                        </div>
                        {editId ? (
                            <div className="fg">
                                <label>Zugewiesener Bot</label>
                                <input type="text" defaultValue="–" readOnly />
                                <span className="hint">Bot-Zuweisung kann nach dem Anlegen nicht geändert werden.</span>
                            </div>
                        ) : (
                            <div className="fg">
                                <label htmlFor="vw-kb-bot">Zugewiesener Bot *</label>
                                <div className="sw">
                                    <select id="vw-kb-bot" defaultValue="">
                                        <option value="">Bot wählen …</option>
                                    </select>
                                </div>
                            </div>
                        )}
                        <div className="fg-row">
                            <div className="fg">
                                <label htmlFor="vw-kb-max-files">Max. Dateien</label>
                                <input type="number" id="vw-kb-max-files" defaultValue={20} min={1} max={500} />
                            </div>
                            <div className="fg">
                                <label htmlFor="vw-kb-max-size">Max. Gesamtgröße (MB)</label>
                                <input type="number" id="vw-kb-max-size" defaultValue={100} min={1} max={10000} />
                            </div>
                        </div>
                    </div>
                    <div className="modal-ft">
                        <button
                            type="button"
                            className="btn-p"
                            onClick={() => {
                                closeForm();
                                showToast(editId ? "Änderungen gespeichert (Demo)" : "Wissensdatenbank angelegt (Demo)");
                            }}
                        >
                            {editId ? "Speichern" : "Anlegen"}
                        </button>
                        <button type="button" className="btn-c" onClick={closeForm}>
                            Abbrechen
                        </button>
                    </div>
                </div>
            </div>

            {/* Delete Confirm */}
            <div className={"overlay" + (deleteTarget ? " open" : "")} onClick={event => event.target === event.currentTarget && closeDelete()}>
                <div className="modal sm">
                    <div className="modal-hd">
                        <h2>Wissensdatenbank löschen</h2>
                        <button type="button" className="x-btn" onClick={closeDelete}>
                            <CloseIcon />
                        </button>
                    </div>
                    <p style={{ fontSize: 15, lineHeight: 1.6, marginBottom: 10 }}>
                        {deleteTarget ? `Möchten Sie die Wissensdatenbank „${deleteTarget.name}" wirklich löschen?` : ""}
                    </p>
                    <p style={{ fontSize: 13, fontWeight: 600, color: "#b00020" }}>Achtung: Alle enthaltenen Dateien werden unwiderruflich gelöscht!</p>
                    <div className="modal-ft">
                        <button
                            type="button"
                            className="btn-d"
                            onClick={() => {
                                closeDelete();
                                showToast("Wissensdatenbank gelöscht (Demo)");
                            }}
                        >
                            Endgültig löschen
                        </button>
                        <button type="button" className="btn-c" onClick={closeDelete}>
                            Abbrechen
                        </button>
                    </div>
                </div>
            </div>

            {/* Text Entry Modal */}
            <div className={"overlay" + (isTextOpen ? " open" : "")} onClick={event => event.target === event.currentTarget && closeText()}>
                <div className="modal">
                    <div className="modal-hd">
                        <h2>{textEditMode ? "Texteintrag bearbeiten" : "Neuer Texteintrag"}</h2>
                        <button type="button" className="x-btn" onClick={closeText}>
                            <CloseIcon />
                        </button>
                    </div>
                    <div className="form-body">
                        <div className="fg">
                            <label htmlFor="vw-t-title">
                                Titel <span style={{ fontWeight: 400, color: "var(--muted)" }}>(optional)</span>
                            </label>
                            <input type="text" id="vw-t-title" placeholder="z. B. Produktbeschreibung, FAQ …" />
                        </div>
                        <div className="fg">
                            <label htmlFor="vw-t-content">Inhalt *</label>
                            <textarea id="vw-t-content" rows={12} placeholder="Text hier eingeben …" style={{ minHeight: 220, fontSize: 14 }} />
                        </div>
                    </div>
                    <div className="modal-ft">
                        <button
                            type="button"
                            className="btn-p"
                            onClick={() => {
                                closeText();
                                showToast(textEditMode ? "Eintrag aktualisiert (Demo)" : "Eintrag gespeichert (Demo)");
                            }}
                        >
                            Speichern
                        </button>
                        <button type="button" className="btn-c" onClick={closeText}>
                            Abbrechen
                        </button>
                    </div>
                </div>
            </div>

            {/* Detail Panel */}
            <div className={"dp-bg" + (isDetailOpen ? " open" : "")} onClick={closeDetail} />
            <div className={"dp dp-kb" + (isDetailOpen ? " open" : "")}>
                <div className="dp-hd">
                    <div>
                        <div className="dp-title">Beispiel-Wissensdatenbank</div>
                    </div>
                    <button type="button" className="x-btn" onClick={closeDetail}>
                        <CloseIcon />
                    </button>
                </div>
                <div className="dp-sub">Bot: –</div>
                <div>
                    <div className="usage-section">
                        <div className="usage-row">
                            <div className="usage-row-hd">
                                <span className="usage-row-label">Dateien</span>
                                <span className="usage-row-val">0 / 20</span>
                            </div>
                            <div className="usage-track-lg">
                                <div className="usage-fill-lg" style={{ width: "0%" }} />
                            </div>
                        </div>
                        <div className="usage-row">
                            <div className="usage-row-hd">
                                <span className="usage-row-label">Speicher</span>
                                <span className="usage-row-val">0 B / 100 MB</span>
                            </div>
                            <div className="usage-track-lg">
                                <div className="usage-fill-lg" style={{ width: "0%" }} />
                            </div>
                        </div>
                    </div>

                    <div className="upload-section">
                        <div className="upload-section-title">Datei hochladen</div>
                        <div className="dropzone">
                            <input type="file" multiple />
                            <div className="dropzone-icon">
                                <UploadCloudIcon />
                            </div>
                            <div className="dropzone-text">Dateien hierher ziehen oder klicken</div>
                            <div className="dropzone-hint">PDF, Word, Excel, TXT, CSV u. a.</div>
                        </div>
                        <div className="upload-queue" />
                    </div>

                    <div className="dp-section">
                        <div className="dp-section-hd">
                            <div className="dp-section-title">Dateien (0)</div>
                        </div>
                        <div className="file-list">
                            <div className="empty-state">Noch keine Dateien hochgeladen.</div>
                        </div>
                    </div>

                    <div className="dp-section">
                        <div className="dp-section-hd">
                            <div className="dp-section-title">Texteingaben (0)</div>
                            <button type="button" className="add-text-btn" onClick={openNewText}>
                                <PlusTinyIcon />
                                Neuer Eintrag
                            </button>
                        </div>
                        <div className="text-list">
                            <div className="empty-state">Noch keine Texteingaben vorhanden.</div>
                        </div>
                        {/* Example item kept hidden; sample structure for when wiring data:

                        <div className="text-list">
                            <div className="text-item">
                                <div className="text-icon"><TextLinesIcon /></div>
                                <div className="text-info">
                                    <div className="text-title">FAQ</div>
                                    <div className="text-preview">Lorem ipsum …</div>
                                </div>
                                <div className="text-actions">
                                    <button className="text-btn" onClick={() => { setTextEditMode(true); setTextOpen(true); }}><EditSmallIcon /></button>
                                    <button className="text-btn del" onClick={() => showToast("Eintrag gelöscht (Demo)")}><DeleteSmallIcon /></button>
                                </div>
                            </div>
                        </div>
                        */}
                    </div>

                    <div className="dp-section">
                        <div className="dp-section-hd">
                            <div className="dp-section-title">Webseiten (0/3)</div>
                            <button type="button" className="add-text-btn" onClick={() => setUrlFormOpen(true)}>
                                <PlusTinyIcon />
                                URL hinzufügen
                            </button>
                        </div>
                        <div className="url-form-wrap" style={{ display: isUrlFormOpen ? "" : "none" }}>
                            <label className="perm-label">
                                <input type="checkbox" />
                                <span>Ich bestätige, dass ich die Erlaubnis habe, den Inhalt dieser Website zu crawlen.</span>
                            </label>
                            <div className="fg" style={{ marginTop: 12 }}>
                                <label htmlFor="vw-url-input">URL *</label>
                                <input type="url" id="vw-url-input" placeholder="https://beispiel.de/" />
                            </div>
                            <div className="fg" style={{ marginTop: 10 }}>
                                <label htmlFor="vw-depth-sel">Linktiefe</label>
                                <div className="sw">
                                    <select id="vw-depth-sel" value={crawlDepth} onChange={event => setCrawlDepth(event.target.value)}>
                                        <option value="0">0 – Nur diese Seite</option>
                                        <option value="1">1 – Direkt verlinkte Seiten</option>
                                        <option value="2">2 – Empfohlen</option>
                                        <option value="3">3 – Tiefes Crawling</option>
                                    </select>
                                </div>
                            </div>
                            {crawlDepth === "3" && (
                                <div className="depth-warn">
                                    ⚠ Achtung: Linktiefe 3 kann bei großen Webseiten mehrere hundert oder tausende Seiten erfassen und die Verarbeitung deutlich verlängern. Maximales Limit: 500 Seiten.
                                </div>
                            )}
                            <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
                                <button
                                    type="button"
                                    className="add-text-btn"
                                    onClick={() => {
                                        setUrlFormOpen(false);
                                        showToast("Crawl gestartet (Demo)");
                                    }}
                                >
                                    Crawlen starten
                                </button>
                                <button type="button" className="btn-sm-cancel" onClick={() => setUrlFormOpen(false)}>
                                    Abbrechen
                                </button>
                            </div>
                        </div>
                        <div className="url-list">
                            <div className="empty-state" style={{ padding: "16px 0" }}>
                                Noch keine URLs eingetragen.
                            </div>
                        </div>
                        {/* Example URL item kept hidden as a template:

                        <div className="url-item">
                            <div className="url-item-hd">
                                <div className="url-text">https://example.com/</div>
                                <div className="text-actions">
                                    <button className="text-btn"><PlayTriangleSmallIcon /></button>
                                    <button className="text-btn del"><DeleteSmallIcon /></button>
                                </div>
                            </div>
                            <div className="url-depth-row">Tiefe 2 – Empfohlen</div>
                            <div className="job-row">
                                <span className="job-badge done">fertig</span>
                                <span className="job-counter">12 Seiten · 2026-05-26</span>
                            </div>
                        </div>
                        */}
                    </div>
                </div>
                <div className="dp-ft">
                    <button
                        type="button"
                        className="btn-p"
                        onClick={() => {
                            closeDetail();
                            setEditId(null);
                            setFormOpen(true);
                        }}
                    >
                        Einstellungen
                    </button>
                    <button type="button" className="btn-c" onClick={closeDetail}>
                        Schließen
                    </button>
                </div>
            </div>

            {toastNode}

            <Helmet>
                <title>Wissensdatenbanken – nerilio</title>
            </Helmet>
        </>
    );
}

export default KnowledgeBasesPage;
