import {
  authorizationHeaders,
  hostedAuthEnabled,
  refreshAuthorizationHeaders,
} from "@/lib/auth-session";

/** One API-origin seam for desktop/local and hosted web deployments. */
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_JOURNALME_API_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://127.0.0.1:8066/api/v1";
const API_URL = API_BASE_URL;

const inFlightGets = new Map<string, Promise<unknown>>();
const responseCache = new Map<string, { expiresAt: number; value: unknown }>();

function cacheTtl(path: string): number {
  if (path === "/accounts" || path === "/preferences" || path === "/tags") return 30_000;
  if (path.startsWith("/playbooks")) return 30_000;
  if (
    path.startsWith("/dashboard") ||
    path.startsWith("/review-summary") ||
    path.startsWith("/review-queue") ||
    path.startsWith("/trading-days") ||
    path.startsWith("/trades") ||
    path.startsWith("/calendar") ||
    path.startsWith("/analytics") ||
    path.startsWith("/intelligence") ||
    path.startsWith("/broker-connections") ||
    path.startsWith("/goals") ||
    path.startsWith("/prop-rules") ||
    path.startsWith("/push")
  ) return 8_000;
  return 2_000;
}

export function assetUrl(path: string): string {
  if (path.startsWith("/api/v1")) {
    return `${API_URL.slice(0, -"/api/v1".length)}${path}`;
  }
  return `${API_URL}${path}`;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

export type ImportIssue = {
  report_type: string;
  filename: string;
  row_number: number;
  source_column: string;
  field_name: string;
  reason: string;
};

export function errorMessage(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((issue) => {
        if (!issue || typeof issue !== "object") return "";
        const validation = issue as { loc?: unknown[]; msg?: string };
        const field = validation.loc?.at(-1);
        return `${String(field ?? "field").replaceAll("_", " ")}: ${validation.msg ?? "Invalid value."}`;
      })
      .filter(Boolean)
      .join(" ");
  }
  if (!detail || typeof detail !== "object") {
    return "JournalMe could not complete that request.";
  }
  const structured = detail as {
    message?: string;
    errors?: ImportIssue[];
  };
  const contexts = (structured.errors ?? []).map(
    (issue) =>
      `${issue.filename}, CSV row ${issue.row_number}, column ${issue.source_column} ` +
      `(${issue.field_name}): ${issue.reason}`,
  );
  return [structured.message, ...contexts].filter(Boolean).join(" ");
}

export async function api<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const method = (options?.method ?? "GET").toUpperCase();
  const dedupeKey = `${method}:${path}`;
  const bypassMemoryCache = options?.cache === "reload" || options?.cache === "no-cache";
  if (method === "GET" && !bypassMemoryCache) {
    const cached = responseCache.get(dedupeKey);
    if (cached && cached.expiresAt > Date.now()) return cached.value as T;
    const existing = inFlightGets.get(dedupeKey);
    if (existing) return existing as Promise<T>;
  } else {
    responseCache.clear();
  }

  const request = (async () => {
    const doFetch = async (authHeaders: HeadersInit) =>
      fetch(`${API_URL}${path}`, {
        ...options,
        headers:
          options?.body instanceof FormData
            ? { ...authHeaders, ...options.headers }
            : {
                "Content-Type": "application/json",
                ...authHeaders,
                ...options?.headers,
              },
        cache: "no-store",
      });

    let response = await doFetch(await authorizationHeaders());
    if (response.status === 401 && hostedAuthEnabled) {
      try {
        const refreshedHeaders = await refreshAuthorizationHeaders();
        response = await doFetch(refreshedHeaders);
      } catch {
        // Preserve the original unauthorized response. Supabase owns session
        // restoration; an API race must not force a browser logout.
      }
    }
    if (!response.ok) {
      const payload = (await response.json().catch(() => null)) as {
        detail?: unknown;
      } | null;
      throw new ApiError(errorMessage(payload?.detail), response.status);
    }
    if (response.status === 204) return undefined as T;
    const value = await response.json() as T;
    if (method === "GET" && !bypassMemoryCache) {
      responseCache.set(dedupeKey, {
        expiresAt: Date.now() + cacheTtl(path),
        value,
      });
    }
    return value;
  })();
  if (method === "GET") inFlightGets.set(dedupeKey, request);
  try {
    return await request;
  } finally {
    if (method === "GET") inFlightGets.delete(dedupeKey);
  }
}

export async function apiBlob(path: string): Promise<Blob> {
  const target = path.startsWith("http://") || path.startsWith("https://") ? path : assetUrl(path);
  const doFetch = async (authHeaders: HeadersInit) => fetch(target, {
    headers: authHeaders,
    cache: "no-store",
  });
  let response = await doFetch(await authorizationHeaders());
  if (response.status === 401 && hostedAuthEnabled) {
    try {
      response = await doFetch(await refreshAuthorizationHeaders());
    } catch {
      // Keep the original 401 without forcing a Supabase logout.
    }
  }
  if (!response.ok) {
    throw new ApiError("JournalMe could not load that file.", response.status);
  }
  return response.blob();
}

export function money(
  value: string | number | null | undefined,
  currency = "USD",
): string {
  if (value === null || value === undefined) return "Unavailable";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
  }).format(Number(value));
}

export function percent(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "Unavailable";
  return `${Number(value).toFixed(1)}%`;
}

export function duration(seconds: number | null): string {
  if (seconds === null) return "Unavailable";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remaining = seconds % 60;
  return [hours && `${hours}h`, minutes && `${minutes}m`, `${remaining}s`]
    .filter(Boolean)
    .join(" ");
}

export function quantity(
  value: string | number | null | undefined,
  includeUnit = false,
): string {
  if (value === null || value === undefined) return "Unavailable";
  const numeric = Number(value);
  const display = Number.isInteger(numeric)
    ? String(numeric)
    : numeric.toLocaleString("en-US", { maximumFractionDigits: 6 });
  if (!includeUnit) return display;
  return `${display} ${numeric === 1 ? "contract" : "contracts"}`;
}

export function dateTime(
  value: string,
  options?: Intl.DateTimeFormatOptions,
): string {
  const resolved = options ?? {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  };
  const includesTime = Boolean(
    resolved.timeStyle || resolved.hour || resolved.minute || resolved.second,
  );
  return new Intl.DateTimeFormat("en-US", {
    ...resolved,
    ...(includesTime ? { hour12: true } : {}),
  }).format(new Date(value));
}

export function timeOnly(
  value: string | Date,
  options: Intl.DateTimeFormatOptions = {},
): string {
  return new Intl.DateTimeFormat("en-US", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
    ...options,
  }).format(typeof value === "string" ? new Date(value) : value);
}

export function hourLabel12(value: string): string {
  const match = /^(\d{1,2}):(\d{2})$/.exec(value.trim());
  if (!match) return value;
  const hour = Number(match[1]);
  const minute = match[2];
  if (hour < 0 || hour > 23) return value;
  const suffix = hour >= 12 ? "PM" : "AM";
  const displayHour = hour % 12 || 12;
  return `${displayHour}:${minute} ${suffix}`;
}

export function price(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "Unavailable";
  return Number(value).toLocaleString("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 8,
  });
}

