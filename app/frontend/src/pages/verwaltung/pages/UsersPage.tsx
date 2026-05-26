import { useState } from "react";
import { Helmet } from "react-helmet-async";

import { CloseIcon, PlusIcon } from "../components/icons";
import { useToast } from "../components/Toast";

/*
 * Ported from D:\working student\snap\nerilio backend\views\users.php
 *
 * User management with table + role/status/customer filters + create/edit modal +
 * delete confirm + slide-in detail panel (with bot assignments checklist).
 * Empty shell — filter dropdowns track local state, modals/panels open/close, no AJAX.
 */

type RoleFilter = "" | "admin" | "customer_admin" | "customer_user";
type StatusFilter = "" | "active" | "inactive";

export function UsersPage() {
    const { showToast, toastNode } = useToast();

    const [searchQuery, setSearchQuery] = useState("");
    const [customerFilter, setCustomerFilter] = useState("");
    const [roleFilter, setRoleFilter] = useState<RoleFilter>("");
    const [statusFilter, setStatusFilter] = useState<StatusFilter>("");

    const [isFormOpen, setFormOpen] = useState(false);
    const [editId, setEditId] = useState<number | null>(null);
    const [formRole, setFormRole] = useState<"admin" | "customer_admin" | "customer_user">("customer_user");

    const [deleteTarget, setDeleteTarget] = useState<{ name: string } | null>(null);

    const [isDetailOpen, setDetailOpen] = useState(false);

    const openCreate = () => {
        setEditId(null);
        setFormRole("customer_user");
        setFormOpen(true);
    };
    const closeForm = () => setFormOpen(false);
    const closeDetail = () => setDetailOpen(false);
    const closeDelete = () => setDeleteTarget(null);

    const showCustomerSelect = formRole !== "admin";
    const showBotAssignments = formRole === "customer_user";

    return (
        <>
            <div className="page-header">
                <h1>Benutzer</h1>
                <p>Alle Benutzerkonten mit Rollen und Bot-Zuweisungen.</p>
            </div>

            <div className="table-section">
                <div className="table-header">
                    <h2 className="table-title">Benutzerübersicht</h2>
                    <button type="button" className="create-button" onClick={openCreate}>
                        <PlusIcon />
                        Neuen Benutzer anlegen
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
                    <div className="filter-group">
                        <span className="filter-label">Kunde:</span>
                        <select className="filter-select" value={customerFilter} onChange={event => setCustomerFilter(event.target.value)}>
                            <option value="">Alle</option>
                        </select>
                        <span className="filter-label">Rolle:</span>
                        <select
                            className="filter-select"
                            value={roleFilter}
                            onChange={event => setRoleFilter(event.target.value as RoleFilter)}
                        >
                            <option value="">Alle</option>
                            <option value="admin">Admin</option>
                            <option value="customer_admin">Kunden-Admin</option>
                            <option value="customer_user">Benutzer</option>
                        </select>
                        <span className="filter-label">Status:</span>
                        <select
                            className="filter-select"
                            value={statusFilter}
                            onChange={event => setStatusFilter(event.target.value as StatusFilter)}
                        >
                            <option value="">Alle</option>
                            <option value="active">Aktiv</option>
                            <option value="inactive">Inaktiv</option>
                        </select>
                    </div>
                </div>
                <div className="table-wrap">
                    <table>
                        <thead>
                            <tr>
                                <th>Name</th>
                                <th>E-Mail</th>
                                <th>Rolle</th>
                                <th>Kunde</th>
                                <th>Status</th>
                                <th>Letzter Login</th>
                                <th>Aktionen</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr>
                                <td colSpan={7} className="loading">
                                    Keine Benutzer gefunden.
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
                        <h2>{editId ? "Benutzer bearbeiten" : "Neuen Benutzer anlegen"}</h2>
                        <button type="button" className="x-btn" onClick={closeForm}>
                            <CloseIcon />
                        </button>
                    </div>
                    <div className="form-grid">
                        <div className="fg">
                            <label htmlFor="vw-u-first">Vorname *</label>
                            <input type="text" id="vw-u-first" placeholder="Vorname" />
                        </div>
                        <div className="fg">
                            <label htmlFor="vw-u-last">Nachname *</label>
                            <input type="text" id="vw-u-last" placeholder="Nachname" />
                        </div>
                        <div className="fg full">
                            <label htmlFor="vw-u-email">E-Mail *</label>
                            <input type="email" id="vw-u-email" placeholder="benutzer@firma.de" />
                        </div>
                        <div className="fg">
                            <label htmlFor="vw-u-phone">Telefon</label>
                            <input type="tel" id="vw-u-phone" placeholder="+49 …" />
                        </div>
                        <div className="fg">
                            <label htmlFor="vw-u-role">Rolle *</label>
                            <div className="sw">
                                <select
                                    id="vw-u-role"
                                    value={formRole}
                                    onChange={event => setFormRole(event.target.value as "admin" | "customer_admin" | "customer_user")}
                                >
                                    <option value="admin">Admin</option>
                                    <option value="customer_admin">Kunden-Admin</option>
                                    <option value="customer_user">Benutzer</option>
                                </select>
                            </div>
                        </div>
                        {showCustomerSelect && (
                            <div className="fg full">
                                <label htmlFor="vw-u-customer">Zugehöriger Kunde *</label>
                                <div className="sw">
                                    <select id="vw-u-customer" defaultValue="">
                                        <option value="">Bitte wählen …</option>
                                    </select>
                                </div>
                            </div>
                        )}
                        {showBotAssignments && (
                            <div className="fg full">
                                <label>Chatbot-Zugang</label>
                                <div className="bot-assign-list" style={{ marginTop: 4 }} />
                                <p className="hint">Wähle einen Kunden, um zugehörige Chatbots zu sehen.</p>
                            </div>
                        )}
                        <div className="fg">
                            <label htmlFor="vw-u-status">Status</label>
                            <div className="sw">
                                <select id="vw-u-status" defaultValue="active">
                                    <option value="active">Aktiv</option>
                                    <option value="inactive">Inaktiv</option>
                                </select>
                            </div>
                        </div>
                        <div className="fg full">
                            <label htmlFor="vw-u-pw">Passwort *</label>
                            <input type="password" id="vw-u-pw" placeholder="Mindestens 8 Zeichen" />
                            <span className="hint">{editId ? "Leer lassen um Passwort beizubehalten" : ""}</span>
                        </div>
                    </div>
                    <div className="modal-ft">
                        <button
                            type="button"
                            className="btn-p"
                            onClick={() => {
                                closeForm();
                                showToast(editId ? "Änderungen gespeichert (Demo)" : "Benutzer angelegt (Demo)");
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
                        <h2>Benutzer löschen</h2>
                        <button type="button" className="x-btn" onClick={closeDelete}>
                            <CloseIcon />
                        </button>
                    </div>
                    <p style={{ fontSize: 15, lineHeight: 1.6, marginBottom: 10 }}>
                        {deleteTarget ? `Möchten Sie den Benutzer „${deleteTarget.name}" wirklich löschen?` : ""}
                    </p>
                    <p style={{ fontSize: 13, fontWeight: 600, color: "#b00020" }}>Achtung: Dieser Vorgang kann nicht rückgängig gemacht werden!</p>
                    <div className="modal-ft">
                        <button
                            type="button"
                            className="btn-d"
                            onClick={() => {
                                closeDelete();
                                showToast("Benutzer gelöscht (Demo)");
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
                        <div className="dp-name">Beispiel Benutzer</div>
                        <div className="dp-meta-row">
                            <span className="role-badge customer_user">Benutzer</span>
                            <span style={{ color: "var(--muted)", fontSize: 13 }}>user@example.com</span>
                        </div>
                    </div>
                    <button type="button" className="x-btn" onClick={closeDetail}>
                        <CloseIcon />
                    </button>
                </div>
                <div>
                    <div className="dp-sec">
                        <div className="dp-sec-title">Profil</div>
                        <div className="dp-row">
                            <span className="dp-lbl">E-Mail</span>
                            <span className="dp-val">–</span>
                        </div>
                        <div className="dp-row">
                            <span className="dp-lbl">Telefon</span>
                            <span className="dp-val">–</span>
                        </div>
                        <div className="dp-row">
                            <span className="dp-lbl">Kunde</span>
                            <span className="dp-val">–</span>
                        </div>
                        <div className="dp-row">
                            <span className="dp-lbl">Status</span>
                            <span className="dp-val">
                                <span className="status-badge inactive">
                                    <span className="status-dot" />
                                    Inaktiv
                                </span>
                            </span>
                        </div>
                        <div className="dp-row">
                            <span className="dp-lbl">Letzter Login</span>
                            <span className="dp-val">–</span>
                        </div>
                    </div>

                    <div className="dp-sec">
                        <div className="dp-sec-title">Bot-Zuweisungen</div>
                        <p style={{ fontSize: 14, color: "var(--muted)" }}>Keine Chatbots für diesen Kunden.</p>
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
                <title>Benutzer – nerilio</title>
            </Helmet>
        </>
    );
}

export default UsersPage;
