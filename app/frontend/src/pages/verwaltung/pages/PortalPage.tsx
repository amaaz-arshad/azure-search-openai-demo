import { useState } from "react";
import { Helmet } from "react-helmet-async";

import { CloseIcon } from "../components/icons";
import { useToast } from "../components/Toast";
import "../verwaltung.css";

/*
 * Ported from D:\working student\snap\nerilio backend\views\portal.php
 *
 * Standalone customer-user surface (no sidebar, no admin gate).
 * Renders the top header + bot grid empty state + profile-edit modal.
 *
 * Lives outside VerwaltungLayout because the source has no sidebar here
 * and a different audience (assigned customer-users, not admins).
 */

export function PortalPage() {
    const { showToast, toastNode } = useToast();
    const [isProfileOpen, setProfileOpen] = useState(false);

    const closeProfile = () => setProfileOpen(false);

    return (
        <div className="verwaltung-root">
            <Helmet>
                <title>Meine Chatbots – nerilio</title>
            </Helmet>

            <header className="portal-header">
                <div className="portal-brand">nerilio</div>
                <div className="header-right">
                    <span className="user-label">Benutzer</span>
                    <button type="button" className="btn-profile" onClick={() => setProfileOpen(true)}>
                        Profil bearbeiten
                    </button>
                    <a href="/verwaltung" className="logout-link">
                        Abmelden
                    </a>
                </div>
            </header>

            <main className="portal-main">
                <h1 className="portal-heading">Meine Chatbots</h1>
                <p className="portal-sub">Klicke auf „Öffnen" um einen Bot zu starten.</p>
                <div className="bot-grid">
                    <div className="empty-state">Dir sind noch keine Chatbots zugewiesen.</div>
                    {/* Example bot card kept hidden as a template for when wiring real data:

                    <div className="bot-card">
                        <div className="bot-card-icon"><RobotIcon /></div>
                        <div>
                            <div className="bot-card-name">Beispiel-Bot</div>
                            <div className="bot-card-url">https://chat.nerilio.ai/beispiel</div>
                        </div>
                        <div className="bot-card-desc">Kurzbeschreibung des Bots …</div>
                        <a href="https://chat.nerilio.ai/beispiel" target="_blank" rel="noopener" className="btn-open">
                            Öffnen <OpenExternalIcon />
                        </a>
                    </div>
                    */}
                </div>
            </main>

            {/* Profil-Modal */}
            <div className={"overlay" + (isProfileOpen ? " open" : "")} onClick={event => event.target === event.currentTarget && closeProfile()}>
                <div className="modal">
                    <div className="modal-hd">
                        <h2>Profil bearbeiten</h2>
                        <button type="button" className="x-btn" onClick={closeProfile}>
                            <CloseIcon />
                        </button>
                    </div>
                    <div className="section-label">Persönliche Daten</div>
                    <div className="fg">
                        <label htmlFor="vw-p-first">Vorname</label>
                        <input type="text" id="vw-p-first" placeholder="Vorname" />
                    </div>
                    <div className="fg">
                        <label htmlFor="vw-p-last">Nachname</label>
                        <input type="text" id="vw-p-last" placeholder="Nachname" />
                    </div>
                    <div className="fg">
                        <label htmlFor="vw-p-email">E-Mail</label>
                        <input type="email" id="vw-p-email" placeholder="E-Mail-Adresse" />
                    </div>
                    <div className="fg">
                        <label htmlFor="vw-p-phone">Telefon</label>
                        <input type="tel" id="vw-p-phone" placeholder="+49 …" />
                    </div>
                    <div className="section-label">Passwort ändern</div>
                    <div className="fg">
                        <label htmlFor="vw-p-pw">Neues Passwort</label>
                        <input type="password" id="vw-p-pw" placeholder="Leer lassen, um beizubehalten" />
                        <span className="hint">Mindestens 8 Zeichen, wenn ausgefüllt</span>
                    </div>
                    <div className="modal-ft">
                        <button
                            type="button"
                            className="btn-p"
                            onClick={() => {
                                closeProfile();
                                showToast("Profil gespeichert (Demo)");
                            }}
                        >
                            Speichern
                        </button>
                        <button type="button" className="btn-c" onClick={closeProfile}>
                            Abbrechen
                        </button>
                    </div>
                </div>
            </div>

            {toastNode}
        </div>
    );
}

export default PortalPage;
