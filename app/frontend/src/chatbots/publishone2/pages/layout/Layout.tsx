import { useEffect, useRef, useState } from "react";
import { Link, Outlet } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { IconButton } from "@fluentui/react";
import { ChatAdd24Regular, History24Regular } from "@fluentui/react-icons";

import { useLogin } from "../../authConfig";
import { LoginButton } from "../../components/LoginButton";
import publishoneNavLogo from "../../../../assets/publishone-nav.svg";
import styles from "./Layout.module.css";

let globalClearChat: () => void = () => {};

export const setGlobalClearChat = (fn: () => void) => {
    globalClearChat = fn;
};

const Layout = () => {
    const { t } = useTranslation();
    const dropdownRef = useRef<HTMLDivElement | null>(null);
    const [dropdownOpen, setDropdownOpen] = useState(false);
    const [recentChatsAction, setRecentChatsAction] = useState<{ run: () => void } | null>(null);

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
        recentChatsAction?.run();
    };

    return (
        <div className={styles.layout}>
            <header className={styles.header} role="banner">
                <div className={styles.headerContainer}>
                    <Link aria-label="Go to home page" className={styles.logoContainer} to="/publishone2">
                        <img alt="PublishOne logo" className={styles.brandWordmark} src={publishoneNavLogo} />
                    </Link>

                    <div className={styles.rightSection}>
                        {useLogin && <LoginButton />}
                        <div className={styles.dropdown} ref={dropdownRef}>
                            <IconButton
                                ariaLabel={t("labels.openMenu")}
                                className={styles.menuButton}
                                iconProps={{ iconName: "More", styles: { root: { fontSize: "25px", color: "var(--chatbot-navbar-text)" } } }}
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
                                    <li>
                                        <button className={styles.dropdownItem} onClick={handleOpenRecentChats}>
                                            <History24Regular />
                                            <span>{t("history.viewRecentChats")}</span>
                                        </button>
                                    </li>
                                </ul>
                            )}
                        </div>
                    </div>
                </div>
            </header>

            <main className={styles.main} id="main-content">
                <Outlet context={{ setRecentChatsAction }} />
            </main>
        </div>
    );
};

export default Layout;
