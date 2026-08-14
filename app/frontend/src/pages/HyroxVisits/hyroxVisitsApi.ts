// Admin-gated client for the HYROX assessment visit log. The session cookie rides along
// automatically (same shell session as the other /admin tabs).

// Sentinel month meaning "every month at once"; matches ALL_MONTHS on the backend.
export const ALL_MONTHS = "all";

export type HyroxVisitMonth = {
    month: string;
    totalCount: number;
};

export type HyroxVisitRow = {
    userId: string;
    timestamp: string;
};

export type HyroxVisitsResponse = {
    months: HyroxVisitMonth[];
    selectedMonth: string;
    rowCount: number;
    totalCount: number;
    rows: HyroxVisitRow[];
    previewLimit: number;
    previewTruncated: boolean;
};

async function parseErrorMessage(response: Response, fallbackMessage: string): Promise<never> {
    const errorBody = (await response.json().catch(() => null)) as { message?: string } | null;
    throw new Error(errorBody?.message || fallbackMessage);
}

export async function listHyroxVisitsApi(month: string, signal?: AbortSignal): Promise<HyroxVisitsResponse> {
    const response = await fetch(`/internal-admin/hyrox-visits?month=${encodeURIComponent(month)}`, {
        method: "GET",
        signal
    });

    if (!response.ok) {
        await parseErrorMessage(response, `Loading HYROX visits failed: ${response.statusText}`);
    }

    return (await response.json()) as HyroxVisitsResponse;
}

/**
 * Fetch the CSV and hand it to the browser as a download.
 *
 * Fetched rather than linked so an expired admin session surfaces as a normal error the shell can
 * turn back into its login gate, instead of dumping a JSON 401 into a new tab.
 */
export async function downloadHyroxVisitsCsvApi(month: string): Promise<string> {
    const response = await fetch(`/internal-admin/hyrox-visits.csv?month=${encodeURIComponent(month)}`, {
        method: "GET"
    });

    if (!response.ok) {
        await parseErrorMessage(response, `Downloading the HYROX visits CSV failed: ${response.statusText}`);
    }

    const filename = `hyrox-visits-${month || ALL_MONTHS}.csv`;
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    try {
        const link = document.createElement("a");
        link.href = objectUrl;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
    } finally {
        // Revoking immediately would race the download in some browsers; a tick is enough.
        window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    }

    return filename;
}
