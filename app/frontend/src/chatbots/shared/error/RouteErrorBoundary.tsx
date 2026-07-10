import type { CSSProperties } from "react";
import { useRouteError } from "react-router-dom";

// Friendly full-page fallback for any error that bubbles to the router.
//
// Wired as the router's top-level `errorElement` (see index.tsx). React Router renders this IN PLACE
// of the matched route, so the per-route providers (the bot's I18nextProvider, ChatbotThemeRoot) are
// NOT in scope here — this component must be fully self-contained: no useTranslation, no theme tokens,
// only inline styles. Its job is purely to stop a single stray render/commit error (a browser
// extension tampering with the page, a rare unmount race, or a future bug) from white-screening the
// whole SPA with React Router's raw developer error page. See CHANGES.md 2026-07-09.

const COPY: Record<"de" | "en" | "nl", { title: string; body: string; reload: string; home: string }> = {
    de: {
        title: "Es ist ein Fehler aufgetreten",
        body: "Beim Anzeigen dieser Seite ist ein unerwarteter Fehler aufgetreten. Bitte lade die Seite neu. Sollte das Problem bestehen bleiben, versuche es in einem privaten Fenster (ohne Browser-Erweiterungen).",
        reload: "Neu laden",
        home: "Zur Startseite"
    },
    en: {
        title: "Something went wrong",
        body: "An unexpected error occurred while showing this page. Please reload. If it keeps happening, try a private/incognito window (with browser extensions disabled).",
        reload: "Reload",
        home: "Go to start page"
    },
    nl: {
        title: "Er is iets misgegaan",
        body: "Er is een onverwachte fout opgetreden bij het tonen van deze pagina. Laad de pagina opnieuw. Blijft het gebeuren, probeer dan een incognitovenster (zonder browserextensies).",
        reload: "Opnieuw laden",
        home: "Naar de startpagina"
    }
};

function resolveLanguage(): "de" | "en" | "nl" {
    const raw =
        (typeof document !== "undefined" ? document.documentElement.getAttribute("lang") : "") ||
        (typeof navigator !== "undefined" ? navigator.language : "") ||
        "de";
    const normalized = raw.toLowerCase();
    if (normalized.startsWith("nl")) {
        return "nl";
    }
    if (normalized.startsWith("en")) {
        return "en";
    }
    return "de";
}

export function RouteErrorBoundary() {
    const error = useRouteError();
    // Surface the underlying error to the console for support/telemetry without exposing internals in
    // the UI (the visible card stays user-friendly).
    // eslint-disable-next-line no-console
    console.error("Route error boundary caught:", error);

    const copy = COPY[resolveLanguage()];

    return (
        <div style={pageStyle} role="alert" data-testid="route-error-boundary">
            <div style={cardStyle}>
                <div aria-hidden="true" style={iconStyle}>
                    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <circle cx="12" cy="12" r="10" />
                        <line x1="12" y1="8" x2="12" y2="13" />
                        <line x1="12" y1="16.5" x2="12" y2="16.5" />
                    </svg>
                </div>
                <h1 style={titleStyle}>{copy.title}</h1>
                <p style={bodyStyle}>{copy.body}</p>
                <div style={actionsStyle}>
                    <button type="button" style={primaryButtonStyle} onClick={() => window.location.reload()}>
                        {copy.reload}
                    </button>
                    <a href="/" style={secondaryButtonStyle}>
                        {copy.home}
                    </a>
                </div>
            </div>
        </div>
    );
}

const pageStyle: CSSProperties = {
    minHeight: "100vh",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: "24px",
    background: "#f7f7fb",
    fontFamily: "'Segoe UI', system-ui, -apple-system, sans-serif",
    color: "#20222b"
};

const cardStyle: CSSProperties = {
    maxWidth: "440px",
    width: "100%",
    background: "#ffffff",
    borderRadius: "16px",
    padding: "36px 32px",
    textAlign: "center",
    boxShadow: "0 10px 40px rgba(20, 22, 43, 0.12)"
};

const iconStyle: CSSProperties = {
    width: "56px",
    height: "56px",
    margin: "0 auto 18px",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    borderRadius: "50%",
    background: "#fdecef",
    color: "#c62b47"
};

const titleStyle: CSSProperties = { fontSize: "20px", fontWeight: 600, margin: "0 0 10px" };

const bodyStyle: CSSProperties = { fontSize: "14.5px", lineHeight: 1.6, margin: "0 0 24px", color: "#4a4d5b" };

const actionsStyle: CSSProperties = { display: "flex", gap: "12px", justifyContent: "center", flexWrap: "wrap" };

const primaryButtonStyle: CSSProperties = {
    appearance: "none",
    border: "none",
    cursor: "pointer",
    borderRadius: "999px",
    padding: "10px 22px",
    fontSize: "14px",
    fontWeight: 600,
    color: "#ffffff",
    background: "#4b5563"
};

const secondaryButtonStyle: CSSProperties = {
    borderRadius: "999px",
    padding: "10px 22px",
    fontSize: "14px",
    fontWeight: 600,
    textDecoration: "none",
    color: "#4b5563",
    background: "#eceef3",
    display: "inline-flex",
    alignItems: "center"
};

export default RouteErrorBoundary;
