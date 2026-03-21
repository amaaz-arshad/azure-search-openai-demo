import React, { useState, useEffect, useRef, RefObject } from "react";
import { Outlet, Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import styles from "./Layout.module.css";

import { useLogin } from "../../authConfig";

import { LoginButton } from "../../components/LoginButton";
import { IconButton } from "@fluentui/react";
import { ChatDismiss24Regular, SignOut24Regular } from "@fluentui/react-icons";
import fhgLogo from "../../assets/grafik.png";
import { logout } from "../basicauth/basicAuth";

// At the top of the file, outside the component
let globalClearChat: () => void = () => {};

// Function to set the clear chat callback
export const setGlobalClearChat = (fn: () => void) => {
    globalClearChat = fn;
};

const Layout = () => {
    const { t } = useTranslation();
    const [menuOpen, setMenuOpen] = useState(false);
    const [dropdownOpen, setDropdownOpen] = useState(false);
    const menuRef: RefObject<HTMLDivElement> = useRef(null);
    const dropdownRef: RefObject<HTMLDivElement> = useRef(null);

    const toggleMenu = () => {
        setMenuOpen(!menuOpen);
    };

    const toggleDropdown = () => {
        setDropdownOpen(!dropdownOpen);
    };

    const handleClickOutside = (event: MouseEvent) => {
        if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
            setMenuOpen(false);
        }
        if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
            setDropdownOpen(false);
        }
    };

    useEffect(() => {
        if (menuOpen || dropdownOpen) {
            document.addEventListener("mousedown", handleClickOutside);
        } else {
            document.removeEventListener("mousedown", handleClickOutside);
        }
        return () => {
            document.removeEventListener("mousedown", handleClickOutside);
        };
    }, [menuOpen, dropdownOpen]);

    const handleStartNewChat = () => {
        setDropdownOpen(false);
        // Add your start new chat logic here
        console.log("Start new chat");
    };

    // Inside the Layout component:
    const handleEndChat = () => {
        setDropdownOpen(false);
        globalClearChat();
    };

    const handleViewRecentChats = () => {
        setDropdownOpen(false);
        // Add your view recent chats logic here
        console.log("View recent chats");
    };

    const handleBasicLogout = () => {
        setDropdownOpen(false);
        logout();
        window.location.reload();
    };

    return (
        <div className={styles.layout}>
            <header className={styles.header} role={"banner"}>
                <div className={styles.headerContainer}>
                    {/* Left: Logo */}
                    <Link to="/" className={styles.logoContainer}>
                        <div className={styles.logoCircle}>
                            <img src={fhgLogo} alt="FHG chatbot logo" />
                        </div>
                    </Link>

                    {/* Center: Title */}
                    <div className={styles.navbarTitle}>{t("headerTitle")}</div>

                    {/* Right: Menu and Login */}
                    <div className={styles.rightSection}>
                        {useLogin && <LoginButton />}
                        <div className={styles.dropdown} ref={dropdownRef}>
                            <IconButton
                                iconProps={{ iconName: "More", styles: { root: { fontSize: "25px", color: "var(--chatbot-navbar-text)" } } }} // Increase from default 16px
                                className={styles.menuButton}
                                onClick={toggleDropdown}
                                ariaLabel={t("labels.openMenu")}
                            />
                            {dropdownOpen && (
                                <ul className={styles.dropdownMenu}>
                                    {/* <li>
                                        <button className={styles.dropdownItem} style={{ opacity: 0.5, cursor: "not-allowed" }} onClick={() => {}} disabled>
                                            <ChatAdd24Regular />
                                            <span>Start a new chat</span>
                                        </button>
                                    </li> */}
                                    <li>
                                        <button className={styles.dropdownItem} onClick={handleEndChat}>
                                            <ChatDismiss24Regular />
                                            <span>{t("clearChat")}</span>
                                        </button>
                                    </li>
                                    {/* <li>
                                        <button className={styles.dropdownItem} style={{ opacity: 0.5, cursor: "not-allowed" }} onClick={() => {}} disabled>
                                            <History24Regular />
                                            <span>View recent chats</span>
                                        </button>
                                    </li> */}
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
                <Outlet />
            </main>
        </div>
    );
};

export default Layout;
