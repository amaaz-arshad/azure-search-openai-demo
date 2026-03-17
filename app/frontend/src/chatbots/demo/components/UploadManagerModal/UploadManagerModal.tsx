import { ChangeEvent, DragEvent, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Button } from "@fluentui/react-components";
import {
    ArrowClockwise24Regular,
    ArrowUpload24Regular,
    Delete24Regular,
    Dismiss24Regular,
    Document24Regular
} from "@fluentui/react-icons";
import { useTranslation } from "react-i18next";

import { deleteChatbotUploadedFileApi, listChatbotUploadedFilesApi, uploadChatbotFilesApi } from "../../api";
import styles from "./UploadManagerModal.module.css";

type Props = {
    chatbotName: string;
    isOpen: boolean;
    onClose: () => void;
};

type StatusState =
    | {
          tone: "success" | "warning" | "error";
          message: string;
      }
    | undefined;

const acceptedFileTypes = ".txt,.md,.csv,.json,.pdf,.html,.xml";

const formatExtension = (filename: string) => {
    const extension = filename.split(".").pop();
    return extension ? extension.toUpperCase() : "FILE";
};

export const UploadManagerModal = ({ chatbotName, isOpen, onClose }: Props) => {
    const { t } = useTranslation();
    const titleId = useId();
    const fileInputRef = useRef<HTMLInputElement | null>(null);
    const [uploadedFiles, setUploadedFiles] = useState<string[]>([]);
    const [isLoading, setIsLoading] = useState(false);
    const [isUploading, setIsUploading] = useState(false);
    const [isDragActive, setIsDragActive] = useState(false);
    const [deletingFiles, setDeletingFiles] = useState<Record<string, boolean>>({});
    const [status, setStatus] = useState<StatusState>();

    const loadFiles = async () => {
        setIsLoading(true);
        try {
            const files = await listChatbotUploadedFilesApi(chatbotName);
            setUploadedFiles(files);
        } catch (error) {
            setStatus({
                tone: "error",
                message: error instanceof Error ? error.message : t("upload.listError")
            });
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        if (!isOpen) {
            return;
        }

        void loadFiles();
        const previousOverflow = document.body.style.overflow;
        document.body.style.overflow = "hidden";

        const handleEscape = (event: KeyboardEvent) => {
            if (event.key === "Escape") {
                onClose();
            }
        };

        document.addEventListener("keydown", handleEscape);
        return () => {
            document.body.style.overflow = previousOverflow;
            document.removeEventListener("keydown", handleEscape);
        };
    }, [isOpen, onClose]);

    const resetFileInput = () => {
        if (fileInputRef.current) {
            fileInputRef.current.value = "";
        }
    };

    const uploadFiles = async (files: File[]) => {
        if (files.length === 0) {
            return;
        }

        setIsUploading(true);
        setStatus(undefined);
        const formData = new FormData();
        files.forEach(file => formData.append("files", file));

        try {
            const response = await uploadChatbotFilesApi(chatbotName, formData);
            const uploadTone = response.failedFiles.length > 0 ? "warning" : "success";
            const failedMessage =
                response.failedFiles.length > 0
                    ? ` ${response.failedFiles.map(file => `${file.filename}: ${file.message}`).join(" ")}`
                    : "";

            setStatus({
                tone: uploadTone,
                message: `${response.message ?? ""}${failedMessage}`.trim()
            });
            await loadFiles();
        } catch (error) {
            setStatus({
                tone: "error",
                message: error instanceof Error ? error.message : t("upload.uploadedFileError")
            });
        } finally {
            resetFileInput();
            setIsUploading(false);
        }
    };

    const handleInputChange = async (event: ChangeEvent<HTMLInputElement>) => {
        const files = Array.from(event.target.files ?? []);
        await uploadFiles(files);
    };

    const handleDelete = async (filename: string) => {
        setDeletingFiles(current => ({ ...current, [filename]: true }));
        setStatus(undefined);
        try {
            const response = await deleteChatbotUploadedFileApi(chatbotName, filename);
            setStatus({
                tone: "success",
                message: response.message ?? t("upload.fileDeleted")
            });
            await loadFiles();
        } catch (error) {
            setStatus({
                tone: "error",
                message: error instanceof Error ? error.message : t("upload.errorDeleting")
            });
        } finally {
            setDeletingFiles(current => {
                const nextState = { ...current };
                delete nextState[filename];
                return nextState;
            });
        }
    };

    const handleDrop = async (event: DragEvent<HTMLDivElement>) => {
        event.preventDefault();
        setIsDragActive(false);
        const files = Array.from(event.dataTransfer.files ?? []);
        await uploadFiles(files);
    };

    if (!isOpen) {
        return null;
    }

    return createPortal(
        <div className={styles.backdrop} onMouseDown={onClose}>
            <div
                aria-labelledby={titleId}
                aria-modal="true"
                className={styles.dialog}
                onMouseDown={event => event.stopPropagation()}
                role="dialog"
            >
                <div className={styles.header}>
                    <div>
                        <p className={styles.eyebrow}>{t("upload.menuLabel")}</p>
                        <h2 className={styles.title} id={titleId}>
                            {t("upload.modalTitle")}
                        </h2>
                        <p className={styles.description}>{t("upload.modalDescription")}</p>
                    </div>
                    <button aria-label={t("upload.close")} className={styles.closeButton} onClick={onClose} type="button">
                        <Dismiss24Regular />
                    </button>
                </div>

                <div className={styles.toolbar}>
                    <Button appearance="primary" icon={<ArrowUpload24Regular />} onClick={() => fileInputRef.current?.click()}>
                        {t("upload.chooseFiles")}
                    </Button>
                    <Button appearance="secondary" icon={<ArrowClockwise24Regular />} onClick={() => void loadFiles()}>
                        {t("upload.refreshList")}
                    </Button>
                </div>

                <input
                    accept={acceptedFileTypes}
                    className={styles.hiddenInput}
                    multiple
                    onChange={event => void handleInputChange(event)}
                    ref={fileInputRef}
                    type="file"
                />

                <div
                    className={`${styles.dropzone} ${isDragActive ? styles.dropzoneActive : ""}`}
                    onClick={() => fileInputRef.current?.click()}
                    onDragEnter={event => {
                        event.preventDefault();
                        setIsDragActive(true);
                    }}
                    onDragLeave={event => {
                        event.preventDefault();
                        setIsDragActive(false);
                    }}
                    onDragOver={event => event.preventDefault()}
                    onDrop={event => void handleDrop(event)}
                    onKeyDown={event => {
                        if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            fileInputRef.current?.click();
                        }
                    }}
                    role="button"
                    tabIndex={0}
                >
                    <div className={styles.dropzoneIcon}>
                        <ArrowUpload24Regular />
                    </div>
                    <p className={styles.dropzoneTitle}>{t("upload.dropzoneTitle")}</p>
                    <p className={styles.dropzoneHint}>{t("upload.dropzoneHint")}</p>
                    <p className={styles.supportedFormats}>{t("upload.supportedFormats")}</p>
                </div>

                {(isUploading || status) && (
                    <div
                        className={`${styles.status} ${status ? styles[`status${status.tone[0].toUpperCase()}${status.tone.slice(1)}`] : styles.statusNeutral}`}
                        role="status"
                    >
                        {isUploading ? t("upload.uploadingFiles") : status?.message}
                    </div>
                )}

                <div className={styles.sectionHeader}>
                    <div>
                        <p className={styles.sectionLabel}>{t("upload.sectionTitle")}</p>
                        <h3 className={styles.sectionTitle}>{t("upload.uploadedFilesLabel")}</h3>
                    </div>
                    <span className={styles.fileCount}>{uploadedFiles.length}</span>
                </div>

                <div className={styles.fileList}>
                    {isLoading && <p className={styles.infoMessage}>{t("upload.loading")}</p>}
                    {!isLoading && uploadedFiles.length === 0 && (
                        <div className={styles.emptyState}>
                            <Document24Regular />
                            <div>
                                <p className={styles.emptyStateTitle}>{t("upload.emptyStateTitle")}</p>
                                <p className={styles.emptyStateDescription}>{t("upload.emptyStateDescription")}</p>
                            </div>
                        </div>
                    )}
                    {!isLoading &&
                        uploadedFiles.map(filename => (
                            <div className={styles.fileRow} key={filename}>
                                <div className={styles.fileMeta}>
                                    <div className={styles.fileBadge}>{formatExtension(filename)}</div>
                                    <div className={styles.fileDetails}>
                                        <span className={styles.fileName}>{filename}</span>
                                        <span className={styles.fileSubtext}>{t("upload.fileReady")}</span>
                                    </div>
                                </div>
                                <Button
                                    appearance="subtle"
                                    className={styles.deleteButton}
                                    disabled={Boolean(deletingFiles[filename])}
                                    icon={<Delete24Regular />}
                                    onClick={() => void handleDelete(filename)}
                                >
                                    {deletingFiles[filename] ? t("upload.deletingFile") : t("upload.deleteFile")}
                                </Button>
                            </div>
                        ))}
                </div>
            </div>
        </div>,
        document.body
    );
};
