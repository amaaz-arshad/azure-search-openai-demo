import { useState } from "react";
import { Helmet } from "react-helmet-async";

import { CloseIcon } from "../components/icons";
import { useToast } from "../components/Toast";

/*
 * Ported from D:\working student\snap\nerilio backend\views\dashboard.php
 *
 * Chatbot management table — empty shell. No data is loaded; the table renders
 * its header columns and an empty-state row. Search, sort, and rows-per-page
 * controls are interactive (track local state) but there's nothing to filter.
 * Create-modal and confirm-modal open/close but their submit handlers are stubs.
 */

type SortKey = "id" | "name" | "customer_name" | "url";
type SortDir = "asc" | "desc";

export function DashboardPage() {
    const { showToast, toastNode } = useToast();

    // Table state (wired but no data — matches empty-shell decision)
    const [searchQuery, setSearchQuery] = useState("");
    const [rowsPerPage, setRowsPerPage] = useState(12);
    const [sortKey, setSortKey] = useState<SortKey>("name");
    const [sortDir, setSortDir] = useState<SortDir>("asc");

    // Create-modal state
    const [isCreateOpen, setCreateOpen] = useState(false);
    const [cmCustomer, setCmCustomer] = useState("");
    const [cmName, setCmName] = useState("");
    const [cmBotname, setCmBotname] = useState("");

    // Confirm-modal state (not driven by data yet, but visually wired)
    const [confirmState, setConfirmState] = useState<{
        text: string;
        confirmLabel: string;
        warning?: string;
    } | null>(null);

    const handleSort = (key: SortKey) => {
        if (sortKey === key) {
            setSortDir(prev => (prev === "asc" ? "desc" : "asc"));
        } else {
            setSortKey(key);
            setSortDir("asc");
        }
    };

    const sortIndicator = (key: SortKey) => {
        if (sortKey !== key) return "↕";
        return sortDir === "asc" ? "↑" : "↓";
    };

    const openCreateModal = () => {
        setCmCustomer("");
        setCmName("");
        setCmBotname("");
        setCreateOpen(true);
    };

    const closeCreateModal = () => setCreateOpen(false);

    const handleCreateSave = () => {
        // Empty shell: would POST to /verwaltung/chatbots in the future.
        closeCreateModal();
        showToast("Chatbot angelegt (Demo)");
    };

    const closeConfirmModal = () => setConfirmState(null);

    return (
        <>
            <div className="page-header">
                <h1>Dashboard</h1>
                <p>Willkommen.</p>
            </div>

            <section className="table-section">
                <div className="table-header">
                    <h2 className="table-title">Alle Chatbots</h2>
                    <button type="button" className="create-button" onClick={openCreateModal}>
                        Chatbot anlegen
                    </button>
                </div>

                <div className="table-toolbar">
                    <input
                        type="search"
                        className="search-input"
                        placeholder="Suchen …"
                        aria-label="Chatbots suchen"
                        value={searchQuery}
                        onChange={event => setSearchQuery(event.target.value)}
                    />
                    <div className="toolbar-right">
                        <label htmlFor="vw-rows-per-page">Einträge pro Seite</label>
                        <select id="vw-rows-per-page" value={rowsPerPage} onChange={event => setRowsPerPage(Number(event.target.value))}>
                            <option value={12}>12</option>
                            <option value={24}>24</option>
                            <option value={50}>50</option>
                        </select>
                    </div>
                </div>

                <div className="table-wrap">
                    <table>
                        <thead>
                            <tr>
                                <th>
                                    <button type="button" className="sortable" onClick={() => handleSort("id")}>
                                        ID <span className="sort-indicator">{sortIndicator("id")}</span>
                                    </button>
                                </th>
                                <th>
                                    <button type="button" className="sortable" onClick={() => handleSort("name")}>
                                        Name <span className="sort-indicator">{sortIndicator("name")}</span>
                                    </button>
                                </th>
                                <th>
                                    <button type="button" className="sortable" onClick={() => handleSort("customer_name")}>
                                        Kunde <span className="sort-indicator">{sortIndicator("customer_name")}</span>
                                    </button>
                                </th>
                                <th>
                                    <button type="button" className="sortable" onClick={() => handleSort("url")}>
                                        URL <span className="sort-indicator">{sortIndicator("url")}</span>
                                    </button>
                                </th>
                                <th>Status</th>
                                <th>Aktionen</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr>
                                <td colSpan={6} className="loading">
                                    Keine Chatbots gefunden.
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
            </section>

            {/* Confirm Modal (delete / deactivate) */}
            <div className={"modal-overlay" + (confirmState ? " open" : "")} onClick={event => event.target === event.currentTarget && closeConfirmModal()}>
                <div className="modal" role="dialog" aria-modal="true">
                    <div className="modal-text">{confirmState?.text}</div>
                    {confirmState?.warning ? <div className="modal-warning">{confirmState.warning}</div> : null}
                    <div className="modal-actions">
                        <button
                            type="button"
                            className="modal-button danger"
                            onClick={() => {
                                closeConfirmModal();
                                showToast("Aktion bestätigt (Demo)");
                            }}
                        >
                            {confirmState?.confirmLabel ?? "Bestätigen"}
                        </button>
                        <button type="button" className="modal-button" onClick={closeConfirmModal}>
                            Abbrechen
                        </button>
                    </div>
                </div>
            </div>

            {/* Create Chatbot Modal */}
            <div className={"cm-overlay" + (isCreateOpen ? " open" : "")} onClick={event => event.target === event.currentTarget && closeCreateModal()}>
                <div className="cm" role="dialog" aria-modal="true" aria-labelledby="cm-title">
                    <div className="cm-hd">
                        <h2 id="cm-title">Neuen Chatbot anlegen</h2>
                        <button type="button" className="x-btn" onClick={closeCreateModal} aria-label="Schließen">
                            <CloseIcon />
                        </button>
                    </div>
                    <div className="cm-body">
                        <div className="fg">
                            <label htmlFor="cm-customer">Kunde *</label>
                            <div className="sw">
                                <select id="cm-customer" value={cmCustomer} onChange={event => setCmCustomer(event.target.value)}>
                                    <option value="">Kunde wählen …</option>
                                </select>
                            </div>
                        </div>
                        <div className="fg">
                            <label htmlFor="cm-name">Name *</label>
                            <input
                                type="text"
                                id="cm-name"
                                placeholder="z. B. Support-Bot"
                                value={cmName}
                                onChange={event => setCmName(event.target.value)}
                            />
                        </div>
                        <div className="fg">
                            <label htmlFor="cm-botname">Botname (URL) *</label>
                            <div className="botname-wrap">
                                <span className="botname-prefix">chat.nerilio.ai/</span>
                                <input
                                    type="text"
                                    className="botname-field"
                                    id="cm-botname"
                                    placeholder="botname"
                                    autoComplete="off"
                                    spellCheck={false}
                                    value={cmBotname}
                                    onChange={event => setCmBotname(event.target.value)}
                                />
                            </div>
                        </div>
                    </div>
                    <div className="cm-ft">
                        <button type="button" className="btn-p" onClick={handleCreateSave}>
                            Anlegen
                        </button>
                        <button type="button" className="btn-c" onClick={closeCreateModal}>
                            Abbrechen
                        </button>
                    </div>
                </div>
            </div>

            {toastNode}

            <Helmet>
                <title>Dashboard – nerilio</title>
            </Helmet>
        </>
    );
}

export default DashboardPage;
