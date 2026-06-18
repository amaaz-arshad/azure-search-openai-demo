import { useContext, useEffect, useRef, useState } from "react";
import { Link, Outlet } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { IconButton } from "@fluentui/react";
import { ArrowUpload24Regular, ChatAdd24Regular, History24Regular, Person24Regular, SignOut24Regular } from "@fluentui/react-icons";

import { useLogin } from "../../authConfig";
import { UploadManagerModal } from "../../components/UploadManagerModal/UploadManagerModal";
import { LoginButton } from "../../components/LoginButton";
import nerilioLogo from "../../../nerilio/assets/robo1.png";
import { LoginContext } from "../../loginContext";
import { getCurrentProfile, logout, FreeProfile } from "../basicauth/basicAuth";
import styles from "./Layout.module.css";

let globalClearChat: () => void = () => {};

export const setGlobalClearChat = (fn: () => void) => {
    globalClearChat = fn;
};

const Layout = () => {
    const { t, i18n } = useTranslation();
    const { currentUser } = useContext(LoginContext);
    const dropdownRef = useRef<HTMLDivElement | null>(null);
    const [dropdownOpen, setDropdownOpen] = useState(false);
    const [isUploadManagerOpen, setIsUploadManagerOpen] = useState(false);
    const [isProfileOpen, setIsProfileOpen] = useState(false);
    const [isProfileLoading, setIsProfileLoading] = useState(false);
    const [profileError, setProfileError] = useState("");
    const [profile, setProfile] = useState<FreeProfile | null>(null);
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

    const handleOpenUploadManager = () => {
        setDropdownOpen(false);
        setIsUploadManagerOpen(true);
    };

    const handleOpenProfile = () => {
        setDropdownOpen(false);
        setIsProfileOpen(true);
    };

    const handleBasicLogout = async () => {
        setDropdownOpen(false);
        await logout();
        window.location.reload();
    };

    useEffect(() => {
        if (!isProfileOpen || !currentUser) {
            return;
        }

        let isMounted = true;
        setIsProfileLoading(true);
        setProfileError("");

        void getCurrentProfile()
            .then(profileResult => {
                if (!isMounted) {
                    return;
                }
                setProfile(profileResult);
            })
            .catch(error => {
                console.error("nerilio profile load failed", error);
                if (!isMounted) {
                    return;
                }
                setProfileError(t("profile.loadError"));
            })
            .finally(() => {
                if (isMounted) {
                    setIsProfileLoading(false);
                }
            });

        return () => {
            isMounted = false;
        };
    }, [currentUser, isProfileOpen, t]);

    const formatProfileDate = (value: string) => {
        try {
            return new Intl.DateTimeFormat(i18n.language || undefined, {
                dateStyle: "medium",
                timeStyle: "short"
            }).format(new Date(value));
        } catch {
            return value;
        }
    };

    return (
        <div className={styles.layout}>
            <header className={styles.header} role="banner">
                <div className={styles.headerContainer}>
                    <Link className={styles.logoContainer} to="/free">
                        <div className={styles.logoCircle}>
                            <img alt="nerilio logo" src={nerilioLogo} />
                        </div>
                    </Link>

                    <div className={styles.navbarTitle}>{t("headerTitle")}</div>

                    <div className={styles.rightSection}>
                        {useLogin && <LoginButton />}
                        <div className={styles.dropdown} ref={dropdownRef}>
                            <IconButton
                                ariaLabel={t("labels.toggleMenu")}
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
                                    <li>
                                        <button className={styles.dropdownItem} onClick={handleOpenUploadManager}>
                                            <ArrowUpload24Regular />
                                            <span>{t("upload.menuLabel")}</span>
                                        </button>
                                    </li>
                                    <li>
                                        <button className={styles.dropdownItem} onClick={handleOpenProfile}>
                                            <Person24Regular />
                                            <span>{t("profile.menuLabel")}</span>
                                        </button>
                                    </li>
                                    <li>
                                        <button className={styles.dropdownItem} onClick={() => void handleBasicLogout()}>
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

            <UploadManagerModal chatbotName="free" isOpen={isUploadManagerOpen} onClose={() => setIsUploadManagerOpen(false)} />

            {isProfileOpen && (
                <div className={styles.profileOverlay} onClick={() => setIsProfileOpen(false)} role="presentation">
                    <section aria-labelledby="free-profile-title" className={styles.profileModal} onClick={event => event.stopPropagation()}>
                        <div className={styles.profileHeader}>
                            <div>
                                <h2 className={styles.profileTitle} id="free-profile-title">
                                    {t("profile.title")}
                                </h2>
                                <p className={styles.profileSubtitle}>{t("profile.subtitle")}</p>
                            </div>
                            <button className={styles.profileCloseButton} onClick={() => setIsProfileOpen(false)} type="button">
                                {t("labels.closeButton")}
                            </button>
                        </div>

                        {isProfileLoading ? (
                            <p className={styles.profileLoading}>{t("profile.loading")}</p>
                        ) : profileError ? (
                            <p className={styles.profileError}>{profileError}</p>
                        ) : (
                            <dl className={styles.profileDetails}>
                                <div className={styles.profileRow}>
                                    <dt>{t("profile.displayName")}</dt>
                                    <dd>{profile?.displayName ?? currentUser?.displayName ?? "-"}</dd>
                                </div>
                                <div className={styles.profileRow}>
                                    <dt>{t("profile.email")}</dt>
                                    <dd>{profile?.email ?? currentUser?.email ?? "-"}</dd>
                                </div>
                                <div className={styles.profileRow}>
                                    <dt>{t("profile.createdAt")}</dt>
                                    <dd>{profile?.createdAt ? formatProfileDate(profile.createdAt) : "-"}</dd>
                                </div>
                                <div className={styles.profileRow}>
                                    <dt>{t("profile.updatedAt")}</dt>
                                    <dd>{profile?.updatedAt ? formatProfileDate(profile.updatedAt) : "-"}</dd>
                                </div>
                            </dl>
                        )}
                    </section>
                </div>
            )}
        </div>
    );
};

export default Layout;
