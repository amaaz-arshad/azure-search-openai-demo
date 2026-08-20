/** Scale and tick helpers shared by every chart on the telemetry page.
 *
 * Hand-rolled rather than pulled from a charting library: the project has no chart dependency at all,
 * the admin routes are statically imported into the main SPA bundle (which every chatbot page
 * downloads, including the ungated public ones), and the chart set here is small and regular. See
 * ChartFrame for the accessibility half of that decision.
 */

export interface LinearScale {
    (value: number): number;
    domain: [number, number];
    range: [number, number];
    ticks: (count?: number) => number[];
}

export interface BandScale {
    (index: number): number;
    bandwidth: number;
    step: number;
}

/** A "nice" upper bound: 1, 2, 2.5 or 5 times a power of ten, so axis labels are readable numbers. */
export function niceCeiling(value: number): number {
    if (!Number.isFinite(value) || value <= 0) return 1;
    const magnitude = Math.pow(10, Math.floor(Math.log10(value)));
    const normalized = value / magnitude;
    const step = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 2.5 ? 2.5 : normalized <= 5 ? 5 : 10;
    return step * magnitude;
}

export function linearScale(domain: [number, number], range: [number, number]): LinearScale {
    const [d0, d1] = domain;
    const [r0, r1] = range;
    const span = d1 - d0 || 1;
    const scale = ((value: number) => r0 + ((value - d0) / span) * (r1 - r0)) as LinearScale;
    scale.domain = domain;
    scale.range = range;
    scale.ticks = (count = 5) => {
        const step = niceCeiling(span / Math.max(1, count));
        const ticks: number[] = [];
        for (let tick = Math.ceil(d0 / step) * step; tick <= d1 + step * 0.001; tick += step) {
            ticks.push(Number(tick.toFixed(10)));
        }
        return ticks;
    };
    return scale;
}

export function bandScale(count: number, width: number, padding = 0.2): BandScale {
    const step = count > 0 ? width / count : width;
    const bandwidth = Math.max(1, step * (1 - padding));
    const scale = ((index: number) => index * step + (step - bandwidth) / 2) as BandScale;
    scale.bandwidth = bandwidth;
    scale.step = step;
    return scale;
}

/** Show at most `max` labels, evenly spaced, so a 90-day axis stays legible. */
export function thinTicks<T>(items: T[], max = 8): { item: T; index: number }[] {
    const stride = Math.max(1, Math.ceil(items.length / max));
    return items.map((item, index) => ({ item, index })).filter(({ index }) => index % stride === 0);
}

/** A duration a human reads at a glance: 840 ms, 4.2 s, 1 m 12 s. */
export function formatDuration(ms: number | null | undefined): string {
    if (ms === null || ms === undefined || !Number.isFinite(ms)) return "—";
    if (ms < 1000) return `${Math.round(ms)} ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} s`;
    const minutes = Math.floor(ms / 60000);
    return `${minutes} m ${Math.round((ms % 60000) / 1000)} s`;
}

const compactNumber = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 });
const plainNumber = new Intl.NumberFormat("en");

export function formatCount(value: number | null | undefined): string {
    if (value === null || value === undefined || !Number.isFinite(value)) return "—";
    return value >= 10000 ? compactNumber.format(value) : plainNumber.format(value);
}

export function formatExactCount(value: number | null | undefined): string {
    if (value === null || value === undefined || !Number.isFinite(value)) return "—";
    return plainNumber.format(value);
}

/**
 * Cost is stored as integer millionths of a currency unit. Rendered with up to four decimals below 1
 * so a fractional-cent per-step cost does not display as 0.00, which would read as free.
 */
export function formatCost(micros: number | null | undefined, currency = "EUR"): string {
    if (micros === null || micros === undefined || !Number.isFinite(micros)) return "—";
    const value = micros / 1_000_000;
    const digits = value !== 0 && Math.abs(value) < 1 ? 4 : 2;
    try {
        return new Intl.NumberFormat("en", {
            style: "currency",
            currency,
            minimumFractionDigits: digits === 4 ? 2 : 2,
            maximumFractionDigits: digits
        }).format(value);
    } catch {
        return `${value.toFixed(digits)} ${currency}`;
    }
}

export function formatPercent(fraction: number | null | undefined, digits = 1): string {
    if (fraction === null || fraction === undefined || !Number.isFinite(fraction)) return "—";
    return `${(fraction * 100).toFixed(digits)}%`;
}

/**
 * Everything the dashboard SHOWS is in German time; everything it STORES is UTC.
 *
 * The conversion lives here, in the browser, because the browser has complete IANA data and the
 * backend's environment has none (`zoneinfo` cannot resolve Europe/Berlin there without adding a
 * dependency). Hour buckets convert exactly, since the offset is a whole number of hours. Day, week
 * and month buckets are calendar labels for UTC days and are deliberately NOT shifted -- the rollups
 * aggregate whole UTC days, so a shifted label would claim a boundary the data does not have. The
 * filter bar says so.
 */
export const DISPLAY_TIME_ZONE = "Europe/Berlin";

/** "CET" / "CEST", so the UI can name the zone it is showing rather than asserting a fixed one. */
export function timeZoneLabel(at: Date = new Date()): string {
    try {
        const parts = new Intl.DateTimeFormat("en-GB", {
            timeZone: DISPLAY_TIME_ZONE,
            timeZoneName: "short"
        }).formatToParts(at);
        return parts.find(part => part.type === "timeZoneName")?.value ?? "";
    } catch {
        return "";
    }
}

/** Bucket labels follow the granularity. See DISPLAY_TIME_ZONE for which of these shift. */
/** "1 request" / "2 requests". Prose, so the singular has to be right. */
export function formatRequestCount(count: number): string {
    return `${formatExactCount(count)} ${count === 1 ? "request" : "requests"}`;
}

export function formatBucket(bucket: string, granularity: string): string {
    if (granularity === "hour") {
        const parsed = new Date(bucket);
        return Number.isNaN(parsed.getTime())
            ? bucket
            : new Intl.DateTimeFormat("en-GB", {
                  hour: "2-digit",
                  minute: "2-digit",
                  timeZone: DISPLAY_TIME_ZONE
              }).format(parsed);
    }
    if (granularity === "month") {
        const parsed = new Date(`${bucket}-01T00:00:00Z`);
        return Number.isNaN(parsed.getTime())
            ? bucket
            : new Intl.DateTimeFormat("en-GB", { month: "short", year: "2-digit", timeZone: "UTC" }).format(parsed);
    }
    const parsed = new Date(`${bucket}T00:00:00Z`);
    return Number.isNaN(parsed.getTime())
        ? bucket
        : new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", timeZone: "UTC" }).format(parsed);
}

export function formatTimestamp(iso: string): string {
    const parsed = new Date(iso);
    if (Number.isNaN(parsed.getTime())) return iso;
    return new Intl.DateTimeFormat("en-GB", {
        day: "2-digit",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        timeZone: DISPLAY_TIME_ZONE
    }).format(parsed);
}

export function formatDay(day: string): string {
    const parsed = new Date(`${day}T00:00:00Z`);
    if (Number.isNaN(parsed.getTime())) return day;
    return new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" }).format(
        parsed
    );
}
