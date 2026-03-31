import { ChangeEvent, DragEvent, FormEvent, startTransition, useEffect, useRef, useState } from "react";
import { Helmet } from "react-helmet-async";
import { Link } from "react-router-dom";
import { Icon } from "@fluentui/react";
import {
    ArrowClockwise24Regular,
    ArrowUpload24Regular,
    Delete24Regular,
    Document24Regular,
    Stop24Regular
} from "@fluentui/react-icons";

import {
    INTERNAL_TOOLS_PASSWORD,
    INTERNAL_TOOLS_SESSION_KEY,
    getInitialInternalAuthenticationState
} from "./internalToolsAccess";
import {
    ManagedUploadCreatedEntry,
    ManagedUploadEntry,
    cancelManagedUploadApi,
    deleteManagedUploadedFileApi,
    deleteManagedUploadedFilesApi,
    listManagedUploadsApi,
    uploadManagedFilesApi
} from "./uploadFilesApi";
import styles from "./UploadFilesPage.module.css";

const acceptedFileTypes = ".txt,.md,.csv,.json,.pdf,.html,.xml";
const acceptedExtensions = new Set([".txt", ".md", ".csv", ".json", ".pdf", ".html", ".xml"]);
const allCategoriesValue = "all";
const categoryPattern = /^[a-z0-9][a-z0-9_-]{0,63}$/;
const pageSizeOptions = [10, 15];

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
    category: string;
    file: File;
    filename: string;
    status: QueueItemStatus;
    message?: string;
};

const activeStatuses: QueueItemStatus[] = ["queued", "uploading", "canceling"];

const formatExtension = (filename: string) => {
    const extension = filename.split(".").pop();
    return extension ? extension.toUpperCase() : "FILE";
};

const getFileExtension = (filename: string) => {
    const parts = filename.toLowerCase().split(".");
    return parts.length > 1 ? `.${parts.pop()}` : "";
};

const normalizeCategory = (value: string) => value.trim().toLowerCase();

const validateCategory = (value: string) => {
    const normalized = normalizeCategory(value);
    if (!normalized) {
        return { ok: false, message: "Category is required.", normalized };
    }
    if (!categoryPattern.test(normalized)) {
        return {
            ok: false,
            message: "Category must use lowercase letters, numbers, hyphens, or underscores only.",
            normalized
        };
    }
    return { ok: true, normalized };
};

const formatTimestamp = (timestamp?: string | null) => {
    if (!timestamp) {
        return "Uploaded recently";
    }
    const date = new Date(timestamp);
    if (Number.isNaN(date.getTime())) {
        return "Uploaded recently";
    }
    return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
};

const createUniqueId = () => {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
        return crypto.randomUUID();
    }
    return `upload-${Date.now()}-${Math.random().toString(16).slice(2)}`;
};

const sortCategories = (categories: string[]) =>
    Array.from(new Set(categories)).sort((left, right) => left.localeCompare(right));

const matchesLibraryFilters = (entry: ManagedUploadEntry, categoryFilter: string, normalizedQuery: string) => {
    if (categoryFilter !== allCategoriesValue && entry.category !== categoryFilter) {
        return false;
    }
    if (!normalizedQuery) {
        return true;
    }
    return entry.filename.toLowerCase().includes(normalizedQuery) || entry.category.toLowerCase().includes(normalizedQuery);
};

