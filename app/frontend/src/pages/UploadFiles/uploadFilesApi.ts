export type ManagedUploadEntry = {
    category: string;
    filename: string;
    storage_url: string;
    uploaded_at?: string | null;
};

export type ManagedUploadCreatedEntry = ManagedUploadEntry & {
    replacedExisting?: boolean;
};

export type ManagedUploadFailure = {
    category: string;
    filename: string;
    message: string;
};

export type ManagedUploadListResponse = {
    files: ManagedUploadEntry[];
    categories: string[];
    categoryCounts: Record<string, number>;
    totalCount: number;
    totalAllCount?: number | null;
    page: number;
    pageSize: number;
    totalPages: number;
};

export type ManagedUploadMutationResponse = {
    message?: string;
    uploadedFiles?: ManagedUploadCreatedEntry[];
    deletedFiles?: ManagedUploadEntry[];
    failedFiles: ManagedUploadFailure[];
};

async function parseErrorMessage(response: Response, fallbackMessage: string): Promise<never> {
    const errorBody = (await response.json().catch(() => null)) as { message?: string } | null;
    throw new Error(errorBody?.message || fallbackMessage);
}

export async function listManagedUploadsApi(options?: {
    category?: string;
    query?: string;
    page?: number;
    pageSize?: number;
    includeCategories?: boolean;
    signal?: AbortSignal;
}): Promise<ManagedUploadListResponse> {
    const params = new URLSearchParams();
    if (options?.category) {
        params.set("category", options.category);
    }
    if (options?.query) {
        params.set("query", options.query);
    }
    if (options?.page) {
        params.set("page", String(options.page));
    }
    if (options?.pageSize) {
        params.set("pageSize", String(options.pageSize));
    }
    if (options?.includeCategories === false) {
        params.set("includeCategories", "false");
    }

    const response = await fetch(`/managed_uploads${params.size > 0 ? `?${params.toString()}` : ""}`, {
        method: "GET",
        signal: options?.signal
    });

    if (!response.ok) {
        await parseErrorMessage(response, `Listing files failed: ${response.statusText}`);
    }

    return (await response.json()) as ManagedUploadListResponse;
}

export async function uploadManagedFilesApi(
    request: FormData,
    options?: { signal?: AbortSignal; uploadId?: string }
): Promise<ManagedUploadMutationResponse> {
    const headers: Record<string, string> = {};
    if (options?.uploadId) {
        headers["X-Upload-Id"] = options.uploadId;
    }

    const response = await fetch("/managed_uploads", {
        method: "POST",
        body: request,
        headers,
        signal: options?.signal
    });

    if (!response.ok) {
        await parseErrorMessage(response, `Uploading files failed: ${response.statusText}`);
    }

    return (await response.json()) as ManagedUploadMutationResponse;
}

export async function cancelManagedUploadApi(category: string, uploadId: string): Promise<{ message?: string }> {
    const response = await fetch(
        `/managed_uploads/cancel/${encodeURIComponent(uploadId)}?${new URLSearchParams({ category }).toString()}`,
        {
            method: "POST"
        }
    );

    if (!response.ok) {
        await parseErrorMessage(response, `Stopping upload failed: ${response.statusText}`);
    }

    return (await response.json()) as { message?: string };
}

export async function deleteManagedUploadedFileApi(category: string, filename: string): Promise<{ message?: string }> {
    const response = await fetch(
        `/managed_uploads/${encodeURIComponent(filename)}?${new URLSearchParams({ category }).toString()}`,
        {
            method: "DELETE"
        }
    );

    if (!response.ok) {
        await parseErrorMessage(response, `Deleting file failed: ${response.statusText}`);
    }

    return (await response.json()) as { message?: string };
}

export async function deleteManagedUploadedFilesApi(category?: string): Promise<ManagedUploadMutationResponse> {
    const params = new URLSearchParams();
    if (category) {
        params.set("category", category);
    }

    const response = await fetch(`/managed_uploads${params.size > 0 ? `?${params.toString()}` : ""}`, {
        method: "DELETE"
    });

    if (!response.ok) {
        await parseErrorMessage(response, `Deleting files failed: ${response.statusText}`);
    }

    return (await response.json()) as ManagedUploadMutationResponse;
}
