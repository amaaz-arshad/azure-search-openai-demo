import { useEffect, useState } from "react";
import { Link, Outlet } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
    ChatAdd24Regular,
    History24Regular,
    Settings24Regular,
    PanelLeftContract24Regular,
    PanelLeftExpand24Regular,
    Navigation24Regular
} from "@fluentui/react-icons";

import { useLogin } from "../../authConfig";
import { LoginButton } from "../../../lemon/components/LoginButton";
import appLogo from "../../../../assets/applogo.svg";
import styles from "./Layout.module.css";

let globalClearChat: () => void = () => {};

export const setGlobalClearChat = (fn: () => void) => {
    globalClearChat = fn;
};

export interface InternalV2LayoutOutletContext {
    setRecentChatsAction: (action: { run: () => void } | null) => void;
    setDeveloperOptionsAction: (action: { run: () => void } | null) => void;
}

const Layout = () => {
    const { t } = useTranslation();
    const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
    const [mobileOpen, setMobileOpen] = useState(false);
    const [recentChatsAction, setRecentChatsAction] = useState<{ run: () => void } | null>(null);
    const [developerOptionsAction, setDeveloperOptionsAction] = useState<{ run: () => void } | null>(null);

    useEffect(() => {
        const onResize = () => {
            if (window.innerWidth > 768) {
                setMobileOpen(false);
            }
        };
        window.addEventListener("resize", onResize);
        return () => window.removeEventListener("resize", onResize);
    }, []);

    const handleNewChat = () => {
        globalClearChat();
        setMobileOpen(false);
    };

    const handleRecent = () => {
        recentChatsAction?.run();
        setMobileOpen(false);
    };

    const handleDevSettings = () => {
        developerOptionsAction?.run();
        setMobileOpen(false);
    };

    const sidebarClass = [styles.sidebar, sidebarCollapsed ? styles.sidebarCollapsed : "", mobileOpen ? styles.sidebarMobileOpen : ""]
        .filter(Boolean)
        .join(" ");

    return (
        <div className={styles.layout}>
            {mobileOpen && <div className={styles.mobileOverlay} onClick={() => setMobileOpen(false)} aria-hidden="true" />}

            <aside className={sidebarClass}>
                <div className={styles.sidebarHeader}>
                    <Link className={styles.brandLink} to="/internal-v2" onClick={() => setMobileOpen(false)}>
                        <div className={styles.brandBadge}>
                            <img src={appLogo} alt="" aria-hidden="true" />
                        </div>
                        <div className={styles.brandText}>
                            <div className={styles.brandName}>{t("headerTitle")}</div>
                            <div className={styles.brandTag}>v2 · preview</div>
                        </div>
                    </Link>

                    <button
                        className={styles.collapseButton}
                        type="button"
                        onClick={() => setSidebarCollapsed(v => !v)}
                        aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
                    >
                        {sidebarCollapsed ? <PanelLeftExpand24Regular /> : <PanelLeftContract24Regular />}
                    </button>
                </div>

                <div className={styles.sidebarContent}>
                    <button className={styles.newChatButton} type="button" onClick={handleNewChat}>
                        <ChatAdd24Regular />
                        <span className={styles.primaryLabel}>{t("newChat")}</span>
                    </button>

                    <div>
                        <div className={styles.sectionHeader}>Workspace</div>
                        <ul className={styles.menuList}>
                            <li>
                                <button className={styles.menuItem} type="button" onClick={handleRecent}>
                                    <History24Regular />
                                    <span className={styles.menuLabel}>{t("history.viewRecentChats")}</span>
                                </button>
                            </li>
                            <li>
                                <button className={styles.menuItem} type="button" onClick={handleDevSettings}>
                                    <Settings24Regular />
                                    <span className={styles.menuLabel}>{t("developerSettings")}</span>
                                </button>
                            </li>
                        </ul>
                    </div>

                    <div className={styles.spacer} />
                </div>

                <div className={styles.sidebarFooter}>
                    <div className={styles.accountRow}>
                        <div className={styles.avatar}>IB</div>
                        <div className={styles.accountInfo}>
                            <div className={styles.accountName}>Internal user</div>
                            <div className={styles.accountRole}>v2 workspace</div>
                        </div>
                    </div>
                </div>
            </aside>

            <div className={styles.mainContent}>
                <header className={styles.topBar} role="banner">
                    <div className={styles.topBarLeft}>
                        <button
                            className={styles.mobileMenuButton}
                            type="button"
                            onClick={() => setMobileOpen(v => !v)}
                            aria-label="Open menu"
                        >
                            <Navigation24Regular />
                        </button>
                        <span className={styles.topBarTitle}>{t("headerTitle")}</span>
                        <span className={styles.topBarStatus}>
                            <span className={styles.statusDot} aria-hidden="true" />
                            Online
                        </span>
                    </div>

                    <div className={styles.topBarRight}>
                        {useLogin && (
                            <div className={styles.loginButtonWrap}>
                                <LoginButton />
                            </div>
                        )}
                    </div>
                </header>

                <main className={styles.main} id="main-content">
                    <Outlet context={{ setRecentChatsAction, setDeveloperOptionsAction }} />
                </main>
            </div>
        </div>
    );
};

export default Layout;
