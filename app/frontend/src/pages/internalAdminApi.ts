export const INTERNAL_ADMIN_REQUIRED_MESSAGE = "Internal admin authentication required.";

export type InternalAdminSessionResponse = {
    authenticated: boolean;
    message?: string;
};

async function parseErrorMessage(response: Response, fallbackMessage: string): Promise<never> {
    const errorBody = (await response.json().catch(() => null)) as { message?: string } | null;
    throw new Error(errorBody?.message || fallbackMessage);
}

export async function getInternalAdminSessionApi(signal?: AbortSignal): Promise<InternalAdminSessionResponse> {
    const response = await fetch("/internal-admin/session", {
        method: "GET",
        signal
    });

    if (!response.ok) {
        await parseErrorMessage(response, `Checking internal admin session failed: ${response.statusText}`);
    }

    return (await response.json()) as InternalAdminSessionResponse;
}

export async function loginInternalAdminApi(password: string): Promise<InternalAdminSessionResponse> {
    const response = await fetch("/internal-admin/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password })
    });

    if (!response.ok) {
        await parseErrorMessage(response, `Signing in failed: ${response.statusText}`);
    }

    return (await response.json()) as InternalAdminSessionResponse;
}

export async function logoutInternalAdminApi(): Promise<InternalAdminSessionResponse> {
    const response = await fetch("/internal-admin/logout", {
        method: "POST"
    });

    if (!response.ok) {
        await parseErrorMessage(response, `Signing out failed: ${response.statusText}`);
    }

    return (await response.json()) as InternalAdminSessionResponse;
}
