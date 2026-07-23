import { useEffect, useRef, useState, type PropsWithChildren } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { IconButton } from "@fluentui/react";
import { ChatAdd24Regular, History24Regular } from "@fluentui/react-icons";

// Reuse lemon's chrome read-only: same auth gate, same login button, same header CSS. The only
// difference vs lemon's Layout is that identity (logo, title, home link) comes from the runtime
// BotConfig, and children are rendered directly (no router Outlet, since the generic route is a
// single element rather than a nested route).
import { useLogin } from "../../../lemon/authConfig";
import { LoginButton } from "../../../lemon/components/LoginButton";
import styles from "../../../lemon/pages/layout/Layout.module.css";
// Fallback header mark for a provisioned bot that ships no `design.logo`: the shared nerilio robot
// mascot (also used by the 404 NoPage), NOT the generic Azure "stars" app mark (applogo.svg).
import fallbackLogo from "../../../shared/noPage/nerilioRobot.webp";
import { useBotConfig } from "../../botConfigContext";

let globalClearChat: () => void = () => {};

export const setGlobalClearChat = (fn: () => void) => {
    globalClearChat = fn;
};

let globalOpenRecentChats: () => void = () => {};

export const setGlobalOpenRecentChats = (fn: () => void) => {
    globalOpenRecentChats = fn;
};

const Layout = ({ children }: PropsWithChildren) => {
    const { t } = useTranslation();
    const botConfig = useBotConfig();
    const historyEnabled = botConfig.features?.history !== false;
    const dropdownRef = useRef<HTMLDivElement | null>(null);
    const [dropdownOpen, setDropdownOpen] = useState(false);

    useEffect(() => {
        if (!dropdownOpen) {
            return;
        }

        const handleClickOutside = (event: MouseEvent) => {
            if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
                setDropdownOpen(false);
            }
        };

        document.addEventListener("mousedown", handleClickOutside);
        return () => document.removeEventListener("mousedown", handleClickOutside);
    }, [dropdownOpen]);

    const handleStartNewChat = () => {
        setDropdownOpen(false);
        globalClearChat();
    };

    const handleOpenRecentChats = () => {
        setDropdownOpen(false);
        globalOpenRecentChats();
    };

    return (
        <div className={styles.layout}>
            <header className={styles.header} role="banner">
                <div className={styles.headerContainer}>
                    <Link className={styles.logoContainer} to={`/${botConfig.botName}`}>
                        <div className={styles.logoCircle}>
                            {/* Provisioned header logo (base64 data URI from `design.logo`); falls back to
                                the shared nerilio robot mascot when the bot has none. */}
                            <img alt="Logo" src={botConfig.logo || fallbackLogo} />
                        </div>
                    </Link>

                    <div className={styles.navbarTitle}>{t("headerTitle")}</div>

                    <div className={styles.rightSection}>
                        {useLogin && <LoginButton />}
                        <div className={styles.dropdown} ref={dropdownRef}>
                            <IconButton
                                ariaLabel={t("labels.openMenu")}
                                className={styles.menuButton}
                                iconProps={{ iconName: "More", styles: { root: { fontSize: "25px" } } }}
                                onClick={() => setDropdownOpen(open => !open)}
                            />
                            {dropdownOpen && (
                                <ul className={styles.dropdownMenu}>
                                    <li>
                                        <button className={styles.dropdownItem} onClick={handleStartNewChat}>
                                            <ChatAdd24Regular />
                                            <span>{t("newChat")}</span>
                                        </button>
                                    </li>
                                    {historyEnabled && (
                                        <li>
                                            <button className={styles.dropdownItem} onClick={handleOpenRecentChats}>
                                                <History24Regular />
                                                <span>{t("history.viewRecentChats")}</span>
                                            </button>
                                        </li>
                                    )}
                                </ul>
                            )}
                        </div>
                    </div>
                </div>
            </header>

            <main className={styles.main} id="main-content">
                {children}
            </main>
        </div>
    );
};

export default Layout;
