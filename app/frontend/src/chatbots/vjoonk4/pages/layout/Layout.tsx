import { useEffect, useRef, useState } from "react";
import { Link, Outlet } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { IconButton } from "@fluentui/react";
import { ChatAdd24Regular, History24Regular, SignOut24Regular } from "@fluentui/react-icons";

import { useLogin } from "../../authConfig";
import { LoginButton } from "../../components/LoginButton";
import vjoonk4Logo from "../../../../assets/robo1.png";
import { logout } from "../basicauth/basicAuth";
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

    const handleBasicLogout = () => {
        setDropdownOpen(false);
        logout();
        window.location.reload();
    };

    return (
        <div className={styles.layout}>
            <header className={styles.header} role="banner">
                <div className={styles.headerContainer}>
                    <Link className={styles.logoContainer} to="/vjoonk4">
                        <div className={styles.logoCircle}>
                            <img alt="vjoonK4 logo" src={vjoonk4Logo} />
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
                                    <li>
                                        <button className={styles.dropdownItem} onClick={handleOpenRecentChats}>
                                            <History24Regular />
                                            <span>{t("history.viewRecentChats")}</span>
                                        </button>
                                    </li>
                                    <li>
                                        <button className={styles.dropdownItem} onClick={handleBasicLogout}>
                                            <SignOut24Regular />
                                            <span>{t("logout")}</span>
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
