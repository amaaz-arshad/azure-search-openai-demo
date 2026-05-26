import { useState } from "react";
import { Helmet } from "react-helmet-async";

import { CloseIcon, PlusIcon } from "../components/icons";
import { useToast } from "../components/Toast";

/*
 * Ported from D:\working student\snap\nerilio backend\views\customers.php
 *
 * Customer management with table + create/edit modal (wide) + delete confirm modal +
 * slide-in detail panel (with contact info, users list, chatbots list, inline new-bot form).
 * Empty shell — modals/panels open/close, fields are local state, no AJAX.
 */

export function CustomersPage() {
    const { showToast, toastNode } = useToast();

    const [searchQuery, setSearchQuery] = useState("");

    // Create / Edit modal
    const [isFormOpen, setFormOpen] = useState(false);
    const [editId, setEditId] = useState<number | null>(null);

    // Delete confirm modal
    const [deleteTarget, setDeleteTarget] = useState<{ company: string } | null>(null);

    // Detail panel
    const [isDetailOpen, setDetailOpen] = useState(false);
    const [isInlineBotFormOpen, setInlineBotFormOpen] = useState(false);

    const openCreate = () => {
        setEditId(null);
        setFormOpen(true);
    };
    const closeForm = () => setFormOpen(false);

    const closeDetail = () => setDetailOpen(false);
    const closeDelete = () => setDeleteTarget(null);

    return (
        <>
            <div className="page-header">
                <h1>Kunden</h1>
                <p>Alle registrierten Kundenunternehmen und ihre zugeordneten Bots.</p>
            </div>

            <div className="table-section">
                <div className="table-header">
                    <h2 className="table-title">Kundenübersicht</h2>
                    <button type="button" className="create-button" onClick={openCreate}>
                        <PlusIcon />
                        Neuen Kunden anlegen
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
                                <th>Unternehmen</th>
                                <th>Ansprechpartner</th>
                                <th>E-Mail</th>
                                <th>Status</th>
                                <th>Aktionen</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr>
                                <td colSpan={5} className="loading">
                                    Keine Kunden gefunden.
                                </td>
                            </tr>
                            {/* Demo row to illustrate styling — kept invisible by default;
                                uncomment when wiring real data:

                            <tr>
                                <td className="cell-company">Mustermann GmbH</td>
                                <td>Max Mustermann</td>
                                <td className="cell-muted">kontakt@firma.de</td>
                                <td><span className="status-badge active"><span className="status-dot" />Aktiv</span></td>
                                <td>
                                    <div className="actions">
                                        <button className="icon-button" title="Details" onClick={openDetail}><ViewIcon /></button>
                                        <button className="icon-button" title="Bearbeiten" onClick={() => openEdit(1)}><EditIcon /></button>
                                        <button className="icon-button delete" title="Löschen" onClick={() => openDelete("Mustermann GmbH")}><DeleteIcon /></button>
                                    </div>
                                </td>
                            </tr>
                            */}
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
                <div className="modal modal-wide">
                    <div className="modal-hd">
                        <h2>{editId ? "Kunden bearbeiten" : "Neuen Kunden anlegen"}</h2>
                        <button type="button" className="x-btn" onClick={closeForm}>
                            <CloseIcon />
                        </button>
                    </div>
                    <div className="form-grid">
                        <div className="full section-label">Kundendaten</div>
                        <div className="fg full">
                            <label htmlFor="vw-f-company">Firmenname *</label>
                            <input type="text" id="vw-f-company" placeholder="z. B. Mustermann GmbH" />
                        </div>
                        <div className="fg">
                            <label htmlFor="vw-f-first">Vorname Ansprechpartner *</label>
                            <input type="text" id="vw-f-first" placeholder="Vorname" />
                        </div>
                        <div className="fg">
                            <label htmlFor="vw-f-last">Nachname *</label>
                            <input type="text" id="vw-f-last" placeholder="Nachname" />
                        </div>
                        <div className="fg">
                            <label htmlFor="vw-f-email">E-Mail *</label>
                            <input type="email" id="vw-f-email" placeholder="kontakt@firma.de" />
                        </div>
                        <div className="fg">
                            <label htmlFor="vw-f-phone">Telefon</label>
                            <input type="tel" id="vw-f-phone" placeholder="+49 …" />
                        </div>
                        <div className="fg full">
                            <label htmlFor="vw-f-website">Website</label>
                            <input type="url" id="vw-f-website" placeholder="https://…" />
                        </div>
                        <div className="fg full">
                            <label htmlFor="vw-f-address">Adresse</label>
                            <input type="text" id="vw-f-address" placeholder="Straße, PLZ Ort" />
                        </div>
                        <div className="fg">
                            <label htmlFor="vw-f-status">Status</label>
                            <div className="sw">
                                <select id="vw-f-status" defaultValue="active">
                                    <option value="active">Aktiv</option>
                                    <option value="inactive">Inaktiv</option>
                                </select>
                            </div>
                        </div>
                        <div className="fg full">
                            <label htmlFor="vw-f-notes">Notizen</label>
                            <textarea id="vw-f-notes" placeholder="Interne Anmerkungen …" />
                        </div>

                        {/* Erster Admin-User (nur bei Neuanlage) */}
                        {!editId && (
                            <>
                                <div className="full section-label">Erster Admin-User</div>
                                <div className="fg">
                                    <label htmlFor="vw-f-ufirst">Vorname *</label>
                                    <input type="text" id="vw-f-ufirst" placeholder="Vorname" />
                                </div>
                                <div className="fg">
                                    <label htmlFor="vw-f-ulast">Nachname *</label>
                                    <input type="text" id="vw-f-ulast" placeholder="Nachname" />
                                </div>
                                <div className="fg">
                                    <label htmlFor="vw-f-uemail">E-Mail *</label>
                                    <input type="email" id="vw-f-uemail" placeholder="user@firma.de" />
                                </div>
                                <div className="fg">
                                    <label htmlFor="vw-f-upass">Passwort *</label>
                                    <input type="password" id="vw-f-upass" placeholder="Mindestens 8 Zeichen" />
                                </div>
                                <div className="fg">
                                    <label htmlFor="vw-f-uphone">Telefon</label>
                                    <input type="tel" id="vw-f-uphone" placeholder="+49 …" />
                                </div>
                            </>
                        )}
                    </div>
                    <div className="modal-ft">
                        <button
                            type="button"
                            className="btn-p"
                            onClick={() => {
                                closeForm();
                                showToast(editId ? "Änderungen gespeichert (Demo)" : "Kunde angelegt (Demo)");
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
                        <h2>Kunden löschen</h2>
                        <button type="button" className="x-btn" onClick={closeDelete}>
                            <CloseIcon />
                        </button>
                    </div>
                    <p style={{ fontSize: 15, lineHeight: 1.6, marginBottom: 10 }}>
                        {deleteTarget
                            ? `Möchten Sie den Kunden „${deleteTarget.company}" wirklich endgültig löschen?`
                            : ""}
                    </p>
                    <p style={{ fontSize: 13, fontWeight: 600, color: "#b00020" }}>
                        Achtung: Alle zugehörigen User und Chatbots werden ebenfalls gelöscht!
                    </p>
                    <div className="modal-ft">
                        <button
                            type="button"
                            className="btn-d"
                            onClick={() => {
                                closeDelete();
                                showToast("Kunde gelöscht (Demo)");
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

            {/* Detail Panel */}
            <div className={"dp-bg" + (isDetailOpen ? " open" : "")} onClick={closeDetail} />
            <div className={"dp" + (isDetailOpen ? " open" : "")}>
                <div className="dp-hd">
                    <div>
                        <div className="dp-company">Beispiel Unternehmen</div>
                        <div className="dp-meta">Aktiv</div>
                    </div>
                    <button type="button" className="x-btn" onClick={closeDetail}>
                        <CloseIcon />
                    </button>
                </div>
                <div>
                    <div className="dp-sec">
                        <div className="dp-sec-title">Kontaktdaten</div>
                        <div className="dp-row">
                            <span className="dp-lbl">Ansprechpartner</span>
                            <span className="dp-val">–</span>
                        </div>
                        <div className="dp-row">
                            <span className="dp-lbl">E-Mail</span>
                            <span className="dp-val">–</span>
                        </div>
                        <div className="dp-row">
                            <span className="dp-lbl">Telefon</span>
                            <span className="dp-val">–</span>
                        </div>
                        <div className="dp-row">
                            <span className="dp-lbl">Website</span>
                            <span className="dp-val">–</span>
                        </div>
                        <div className="dp-row">
                            <span className="dp-lbl">Adresse</span>
                            <span className="dp-val">–</span>
                        </div>
                    </div>

                    <div className="dp-sec">
                        <div className="dp-sec-title">
                            <span>Benutzer (0)</span>
                        </div>
                        <p style={{ fontSize: 14, color: "var(--muted)" }}>Keine Benutzer.</p>
                    </div>

                    <div className="dp-sec">
                        <div className="dp-sec-title">
                            <span>Chatbots (0)</span>
                            <button type="button" className="btn-link" onClick={() => setInlineBotFormOpen(prev => !prev)}>
                                + Neuer Chatbot
                            </button>
                        </div>
                        <div className={"inline-form" + (isInlineBotFormOpen ? " open" : "")}>
                            <input type="text" className="inline-input" placeholder="Name *" />
                            <div className="botname-wrap">
                                <span className="botname-prefix">chat.nerilio.ai/</span>
                                <input type="text" className="botname-input" placeholder="botname *" autoComplete="off" spellCheck={false} />
                            </div>
                            <div className="inline-actions">
                                <button
                                    type="button"
                                    className="btn-sm-p"
                                    onClick={() => {
                                        setInlineBotFormOpen(false);
                                        showToast("Chatbot angelegt (Demo)");
                                    }}
                                >
                                    Anlegen
                                </button>
                                <button type="button" className="btn-sm-c" onClick={() => setInlineBotFormOpen(false)}>
                                    Abbrechen
                                </button>
                            </div>
                        </div>
                        <p style={{ fontSize: 14, color: "var(--muted)", marginTop: 10 }}>Keine Chatbots.</p>
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
                        Bearbeiten
                    </button>
                    <button type="button" className="btn-c" onClick={closeDetail}>
                        Schließen
                    </button>
                </div>
            </div>

            {toastNode}

            <Helmet>
                <title>Kunden – nerilio</title>
            </Helmet>
        </>
    );
}

export default CustomersPage;