const UploadFilesPage = () => {
    const [isAuthenticated, setIsAuthenticated] = useState<boolean>(getInitialInternalAuthenticationState);
    const [password, setPassword] = useState("");
    const [errorMessage, setErrorMessage] = useState("");
    const [isPasswordVisible, setIsPasswordVisible] = useState(false);
    const [uploadCategory, setUploadCategory] = useState("");
    const [categoryFilter, setCategoryFilter] = useState(allCategoriesValue);
    const [query, setQuery] = useState("");
    const [debouncedQuery, setDebouncedQuery] = useState("");
    const [queueItems, setQueueItems] = useState<UploadQueueItem[]>([]);
    const [uploadedFiles, setUploadedFiles] = useState<ManagedUploadEntry[]>([]);
    const [availableCategories, setAvailableCategories] = useState<string[]>([]);
    const [categoryCounts, setCategoryCounts] = useState<Record<string, number>>({});
    const [filteredFileCount, setFilteredFileCount] = useState(0);
    const [totalManagedFiles, setTotalManagedFiles] = useState(0);
    const [rowsPerPage, setRowsPerPage] = useState<number>(10);
    const [currentPage, setCurrentPage] = useState<number>(1);
    const [isLoading, setIsLoading] = useState(false);
    const [isProcessingQueue, setIsProcessingQueue] = useState(false);
    const [isStopping, setIsStopping] = useState(false);
    const [isDragActive, setIsDragActive] = useState(false);
    const [deletingFiles, setDeletingFiles] = useState<Record<string, boolean>>({});
    const [deletingCategory, setDeletingCategory] = useState<string | null>(null);
    const [isDeletingAll, setIsDeletingAll] = useState(false);
    const [status, setStatus] = useState<StatusState>();
    const fileInputRef = useRef<HTMLInputElement | null>(null);
    const queueRef = useRef<UploadQueueItem[]>([]);
    const currentAbortRef = useRef<AbortController | null>(null);
    const libraryAbortRef = useRef<AbortController | null>(null);
    const latestLibraryRequestIdRef = useRef(0);
    const currentUploadIdRef = useRef<string | null>(null);
    const currentQueueItemIdRef = useRef<string | null>(null);
    const currentUploadCategoryRef = useRef<string | null>(null);
    const processingRef = useRef(false);
    const stopRequestedRef = useRef(false);
    const [hasLoadedLibraryMetadata, setHasLoadedLibraryMetadata] = useState(false);
    const hasLoadedLibraryMetadataRef = useRef(false);

    const normalizedQuery = debouncedQuery.trim().toLowerCase();

    const hasActiveQueue = queueItems.some(item => activeStatuses.includes(item.status));
    const dismissableQueueItemsCount = queueItems.filter(item => !activeStatuses.includes(item.status)).length;
    const totalPages = Math.max(1, Math.ceil(filteredFileCount / rowsPerPage));
    const currentPageSafe = Math.min(currentPage, totalPages);
    const pageStartIndex = (currentPageSafe - 1) * rowsPerPage;
    const setQueueState = (updater: (current: UploadQueueItem[]) => UploadQueueItem[]) => {
        const nextState = updater(queueRef.current);
        queueRef.current = nextState;
        setQueueItems(nextState);
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

    const dismissAllQueueItems = () => {
        setQueueState(current => current.filter(item => activeStatuses.includes(item.status)));
    };

    const queueStatusLabel = (statusValue: QueueItemStatus) => {
        switch (statusValue) {
            case "queued":
                return "Queued";
            case "uploading":
                return "Uploading";
            case "canceling":
                return "Stopping";
            case "completed":
                return "Completed";
            case "completedAfterStop":
                return "Completed before stop";
            case "failed":
                return "Failed";
            case "canceled":
                return "Canceled";
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

    const applyLibraryResponse = (
        response: Awaited<ReturnType<typeof listManagedUploadsApi>>,
        options?: { includeCategories?: boolean }
    ) => {
        startTransition(() => {
            setUploadedFiles(response.files);
            setFilteredFileCount(response.totalCount);
            if (options?.includeCategories !== false) {
                setAvailableCategories(sortCategories(response.categories));
                setCategoryCounts(response.categoryCounts);
                setTotalManagedFiles(typeof response.totalAllCount === "number" ? response.totalAllCount : 0);
                setHasLoadedLibraryMetadata(true);
                if (categoryFilter !== allCategoriesValue && !response.categories.includes(categoryFilter)) {
                    setCategoryFilter(allCategoriesValue);
                }
            }
        });
    };

    const loadFiles = async (options?: {
        suppressErrors?: boolean;
        includeCategories?: boolean;
        page?: number;
        pageSize?: number;
        category?: string | null;
        query?: string;
    }) => {
        const requestId = latestLibraryRequestIdRef.current + 1;
        latestLibraryRequestIdRef.current = requestId;
        libraryAbortRef.current?.abort();
        const controller = new AbortController();
        libraryAbortRef.current = controller;

        const requestCategory =
            options?.category === undefined
                ? categoryFilter !== allCategoriesValue
                    ? categoryFilter
                    : undefined
                : options.category || undefined;
        const requestQuery = options?.query ?? debouncedQuery.trim();
        const includeCategories = options?.includeCategories ?? !hasLoadedLibraryMetadataRef.current;

        setIsLoading(true);
        try {
            const response = await listManagedUploadsApi({
                category: requestCategory,
                query: requestQuery,
                page: options?.page ?? currentPageSafe,
                pageSize: options?.pageSize ?? rowsPerPage,
                includeCategories,
                signal: controller.signal
            });
            if (requestId !== latestLibraryRequestIdRef.current) {
                return null;
            }
            applyLibraryResponse(response, { includeCategories });
            return response;
        } catch (error) {
            if (controller.signal.aborted || (error instanceof DOMException && error.name === "AbortError")) {
                return null;
            }
            if (!options?.suppressErrors) {
                setStatus({
                    tone: "error",
                    message: error instanceof Error ? error.message : "Unable to load uploaded files."
                });
            }
            return null;
        } finally {
            if (requestId === latestLibraryRequestIdRef.current) {
                setIsLoading(false);
                libraryAbortRef.current = null;
            }
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
        const completedCount = queueRef.current.filter(item => ["completed", "completedAfterStop"].includes(item.status)).length;
        const failedCount = queueRef.current.filter(item => item.status === "failed").length;
        const canceledCount = queueRef.current.filter(item => item.status === "canceled").length;
        return { completedCount, failedCount, canceledCount };
    };

    const setStopSummary = () => {
        const { completedCount, failedCount, canceledCount } = getQueueSummary();
        setStatus({
            tone: canceledCount > 0 ? "warning" : "success",
            message: `Stop processed. ${completedCount} completed, ${failedCount} failed, ${canceledCount} canceled.`
        });
    };

    const mergeUploadedEntry = (entry: ManagedUploadCreatedEntry) => {
        const matchesCurrentFilters = matchesLibraryFilters(entry, categoryFilter, normalizedQuery);

        startTransition(() => {
            setAvailableCategories(current => sortCategories([...current, entry.category]));
            setCategoryCounts(current => {
                const nextCounts = { ...current };
                const currentCount = nextCounts[entry.category] ?? 0;
                nextCounts[entry.category] = entry.replacedExisting ? Math.max(1, currentCount || 1) : currentCount + 1;
                return nextCounts;
            });
            setHasLoadedLibraryMetadata(true);
            if (!entry.replacedExisting) {
                setTotalManagedFiles(current => current + 1);
            }
            if (matchesCurrentFilters && !entry.replacedExisting) {
                setFilteredFileCount(current => current + 1);
            }
            if (matchesCurrentFilters && currentPageSafe === 1) {
                setUploadedFiles(current => {
                    const remainingFiles = current.filter(
                        file => !(file.category === entry.category && file.filename === entry.filename)
                    );
                    return [entry, ...remainingFiles].slice(0, rowsPerPage);
                });
            }
        });
    };

    const reconcileAbortedUpload = async (item: UploadQueueItem) => {
        const response = await listManagedUploadsApi({
            category: item.category,
            query: item.filename,
            page: 1,
            pageSize: 5,
            includeCategories: false
        });
        const fileFinished = response.files.some(file => file.category === item.category && file.filename === item.filename);
        updateQueueItem(item.id, {
            status: fileFinished ? "completedAfterStop" : "canceled",
            message: fileFinished ? "Upload finished before stop completed." : "Upload canceled."
        });
    };

    const runQueue = async () => {
        if (processingRef.current) {
            return;
        }

        processingRef.current = true;
        setIsProcessingQueue(true);
        let shouldRevalidateLibrary = false;
        try {
            while (true) {
                const nextItem = queueRef.current.find(item => item.status === "queued");
                if (!nextItem) {
                    break;
                }

                if (stopRequestedRef.current) {
                    markQueuedItemsCanceled("Upload canceled.");
                    break;
                }

                const abortController = new AbortController();
                currentAbortRef.current = abortController;
                currentUploadIdRef.current = nextItem.uploadId;
                currentQueueItemIdRef.current = nextItem.id;
                currentUploadCategoryRef.current = nextItem.category;
                updateQueueItem(nextItem.id, {
                    status: "uploading",
                    message: `Uploading to ${nextItem.category}`
                });

                const formData = new FormData();
                formData.append("category", nextItem.category);
                formData.append("files", nextItem.file, nextItem.filename);

                try {
                    const response = await uploadManagedFilesApi(formData, {
                        signal: abortController.signal,
                        uploadId: nextItem.uploadId
                    });
                    const failedUpload = response.failedFiles.find(
                        file => file.category === nextItem.category && file.filename === nextItem.filename
                    );
                    if (failedUpload) {
                        updateQueueItem(nextItem.id, {
                            status: failedUpload.message === "Upload canceled" ? "canceled" : "failed",
                            message: failedUpload.message
                        });
                    } else {
                        const uploadedEntry = response.uploadedFiles?.find(
                            file => file.category === nextItem.category && file.filename === nextItem.filename
                        );
                        updateQueueItem(nextItem.id, {
                            status: "completed",
                            message: `Stored in ${nextItem.category}`
                        });
                        if (uploadedEntry) {
                            mergeUploadedEntry(uploadedEntry);
                        }
                        shouldRevalidateLibrary = true;
                    }
                } catch (error) {
                    const isAbortError =
                        abortController.signal.aborted || (error instanceof DOMException && error.name === "AbortError");

                    if (isAbortError) {
                        await reconcileAbortedUpload(nextItem);
                        shouldRevalidateLibrary = true;
                    } else {
                        updateQueueItem(nextItem.id, {
                            status: stopRequestedRef.current ? "canceled" : "failed",
                            message: error instanceof Error ? error.message : "Unexpected upload failure."
                        });
                    }
                } finally {
                    currentAbortRef.current = null;
                    currentUploadIdRef.current = null;
                    currentQueueItemIdRef.current = null;
                    currentUploadCategoryRef.current = null;
                }

                if (stopRequestedRef.current) {
                    markQueuedItemsCanceled("Upload canceled.");
                    break;
                }
            }
        } finally {
            processingRef.current = false;
            setIsProcessingQueue(false);
            if (shouldRevalidateLibrary) {
                await loadFiles({ suppressErrors: true, includeCategories: false });
            }
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
                message: "Wait for the current stop request to finish before adding more files."
            });
            return;
        }

        const categoryResult = validateCategory(uploadCategory);
        if (!categoryResult.ok) {
            setStatus({
                tone: "warning",
                message: categoryResult.message || "Category is required."
            });
            resetFileInput();
            return;
        }

        const activeFileKeys = new Set(
            queueRef.current
                .filter(item => activeStatuses.includes(item.status))
                .map(item => `${item.category}:${item.filename.toLowerCase()}`)
        );
        const selectionKeys = new Set<string>();
        const nextItems: UploadQueueItem[] = [];
        const issues: string[] = [];

        for (const file of files) {
            const filename = file.name;
            const filenameKey = `${categoryResult.normalized}:${filename.toLowerCase()}`;
            if (!acceptedExtensions.has(getFileExtension(filename))) {
                issues.push(`Unsupported file type: ${filename}`);
                continue;
            }
            if (activeFileKeys.has(filenameKey) || selectionKeys.has(filenameKey)) {
                issues.push(`Already queued for ${categoryResult.normalized}: ${filename}`);
                continue;
            }

            selectionKeys.add(filenameKey);
            nextItems.push({
                id: createUniqueId(),
                uploadId: createUniqueId(),
                category: categoryResult.normalized,
                file,
                filename,
                status: "queued",
                message: `Queued for ${categoryResult.normalized}`
            });
        }

        if (nextItems.length > 0) {
            setQueueState(current => [...current, ...nextItems]);
            setUploadCategory(categoryResult.normalized);
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
            message: "Stopping the current upload queue..."
        });

        const currentItemId = currentQueueItemIdRef.current;
        if (currentItemId) {
            updateQueueItem(currentItemId, {
                status: "canceling",
                message: "Stopping upload"
            });
        }

        const activeUploadId = currentUploadIdRef.current;
        const activeCategory = currentUploadCategoryRef.current;
        if (activeUploadId && activeCategory) {
            try {
                await cancelManagedUploadApi(activeCategory, activeUploadId);
            } catch (error) {
                setStatus({
                    tone: "warning",
                    message: error instanceof Error ? error.message : "Stop requested."
                });
            }
        }

        currentAbortRef.current?.abort();

        if (!currentItemId) {
            markQueuedItemsCanceled("Upload canceled.");
            setStopSummary();
            stopRequestedRef.current = false;
            setIsStopping(false);
        }
    };

    const handleDeleteFile = async (file: ManagedUploadEntry) => {
        const key = `${file.category}:${file.filename}`;
        setDeletingFiles(current => ({ ...current, [key]: true }));
        setStatus(undefined);
        try {
            const response = await deleteManagedUploadedFileApi(file.category, file.filename);
            setStatus({
                tone: "success",
                message: response.message || `Deleted ${file.filename}.`
            });
            await loadFiles({ includeCategories: true });
        } catch (error) {
            setStatus({
                tone: "error",
                message: error instanceof Error ? error.message : "Error deleting file."
            });
        } finally {
            setDeletingFiles(current => {
                const nextState = { ...current };
                delete nextState[key];
                return nextState;
            });
        }
    };

    const handleDeleteCategory = async () => {
        if (categoryFilter === allCategoriesValue || deletingCategory || hasActiveQueue || isStopping) {
            return;
        }
        const count = categoryCounts[categoryFilter] ?? 0;
        if (count === 0 || !window.confirm(`Delete all ${count} uploaded files in "${categoryFilter}"?`)) {
            return;
        }

        setDeletingCategory(categoryFilter);
        setStatus(undefined);
        try {
            const response = await deleteManagedUploadedFilesApi(categoryFilter);
            setStatus({
                tone: response.failedFiles.length > 0 ? "warning" : "success",
                message: response.message || `Deleted ${count} files from ${categoryFilter}.`
            });
            await loadFiles({ includeCategories: true });
        } catch (error) {
            setStatus({
                tone: "error",
                message: error instanceof Error ? error.message : "Error deleting category files."
            });
        } finally {
            setDeletingCategory(null);
        }
    };

    const handleDeleteAll = async () => {
        if (totalManagedFiles === 0 || isDeletingAll || hasActiveQueue || isStopping) {
            return;
        }
        if (!window.confirm(`Delete all ${totalManagedFiles} uploaded files across all categories?`)) {
            return;
        }

        setIsDeletingAll(true);
        setStatus(undefined);
        try {
            const response = await deleteManagedUploadedFilesApi();
            setStatus({
                tone: response.failedFiles.length > 0 ? "warning" : "success",
                message: response.message || `Deleted ${totalManagedFiles} uploaded files.`
            });
            await loadFiles({ includeCategories: true });
        } catch (error) {
            setStatus({
                tone: "error",
                message: error instanceof Error ? error.message : "Error deleting uploaded files."
            });
        } finally {
            setIsDeletingAll(false);
        }
    };

    const handleUnlock = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (password === INTERNAL_TOOLS_PASSWORD) {
            window.sessionStorage.setItem(INTERNAL_TOOLS_SESSION_KEY, "true");
            setIsAuthenticated(true);
            setPassword("");
            setErrorMessage("");
            setIsPasswordVisible(false);
            return;
        }
        setErrorMessage("Incorrect password. Please try again.");
    };

    const handleLockPage = () => {
        if (hasActiveQueue || isStopping) {
            setStatus({
                tone: "warning",
                message: "Stop the active upload queue before locking the page."
            });
            return;
        }
        window.sessionStorage.removeItem(INTERNAL_TOOLS_SESSION_KEY);
        setIsAuthenticated(false);
        setPassword("");
        setErrorMessage("");
        setIsPasswordVisible(false);
        setStatus(undefined);
        setQuery("");
        setDebouncedQuery("");
        setUploadCategory("");
        setCategoryFilter(allCategoriesValue);
        setQueueState(() => []);
        setUploadedFiles([]);
        setAvailableCategories([]);
        setCategoryCounts({});
        setFilteredFileCount(0);
        setTotalManagedFiles(0);
        setCurrentPage(1);
        setHasLoadedLibraryMetadata(false);
        libraryAbortRef.current?.abort();
    };

    useEffect(() => {
        queueRef.current = queueItems;
    }, [queueItems]);

    useEffect(() => {
        hasLoadedLibraryMetadataRef.current = hasLoadedLibraryMetadata;
    }, [hasLoadedLibraryMetadata]);

    useEffect(() => {
        const timeoutId = window.setTimeout(() => {
            setDebouncedQuery(query.trim());
        }, 250);
        return () => window.clearTimeout(timeoutId);
    }, [query]);

    useEffect(() => {
        if (!isAuthenticated) {
            return;
        }
        void loadFiles();
    }, [isAuthenticated, categoryFilter, debouncedQuery, currentPage, rowsPerPage]);

    useEffect(() => {
        if (currentPage > totalPages) {
            setCurrentPage(totalPages);
        }
    }, [currentPage, totalPages]);

    useEffect(() => {
        if (!isAuthenticated) {
            return;
        }
        if (queueItems.some(item => item.status === "queued") && !processingRef.current) {
            void runQueue();
        }
    }, [queueItems, isAuthenticated]);

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
    }, [hasActiveQueue, isStopping]);

    useEffect(() => {
        return () => {
            const activeUploadId = currentUploadIdRef.current;
            const activeCategory = currentUploadCategoryRef.current;
            if (activeUploadId && activeCategory) {
                void cancelManagedUploadApi(activeCategory, activeUploadId).catch(() => undefined);
            }
            currentAbortRef.current?.abort();
            libraryAbortRef.current?.abort();
        };
    }, []);

    const handleInputChange = (event: ChangeEvent<HTMLInputElement>) => {
        enqueueFiles(Array.from(event.target.files ?? []));
    };

    const handleDrop = (event: DragEvent<HTMLDivElement>) => {
        event.preventDefault();
        setIsDragActive(false);
        enqueueFiles(Array.from(event.dataTransfer.files ?? []));
    };

    return (
        <main className={styles.page}>
            <Helmet>
                <title>Upload Files</title>
            </Helmet>

            <div className={styles.glowOne} aria-hidden="true" />
            <div className={styles.glowTwo} aria-hidden="true" />

            <section className={styles.shell}>
                <header className={styles.header}>
                    <div>
                        <span className={styles.badge}>Internal tool</span>
                        <h1 className={styles.title}>Upload Files</h1>
                        <p className={styles.subtitle}>Manage shared uploads across chatbot categories.</p>
                    </div>
                    <div className={styles.headerActions}>
                        <span className={styles.countPill}>
                            {isAuthenticated ? `${totalManagedFiles} managed files` : "Protected page"}
                        </span>
                        {isAuthenticated ? (
                            <>
                                <Link className={styles.secondaryButton} to="/chatbots">
                                    Back to directory
                                </Link>
                                <Link className={styles.secondaryButton} to="/public-test-users">
                                    Public-test users
                                </Link>
                                <button className={styles.secondaryButton} type="button" onClick={handleLockPage}>
                                    Lock page
                                </button>
                            </>
                        ) : null}
                    </div>
                </header>

                <section className={`${styles.panel} ${!isAuthenticated ? styles.panelLocked : ""}`}>
                    {!isAuthenticated ? (
                        <div className={styles.accessState}>
                            <div className={styles.accessHeader}>
                                <span className={styles.badge}>Protected</span>
                                <h2 className={styles.sectionTitle}>Unlock upload manager</h2>
                            </div>
                            <form className={styles.form} onSubmit={handleUnlock} autoComplete="off">
                                <label className={styles.label} htmlFor="upload-manager-password">
                                    Password
                                </label>
                                <div className={styles.inputWrap}>
                                    <input
                                        id="upload-manager-password"
                                        className={`${styles.input} ${!isPasswordVisible ? styles.maskedInput : ""}`}
                                        type="text"
                                        name="upload-manager-access-code"
                                        value={password}
                                        onChange={event => {
                                            setPassword(event.target.value);
                                            setErrorMessage("");
                                        }}
                                        placeholder="Enter password"
                                        autoComplete="off"
                                        spellCheck={false}
                                        autoCapitalize="none"
                                        autoCorrect="off"
                                    />
                                    <button
                                        className={styles.visibilityToggle}
                                        type="button"
                                        aria-label={isPasswordVisible ? "Hide password" : "Show password"}
                                        aria-pressed={isPasswordVisible}
                                        onClick={() => setIsPasswordVisible(current => !current)}
                                    >
                                        <Icon iconName={isPasswordVisible ? "Hide3" : "RedEye"} />
                                    </button>
                                </div>
                                <button className={styles.primaryButton} type="submit">
                                    Unlock upload manager
                                </button>
                                <p className={styles.errorMessage}>{errorMessage}</p>
                            </form>
                        </div>
                    ) : (
                        <>
                            <div className={styles.toolbar}>
                                <div className={styles.field}>
                                    <label className={styles.label} htmlFor="upload-category">
                                        Upload category
                                    </label>
                                    <input
                                        id="upload-category"
                                        className={styles.input}
                                        value={uploadCategory}
                                        onChange={event => setUploadCategory(normalizeCategory(event.target.value))}
                                        placeholder="e.g. sartorius"
                                        spellCheck={false}
                                        autoCapitalize="none"
                                        autoCorrect="off"
                                    />
                                </div>
                                <div className={styles.toolbarActions}>
                                    <button className={styles.primaryButton} type="button" disabled={isStopping} onClick={() => fileInputRef.current?.click()}>
                                        <ArrowUpload24Regular />
                                        <span>Choose files</span>
                                    </button>
                                    <button
                                        className={styles.secondaryButton}
                                        type="button"
                                        disabled={isProcessingQueue || isStopping}
                                        onClick={() => void loadFiles({ includeCategories: true })}
                                    >
                                        <ArrowClockwise24Regular />
                                        <span>Refresh</span>
                                    </button>
                                    {hasActiveQueue ? (
                                        <button className={styles.secondaryButton} type="button" disabled={isStopping} onClick={() => void requestStopUploads()}>
                                            <Stop24Regular />
                                            <span>{isStopping ? "Stopping" : "Stop upload"}</span>
                                        </button>
                                    ) : null}
                                </div>
                            </div>

                            <input
                                accept={acceptedFileTypes}
                                className={styles.hiddenInput}
                                multiple
                                onChange={handleInputChange}
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
                                onDrop={handleDrop}
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
                                <p className={styles.dropzoneTitle}>Drop files here or click to browse</p>
                                <p className={styles.dropzoneHint}>
                                    Files are stored directly under <code>content/&lt;category&gt;/</code>.
                                </p>
                                <p className={styles.dropzoneHint}>Set the category first. You can add more files while the queue is uploading.</p>
                            </div>

                            {(isProcessingQueue || status) && (
                                <div
                                    className={`${styles.status} ${status ? styles[`status${status.tone[0].toUpperCase()}${status.tone.slice(1)}`] : styles.statusNeutral}`}
                                    role="status"
                                >
                                    {isProcessingQueue && !status ? "Uploading queue..." : status?.message}
                                </div>
                            )}

                            <section className={styles.section}>
                                <div className={styles.sectionHeader}>
                                    <div>
                                        <p className={styles.sectionLabel}>Queue</p>
                                        <h2 className={styles.sectionTitle}>Current upload queue</h2>
                                    </div>
                                    <div className={styles.sectionHeaderActions}>
                                        {dismissableQueueItemsCount > 1 ? (
                                            <button className={styles.secondaryButton} type="button" onClick={dismissAllQueueItems}>
                                                Dismiss all finished
                                            </button>
                                        ) : null}
                                        <span className={styles.fileCount}>{queueItems.length}</span>
                                    </div>
                                </div>
                                <div className={styles.list}>
                                    {queueItems.length === 0 ? (
                                        <div className={styles.emptyState}>
                                            <Document24Regular />
                                            <div>
                                                <p className={styles.emptyStateTitle}>No files queued</p>
                                                <p className={styles.emptyStateDescription}>Choose one or more files to start the upload queue.</p>
                                            </div>
                                        </div>
                                    ) : (
                                        queueItems.map(item => (
                                            <div className={styles.fileRow} key={item.id}>
                                                <div className={styles.fileMeta}>
                                                    <div className={styles.fileBadge}>{formatExtension(item.filename)}</div>
                                                    <div className={styles.fileDetails}>
                                                        <span className={styles.fileName}>{item.filename}</span>
                                                        <span className={styles.fileSubtext}>{item.message ?? queueStatusLabel(item.status)}</span>
                                                    </div>
                                                </div>
                                                <div className={styles.rowActions}>
                                                    <span className={styles.categoryChip}>{item.category}</span>
                                                    <span className={`${styles.queueStatus} ${queueStatusClass(item.status)}`}>
                                                        {queueStatusLabel(item.status)}
                                                    </span>
                                                    {!activeStatuses.includes(item.status) ? (
                                                        <button className={styles.secondaryButton} type="button" onClick={() => removeQueueItem(item.id)}>
                                                            Dismiss
                                                        </button>
                                                    ) : null}
                                                </div>
                                            </div>
                                        ))
                                    )}
                                </div>
                            </section>

                            <section className={styles.section}>
                                <div className={styles.sectionHeader}>
                                    <div>
                                        <p className={styles.sectionLabel}>Library</p>
                                        <h2 className={styles.sectionTitle}>Managed uploads</h2>
                                    </div>
                                    <div className={styles.sectionHeaderActions}>
                                        <div className={styles.paginationMeta}>
                                            <label className={styles.paginationLabel} htmlFor="rows-per-page">
                                                Rows
                                            </label>
                                            <select
                                                id="rows-per-page"
                                                className={styles.paginationSelect}
                                                value={rowsPerPage}
                                                onChange={event => {
                                                    setRowsPerPage(Number(event.target.value));
                                                    setCurrentPage(1);
                                                }}
                                            >
                                                {pageSizeOptions.map(option => (
                                                    <option key={option} value={option}>
                                                        {option}
                                                    </option>
                                                ))}
                                            </select>
                                        </div>
                                        <span className={styles.fileCount}>{filteredFileCount}</span>
                                    </div>
                                </div>

                                <div className={styles.filters}>
                                    <div className={styles.field}>
                                        <label className={styles.label} htmlFor="category-filter">
                                            View by category
                                        </label>
                                        <select
                                            id="category-filter"
                                            className={styles.select}
                                            value={categoryFilter}
                                            onChange={event => {
                                                setCategoryFilter(event.target.value);
                                                setCurrentPage(1);
                                            }}
                                        >
                                            <option value={allCategoriesValue}>All categories</option>
                                            {availableCategories.map(category => (
                                                <option key={category} value={category}>
                                                    {category}
                                                </option>
                                            ))}
                                        </select>
                                    </div>
                                    <div className={styles.field}>
                                        <label className={styles.label} htmlFor="file-search">
                                            Search files
                                        </label>
                                        <input
                                            id="file-search"
                                            className={styles.input}
                                            type="search"
                                            value={query}
                                            onChange={event => {
                                                setQuery(event.target.value);
                                                setCurrentPage(1);
                                            }}
                                            placeholder="Search by filename or category"
                                        />
                                    </div>
                                    <div className={styles.bulkActions}>
                                        {categoryFilter !== allCategoriesValue ? (
                                            <button
                                                className={styles.secondaryButton}
                                                type="button"
                                                disabled={Boolean(deletingCategory) || isDeletingAll || hasActiveQueue || isStopping}
                                                onClick={() => void handleDeleteCategory()}
                                            >
                                                <Delete24Regular />
                                                <span>{deletingCategory === categoryFilter ? "Deleting category" : "Delete category"}</span>
                                            </button>
                                        ) : null}
                                        <button
                                            className={styles.secondaryButton}
                                            type="button"
                                            disabled={isDeletingAll || hasActiveQueue || isStopping}
                                            onClick={() => void handleDeleteAll()}
                                        >
                                            <Delete24Regular />
                                            <span>{isDeletingAll ? "Deleting all" : "Delete all uploads"}</span>
                                        </button>
                                    </div>
                                </div>

                                <div className={styles.list}>
                                    {isLoading ? <p className={styles.infoMessage}>Loading uploaded files...</p> : null}
                                    {!isLoading && filteredFileCount === 0 ? (
                                        <div className={styles.emptyState}>
                                            <Document24Regular />
                                            <div>
                                                <p className={styles.emptyStateTitle}>No uploaded files found</p>
                                                <p className={styles.emptyStateDescription}>Try another category filter or upload a new file.</p>
                                            </div>
                                        </div>
                                    ) : null}
                                    {!isLoading &&
                                        uploadedFiles.map(file => {
                                            const key = `${file.category}:${file.filename}`;
                                            return (
                                                <div className={styles.fileRow} key={key}>
                                                    <div className={styles.fileMeta}>
                                                        <div className={styles.fileBadge}>{formatExtension(file.filename)}</div>
                                                        <div className={styles.fileDetails}>
                                                            <span className={styles.fileName}>{file.filename}</span>
                                                            <span className={styles.fileSubtext}>{formatTimestamp(file.uploaded_at)}</span>
                                                        </div>
                                                    </div>
                                                    <div className={styles.rowActions}>
                                                        <span className={styles.categoryChip}>{file.category}</span>
                                                        <button
                                                            className={styles.inlineDangerButton}
                                                            type="button"
                                                            disabled={Boolean(deletingFiles[key]) || isDeletingAll || hasActiveQueue || isStopping}
                                                            onClick={() => void handleDeleteFile(file)}
                                                        >
                                                            <Delete24Regular />
                                                            <span>{deletingFiles[key] ? "Deleting" : "Delete"}</span>
                                                        </button>
                                                    </div>
                                                </div>
                                            );
                                        })}
                                </div>
                                {filteredFileCount > 0 ? (
                                    <div className={styles.paginationBar}>
                                        <span className={styles.paginationSummary}>
                                            Showing {pageStartIndex + 1}-{Math.min(pageStartIndex + uploadedFiles.length, filteredFileCount)} of {filteredFileCount}
                                        </span>
                                        <div className={styles.paginationControls}>
                                            <button
                                                className={styles.secondaryButton}
                                                type="button"
                                                disabled={currentPageSafe <= 1}
                                                onClick={() => setCurrentPage(page => Math.max(1, page - 1))}
                                            >
                                                Previous
                                            </button>
                                            <span className={styles.paginationPage}>
                                                Page {currentPageSafe} of {totalPages}
                                            </span>
                                            <button
                                                className={styles.secondaryButton}
                                                type="button"
                                                disabled={currentPageSafe >= totalPages}
                                                onClick={() => setCurrentPage(page => Math.min(totalPages, page + 1))}
                                            >
                                                Next
                                            </button>
                                        </div>
                                    </div>
                                ) : null}
                            </section>
                        </>
                    )}
                </section>
            </section>
        </main>
    );
};

export default UploadFilesPage;
