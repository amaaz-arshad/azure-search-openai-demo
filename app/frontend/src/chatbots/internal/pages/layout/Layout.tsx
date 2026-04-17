import { useEffect, useRef, useState } from "react";
import { Link, Outlet } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { IconButton } from "@fluentui/react";
import { ArrowUpload24Regular, ChatAdd24Regular, History24Regular, Settings24Regular } from "@fluentui/react-icons";

import { useLogin } from "../../authConfig";
import { UploadManagerModal } from "../../../demo/components/UploadManagerModal/UploadManagerModal";
import { LoginButton } from "../../../lemon/components/LoginButton";
import lemonChatbotLogo from "../../../lemon/assets/lemon-chatbot.png";
import styles from "../../../lemon/pages/layout/Layout.module.css";

let globalClearChat: () => void = () => {};

export const setGlobalClearChat = (fn: () => void) => {
    globalClearChat = fn;
};

export interface InternalLayoutOutletContext {
    setRecentChatsAction: (action: { run: () => void } | null) => void;
    setDeveloperOptionsAction: (action: { run: () => void } | null) => void;
}

const Layout = () => {
    const { t } = useTranslation();
    const dropdownRef = useRef<HTMLDivElement | null>(null);
    const [dropdownOpen, setDropdownOpen] = useState(false);
    const [isUploadManagerOpen, setIsUploadManagerOpen] = useState(false);
    const [recentChatsAction, setRecentChatsAction] = useState<{ run: () => void } | null>(null);
    const [developerOptionsAction, setDeveloperOptionsAction] = useState<{ run: () => void } | null>(null);

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

    const handleOpenUploadManager = () => {
        setDropdownOpen(false);
        setIsUploadManagerOpen(true);
    };

    const handleOpenDeveloperOptions = () => {
        setDropdownOpen(false);
        developerOptionsAction?.run();
    };

    return (
        <div className={styles.layout}>
            <header className={styles.header} role="banner">
                <div className={styles.headerContainer}>
                    <Link className={styles.logoContainer} to="/internal">
                        <div className={styles.logoCircle}>
                            <img alt="Internal Bot logo" src={lemonChatbotLogo} />
                        </div>
                    </Link>

                    <div className={styles.navbarTitle}>{t("headerTitle")}</div>

                    <div className={styles.rightSection}>
                        {useLogin && <LoginButton />}
                        <div className={styles.dropdown} ref={dropdownRef}>
                            <IconButton
                                ariaLabel={t("labels.toggleMenu")}
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
                                        <button className={styles.dropdownItem} onClick={handleOpenUploadManager}>
                                            <ArrowUpload24Regular />
                                            <span>{t("upload.menuLabel")}</span>
                                        </button>
                                    </li>
                                    <li>
                                        <button className={styles.dropdownItem} onClick={handleOpenDeveloperOptions}>
                                            <Settings24Regular />
                                            <span>{t("developerSettings")}</span>
                                        </button>
                                    </li>
                                </ul>
                            )}
                        </div>
                    </div>
                </div>
            </header>

            <main className={styles.main} id="main-content">
                <Outlet context={{ setRecentChatsAction, setDeveloperOptionsAction }} />
            </main>

            <UploadManagerModal chatbotName="internal" isOpen={isUploadManagerOpen} onClose={() => setIsUploadManagerOpen(false)} />
        </div>
    );
};

export default Layout;
