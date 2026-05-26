import { NavLink, useLocation } from "react-router-dom";

/*
 * Ported from D:\working student\snap\nerilio backend\nav.php
 * Renders the verwaltung sidebar with brand, nav items, and bottom user/logout block.
 */

type SidebarProps = {
    userName?: string;
    onLogout?: () => void;
};

const navItemClass = ({ isActive }: { isActive: boolean }) => "nav-item" + (isActive ? " active" : "");

export function Sidebar({ userName, onLogout }: SidebarProps) {
    const location = useLocation();

    // The `configure` route should keep `Chatbots` highlighted (matches nav.php behavior where
    // both /dashboard and /configure?id=X share the `dashboard` currentPage flag).
    const dashboardActive =
        location.pathname.startsWith("/verwaltung/dashboard") || location.pathname.startsWith("/verwaltung/configure");

    return (
        <aside className="sidebar">
            <div className="sidebar-top">
                <div className="brand-title">nerilio</div>
                <div className="brand-subtitle">Dashboard</div>
            </div>

            <nav className="nav">
                <NavLink to="/verwaltung/dashboard" className={"nav-item" + (dashboardActive ? " active" : "")}>
                    Chatbots
                </NavLink>

                <NavLink to="/verwaltung/knowledge-bases" className={navItemClass}>
                    Wissensdatenbanken
                </NavLink>

                <div className="nav-spacer" />

                <div className="nav-section-title">Verwaltung</div>

                <NavLink to="/verwaltung/customers" className={navItemClass}>
                    Kunden
                </NavLink>

                <NavLink to="/verwaltung/users" className={navItemClass}>
                    Benutzer
                </NavLink>
            </nav>

            <div className="sidebar-bottom">
                <div className="user-name">{userName ?? ""}</div>
                <button type="button" className="logout-link" onClick={onLogout}>
                    Logout
                </button>
            </div>
        </aside>
    );
}
