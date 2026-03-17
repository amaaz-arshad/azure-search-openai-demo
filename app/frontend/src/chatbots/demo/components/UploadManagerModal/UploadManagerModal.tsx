import { ChangeEvent, DragEvent, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Button } from "@fluentui/react-components";
import {
    ArrowClockwise24Regular,
    ArrowUpload24Regular,
    Delete24Regular,
    Dismiss24Regular,
    Document24Regular,
    Stop24Regular
} from "@fluentui/react-icons";
import { useTranslation } from "react-i18next";

import {
    cancelChatbotUploadApi,
    deleteChatbotUploadedFileApi,
    listChatbotUploadedFilesApi,
    uploadChatbotFilesApi
} from "../../api";
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

type QueueItemStatus = "queued" | "uploading" | "canceling" | "completed" | "completedAfterStop" | "failed" | "canceled";

type UploadQueueItem = {
    id: string;
    uploadId: string;
    file: File;
    filename: string;
    status: QueueItemStatus;
    message?: string;
};

const acceptedFileTypes = ".txt,.md,.csv,.json,.pdf,.html,.xml";
const acceptedExtensions = new Set([".txt", ".md", ".csv", ".json", ".pdf", ".html", ".xml"]);
const activeStatuses: QueueItemStatus[] = ["queued", "uploading", "canceling"];

const formatExtension = (filename: string) => {
    const extension = filename.split(".").pop();
    return extension ? extension.toUpperCase() : "FILE";
};

const getFileExtension = (filename: string) => {
    const parts = filename.toLowerCase().split(".");
    return parts.length > 1 ? `.${parts.pop()}` : "";
};

const createUniqueId = () => {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
        return crypto.randomUUID();
    }
    return `upload-${Date.now()}-${Math.random().toString(16).slice(2)}`;
};

