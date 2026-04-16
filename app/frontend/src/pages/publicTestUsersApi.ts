export type PublicTestAdminUser = {
    displayName: string;
    email: string;
    createdAt: string;
    updatedAt: string;
    uploadCount: number;
    uploadedFiles: string[];
};

export type PublicTestAdminUsersResponse = {
    users: PublicTestAdminUser[];
};

type PublicTestDeleteUserResponse = {
    message?: string;
    deletedUploadCount?: number;
    failedUploads?: { filename?: string; message?: string }[];
};

type PublicTestResetPasswordResponse = {
    message?: string;
    email?: string;
    updatedAt?: string;
};

async function parseErrorMessage(response: Response, fallbackMessage: string): Promise<never> {
    const errorBody = (await response.json().catch(() => null)) as { message?: string } | null;
    throw new Error(errorBody?.message || fallbackMessage);
}

export async function listPublicTestUsersApi(signal?: AbortSignal): Promise<PublicTestAdminUsersResponse> {
    const response = await fetch("/free-admin/users", {
        method: "GET",
        signal
    });

    if (!response.ok) {
        await parseErrorMessage(response, `Listing Nerilio Bot users failed: ${response.statusText}`);
    }

    return (await response.json()) as PublicTestAdminUsersResponse;
}

export async function deletePublicTestUserApi(email: string): Promise<PublicTestDeleteUserResponse> {
    const response = await fetch(`/free-admin/users/${encodeURIComponent(email)}`, {
        method: "DELETE"
    });

    if (!response.ok) {
        await parseErrorMessage(response, `Deleting Nerilio Bot user failed: ${response.statusText}`);
    }

    return (await response.json()) as PublicTestDeleteUserResponse;
}

export async function resetPublicTestUserPasswordApi(
    email: string,
    password: string,
    confirmPassword: string
): Promise<PublicTestResetPasswordResponse> {
    const response = await fetch(`/free-admin/users/${encodeURIComponent(email)}/password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password, confirmPassword })
    });

    if (!response.ok) {
        await parseErrorMessage(response, `Resetting Nerilio Bot user password failed: ${response.statusText}`);
    }

    return (await response.json()) as PublicTestResetPasswordResponse;
}

