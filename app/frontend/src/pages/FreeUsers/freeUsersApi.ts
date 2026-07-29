export type FreeAdminUser = {
    displayName: string;
    email: string;
    createdAt: string;
    updatedAt: string;
    uploadCount: number;
    uploadedFiles: string[];
    // Free Bot access is a 30-day window. Expired accounts are kept (their email can no longer be
    // re-registered) and listed in the archive tab; the backend owns the expiry math.
    expiresAt: string;
    isExpired: boolean;
    daysRemaining: number;
    daysExpired: number;
};

export type FreeAdminUsersResponse = {
    users: FreeAdminUser[];
};

type FreeDeleteUserResponse = {
    message?: string;
    deletedUploadCount?: number;
    failedUploads?: { filename?: string; message?: string }[];
};

type FreeResetPasswordResponse = {
    message?: string;
    email?: string;
    updatedAt?: string;
};

type FreeReactivateUserResponse = {
    message?: string;
    email?: string;
    updatedAt?: string;
    expiresAt?: string;
    isExpired?: boolean;
    daysRemaining?: number;
    daysExpired?: number;
};

async function parseErrorMessage(response: Response, fallbackMessage: string): Promise<never> {
    const errorBody = (await response.json().catch(() => null)) as { message?: string } | null;
    throw new Error(errorBody?.message || fallbackMessage);
}

export async function listFreeUsersApi(signal?: AbortSignal): Promise<FreeAdminUsersResponse> {
    const response = await fetch("/free-admin/users", {
        method: "GET",
        signal
    });

    if (!response.ok) {
        await parseErrorMessage(response, `Listing nerilio users failed: ${response.statusText}`);
    }

    return (await response.json()) as FreeAdminUsersResponse;
}

export async function deleteFreeUserApi(email: string): Promise<FreeDeleteUserResponse> {
    const response = await fetch(`/free-admin/users/${encodeURIComponent(email)}`, {
        method: "DELETE"
    });

    if (!response.ok) {
        await parseErrorMessage(response, `Deleting nerilio user failed: ${response.statusText}`);
    }

    return (await response.json()) as FreeDeleteUserResponse;
}

export async function reactivateFreeUserApi(email: string): Promise<FreeReactivateUserResponse> {
    const response = await fetch(`/free-admin/users/${encodeURIComponent(email)}/reactivate`, {
        method: "POST"
    });

    if (!response.ok) {
        await parseErrorMessage(response, `Reactivating nerilio user failed: ${response.statusText}`);
    }

    return (await response.json()) as FreeReactivateUserResponse;
}

export async function resetFreeUserPasswordApi(
    email: string,
    password: string,
    confirmPassword: string
): Promise<FreeResetPasswordResponse> {
    const response = await fetch(`/free-admin/users/${encodeURIComponent(email)}/password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password, confirmPassword })
    });

    if (!response.ok) {
        await parseErrorMessage(response, `Resetting nerilio user password failed: ${response.statusText}`);
    }

    return (await response.json()) as FreeResetPasswordResponse;
}