export const UploadManagerModal = ({ chatbotName, isOpen, onClose }: Props) => {
    const { t } = useTranslation();
    const titleId = useId();
    const fileInputRef = useRef<HTMLInputElement | null>(null);
    const queueRef = useRef<UploadQueueItem[]>([]);
    const currentAbortRef = useRef<AbortController | null>(null);
    const currentUploadIdRef = useRef<string | null>(null);
    const currentQueueItemIdRef = useRef<string | null>(null);
    const processingRef = useRef(false);
    const stopRequestedRef = useRef(false);
    const [uploadedFiles, setUploadedFiles] = useState<string[]>([]);
    const [queueItems, setQueueItems] = useState<UploadQueueItem[]>([]);
    const [isLoading, setIsLoading] = useState(false);
    const [isProcessingQueue, setIsProcessingQueue] = useState(false);
    const [isStopping, setIsStopping] = useState(false);
    const [isDragActive, setIsDragActive] = useState(false);
    const [deletingFiles, setDeletingFiles] = useState<Record<string, boolean>>({});
    const [status, setStatus] = useState<StatusState>();

    const hasActiveQueue = queueItems.some(item => activeStatuses.includes(item.status));

    const setQueueState = (updater: (current: UploadQueueItem[]) => UploadQueueItem[]) => {
        setQueueItems(current => {
            const nextState = updater(current);
            queueRef.current = nextState;
            return nextState;
        });
    };

    const updateQueueItem = (itemId: string, changes: Partial<UploadQueueItem>) => {
        setQueueState(current =>
            current.map(item => {
                if (item.id !== itemId) {
                    return item;
                }
                return { ...item, ...changes };
            })
        );
    };

    const removeQueueItem = (itemId: string) => {
        setQueueState(current => current.filter(item => item.id !== itemId));
    };

    const loadFiles = async (options?: { suppressErrors?: boolean }) => {
        setIsLoading(true);
        try {
            const files = await listChatbotUploadedFilesApi(chatbotName);
            setUploadedFiles(files);
            return files;
        } catch (error) {
            if (!options?.suppressErrors) {
                setStatus({
                    tone: "error",
                    message: error instanceof Error ? error.message : t("upload.listError")
                });
            }
            return uploadedFiles;
        } finally {
            setIsLoading(false);
        }
    };

    const resetFileInput = () => {
        if (fileInputRef.current) {
            fileInputRef.current.value = "";
        }
    };

    const markQueuedItemsCanceled = (message: string) => {
        setQueueState(current =>
            current.map(item => {
                if (item.status !== "queued") {
                    return item;
                }
                return { ...item, status: "canceled", message };
            })
        );
    };

    const getQueueSummary = () => {
        const completedCount = queueRef.current.filter(item =>
            ["completed", "completedAfterStop"].includes(item.status)
        ).length;
        const failedCount = queueRef.current.filter(item => item.status === "failed").length;
        const canceledCount = queueRef.current.filter(item => item.status === "canceled").length;
        return { completedCount, failedCount, canceledCount };
    };

    const setStopSummary = () => {
        const { completedCount, failedCount, canceledCount } = getQueueSummary();
        setStatus({
            tone: canceledCount > 0 ? "warning" : "success",
            message: t("upload.stopSummary", {
                completedCount,
                failedCount,
                canceledCount
            })
        });
    };

    const reconcileAbortedUpload = async (item: UploadQueueItem) => {
        const latestFiles = await loadFiles({ suppressErrors: true });
        const fileFinished = latestFiles.includes(item.filename);
        updateQueueItem(item.id, {
            status: fileFinished ? "completedAfterStop" : "canceled",
            message: fileFinished ? t("upload.queueCompletedBeforeStop") : t("upload.queueCanceled")
        });
    };

    const runQueue = async () => {
        if (processingRef.current) {
            return;
        }

        processingRef.current = true;
        setIsProcessingQueue(true);
        try {
            while (true) {
                const nextItem = queueRef.current.find(item => item.status === "queued");
                if (!nextItem) {
                    break;
                }

                if (stopRequestedRef.current) {
                    markQueuedItemsCanceled(t("upload.queueCanceled"));
                    break;
                }

                const abortController = new AbortController();
                currentAbortRef.current = abortController;
                currentUploadIdRef.current = nextItem.uploadId;
                currentQueueItemIdRef.current = nextItem.id;
                updateQueueItem(nextItem.id, {
                    status: "uploading",
                    message: t("upload.queueUploading")
                });

                const formData = new FormData();
                formData.append("files", nextItem.file, nextItem.filename);

                try {
                    const response = await uploadChatbotFilesApi(chatbotName, formData, {
                        signal: abortController.signal,
                        uploadId: nextItem.uploadId
                    });
                    const failedUpload = response.failedFiles.find(file => file.filename === nextItem.filename);
                    if (failedUpload) {
                        updateQueueItem(nextItem.id, {
                            status: failedUpload.message === "Upload canceled" ? "canceled" : "failed",
                            message: failedUpload.message
                        });
                    } else {
                        updateQueueItem(nextItem.id, {
                            status: "completed",
                            message: t("upload.queueCompleted")
                        });
                    }
                    await loadFiles({ suppressErrors: true });
                } catch (error) {
                    const isAbortError =
                        abortController.signal.aborted || (error instanceof DOMException && error.name === "AbortError");

                    if (isAbortError) {
                        await reconcileAbortedUpload(nextItem);
                    } else {
                        updateQueueItem(nextItem.id, {
                            status: stopRequestedRef.current ? "canceled" : "failed",
                            message: error instanceof Error ? error.message : t("upload.uploadedFileError")
                        });
                    }
                } finally {
                    currentAbortRef.current = null;
                    currentUploadIdRef.current = null;
                    currentQueueItemIdRef.current = null;
                }

                if (stopRequestedRef.current) {
                    markQueuedItemsCanceled(t("upload.queueCanceled"));
                    break;
                }
            }
        } finally {
            processingRef.current = false;
            setIsProcessingQueue(false);
            if (stopRequestedRef.current) {
                setStopSummary();
            }
            stopRequestedRef.current = false;
            setIsStopping(false);
        }
    };

    const enqueueFiles = (files: File[]) => {
        if (files.length === 0) {
            return;
        }

        if (isStopping) {
            setStatus({
                tone: "warning",
                message: t("upload.waitForStop")
            });
            return;
        }

        const activeFilenames = new Set(
            queueRef.current
                .filter(item => activeStatuses.includes(item.status))
                .map(item => item.filename.toLowerCase())
        );
        const selectionFilenames = new Set<string>();
        const nextItems: UploadQueueItem[] = [];
        const issues: string[] = [];

        for (const file of files) {
            const filename = file.name;
            const filenameKey = filename.toLowerCase();

            if (!acceptedExtensions.has(getFileExtension(filename))) {
                issues.push(t("upload.unsupportedFileType", { filename }));
                continue;
            }

            if (activeFilenames.has(filenameKey) || selectionFilenames.has(filenameKey)) {
                issues.push(t("upload.duplicateQueuedFile", { filename }));
                continue;
            }

            selectionFilenames.add(filenameKey);
            nextItems.push({
                id: createUniqueId(),
                uploadId: createUniqueId(),
                file,
                filename,
                status: "queued",
                message: t("upload.queueQueued")
            });
        }

        if (nextItems.length > 0) {
            setQueueState(current => [...current, ...nextItems]);
        }

        if (issues.length > 0) {
            setStatus({
                tone: "warning",
                message: issues.join(" ")
            });
        } else {
            setStatus(undefined);
        }

        resetFileInput();
    };

    const requestStopUploads = async () => {
        if (!hasActiveQueue || isStopping) {
            return;
        }

        stopRequestedRef.current = true;
        setIsStopping(true);
        setStatus({
            tone: "warning",
            message: t("upload.stopRequested")
        });

        const currentItemId = currentQueueItemIdRef.current;
        if (currentItemId) {
            updateQueueItem(currentItemId, {
                status: "canceling",
                message: t("upload.queueCanceling")
            });
        }

        const activeUploadId = currentUploadIdRef.current;
        if (activeUploadId) {
            try {
                await cancelChatbotUploadApi(chatbotName, activeUploadId);
            } catch (error) {
                setStatus({
                    tone: "warning",
                    message: error instanceof Error ? error.message : t("upload.stopRequested")
                });
            }
        }

        currentAbortRef.current?.abort();

        if (!currentItemId) {
            markQueuedItemsCanceled(t("upload.queueCanceled"));
            setStopSummary();
            stopRequestedRef.current = false;
            setIsStopping(false);
        }
    };

    const handleRequestClose = () => {
        setIsDragActive(false);
        onClose();
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
            await loadFiles({ suppressErrors: true });
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

    useEffect(() => {
        queueRef.current = queueItems;
    }, [queueItems]);

    useEffect(() => {
        if (!isOpen) {
            setIsDragActive(false);
            return;
        }

        void loadFiles();
        const previousOverflow = document.body.style.overflow;
        document.body.style.overflow = "hidden";

        const handleEscape = (event: KeyboardEvent) => {
            if (event.key === "Escape") {
                handleRequestClose();
            }
        };

        document.addEventListener("keydown", handleEscape);
        return () => {
            document.body.style.overflow = previousOverflow;
            document.removeEventListener("keydown", handleEscape);
        };
    }, [isOpen]);

    useEffect(() => {
        if (queueItems.some(item => item.status === "queued") && !processingRef.current) {
            void runQueue();
        }
    }, [queueItems]);

    useEffect(() => {
        if (!(hasActiveQueue || isStopping)) {
            return;
        }

        const handleBeforeUnload = (event: BeforeUnloadEvent) => {
            event.preventDefault();
            event.returnValue = "";
        };

        window.addEventListener("beforeunload", handleBeforeUnload);
        return () => window.removeEventListener("beforeunload", handleBeforeUnload);
    }, [isOpen, hasActiveQueue, isStopping]);

    useEffect(() => {
        return () => {
            const activeUploadId = currentUploadIdRef.current;
            if (activeUploadId) {
                void cancelChatbotUploadApi(chatbotName, activeUploadId).catch(() => undefined);
            }
            currentAbortRef.current?.abort();
        };
    }, [chatbotName]);

    const handleInputChange = async (event: ChangeEvent<HTMLInputElement>) => {
        enqueueFiles(Array.from(event.target.files ?? []));
    };

    const handleDrop = async (event: DragEvent<HTMLDivElement>) => {
        event.preventDefault();
        setIsDragActive(false);
        enqueueFiles(Array.from(event.dataTransfer.files ?? []));
    };

    const queueStatusLabel = (statusValue: QueueItemStatus) => {
        switch (statusValue) {
            case "queued":
                return t("upload.queueQueued");
            case "uploading":
                return t("upload.queueUploading");
            case "canceling":
                return t("upload.queueCanceling");
            case "completed":
                return t("upload.queueCompleted");
            case "completedAfterStop":
                return t("upload.queueCompletedBeforeStop");
            case "failed":
                return t("upload.queueFailed");
            case "canceled":
                return t("upload.queueCanceled");
        }
    };

    const queueStatusClass = (statusValue: QueueItemStatus) => {
        switch (statusValue) {
            case "queued":
                return styles.queueStatusQueued;
            case "uploading":
                return styles.queueStatusUploading;
            case "canceling":
                return styles.queueStatusCanceling;
            case "completed":
            case "completedAfterStop":
                return styles.queueStatusCompleted;
            case "failed":
                return styles.queueStatusFailed;
            case "canceled":
                return styles.queueStatusCanceled;
        }
    };

    if (!isOpen) {
        return null;
    }

    return createPortal(
        <div className={styles.backdrop} onMouseDown={handleRequestClose}>
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
                    <button aria-label={t("upload.close")} className={styles.closeButton} onClick={handleRequestClose} type="button">
                        <Dismiss24Regular />
                    </button>
                </div>

                <div className={styles.toolbar}>
                    <Button
                        appearance="primary"
                        disabled={isStopping}
                        icon={<ArrowUpload24Regular />}
                        onClick={() => fileInputRef.current?.click()}
                    >
                        {t("upload.chooseFiles")}
                    </Button>
                    <Button appearance="secondary" icon={<ArrowClockwise24Regular />} onClick={() => void loadFiles()}>
                        {t("upload.refreshList")}
                    </Button>
                    {hasActiveQueue && (
                        <Button
                            appearance="secondary"
                            disabled={isStopping}
                            icon={<Stop24Regular />}
                            onClick={() => void requestStopUploads()}
                        >
                            {t("upload.stopUploads")}
                        </Button>
                    )}
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
                    className={`${styles.dropzone} ${isDragActive ? styles.dropzoneActive : ""} ${isStopping ? styles.dropzoneDisabled : ""}`}
                    onClick={() => {
                        if (!isStopping) {
                            fileInputRef.current?.click();
                        }
                    }}
                    onDragEnter={event => {
                        event.preventDefault();
                        if (!isStopping) {
                            setIsDragActive(true);
                        }
                    }}
                    onDragLeave={event => {
                        event.preventDefault();
                        setIsDragActive(false);
                    }}
                    onDragOver={event => event.preventDefault()}
                    onDrop={event => void handleDrop(event)}
                    onKeyDown={event => {
                        if ((event.key === "Enter" || event.key === " ") && !isStopping) {
                            event.preventDefault();
                            fileInputRef.current?.click();
                        }
                    }}
                    role="button"
                    tabIndex={isStopping ? -1 : 0}
                >
                    <div className={styles.dropzoneIcon}>
                        <ArrowUpload24Regular />
                    </div>
                    <p className={styles.dropzoneTitle}>{t("upload.dropzoneTitle")}</p>
                    <p className={styles.dropzoneHint}>{t("upload.dropzoneHint")}</p>
                    <p className={styles.supportedFormats}>{t("upload.supportedFormats")}</p>
                </div>

                {(isProcessingQueue || status) && (
                    <div
                        className={`${styles.status} ${status ? styles[`status${status.tone[0].toUpperCase()}${status.tone.slice(1)}`] : styles.statusNeutral}`}
                        role="status"
                    >
                        {isProcessingQueue && !status ? t("upload.uploadingFiles") : status?.message}
                    </div>
                )}

                <div className={styles.sectionHeader}>
                    <div>
                        <p className={styles.sectionLabel}>{t("upload.queueSectionTitle")}</p>
                        <h3 className={styles.sectionTitle}>{t("upload.uploadQueueLabel")}</h3>
                    </div>
                    <span className={styles.fileCount}>{queueItems.length}</span>
                </div>

                <div className={styles.fileList}>
                    {queueItems.length === 0 && (
                        <div className={styles.emptyState}>
                            <Document24Regular />
                            <div>
                                <p className={styles.emptyStateTitle}>{t("upload.emptyQueueTitle")}</p>
                                <p className={styles.emptyStateDescription}>{t("upload.emptyQueueDescription")}</p>
                            </div>
                        </div>
                    )}
                    {queueItems.map(item => (
                        <div className={styles.fileRow} key={item.id}>
                            <div className={styles.fileMeta}>
                                <div className={styles.fileBadge}>{formatExtension(item.filename)}</div>
                                <div className={styles.fileDetails}>
                                    <span className={styles.fileName}>{item.filename}</span>
                                    <span className={styles.fileSubtext}>{item.message ?? queueStatusLabel(item.status)}</span>
                                </div>
                            </div>
                            <div className={styles.queueActions}>
                                <span className={`${styles.queueStatus} ${queueStatusClass(item.status)}`}>
                                    {queueStatusLabel(item.status)}
                                </span>
                                {!activeStatuses.includes(item.status) && (
                                    <Button
                                        appearance="subtle"
                                        className={styles.dismissButton}
                                        onClick={() => removeQueueItem(item.id)}
                                    >
                                        {t("upload.dismissQueueItem")}
                                    </Button>
                                )}
                            </div>
                        </div>
                    ))}
                </div>

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
                                    disabled={Boolean(deletingFiles[filename]) || hasActiveQueue || isStopping}
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
