import type { ApiErrorBody } from "./types";

export class ApiError extends Error {
  code: string;
  status: number;
  details: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;

export function withQuery(path: string, query?: Query): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === null || value === undefined || value === "") continue;
    params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

async function parse(response: Response) {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(handler: () => void) {
  onUnauthorized = handler;
}

let refreshing: Promise<boolean> | null = null;

async function tryRefresh(): Promise<boolean> {
  if (!refreshing) {
    refreshing = fetch("/api/v1/auth/refresh", { method: "POST", credentials: "include" })
      .then((r) => r.ok)
      .catch(() => false)
      .finally(() => {
        setTimeout(() => (refreshing = null), 0);
      });
  }
  return refreshing;
}

export async function request<T>(
  path: string,
  options: RequestInit & { query?: Query; retry?: boolean } = {},
): Promise<T> {
  const { query, retry = true, ...init } = options;
  const url = withQuery(path.startsWith("/api") ? path : `/api/v1${path}`, query);

  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData) && !headers.has("content-type")) {
    headers.set("content-type", "application/json");
  }

  const response = await fetch(url, { ...init, headers, credentials: "include" });

  if (response.status === 401 && retry) {
    // An expired access token is routine; the refresh cookie lives much longer.
    if (await tryRefresh()) {
      return request<T>(path, { ...options, retry: false });
    }
    onUnauthorized?.();
  }

  if (!response.ok) {
    const body = (await parse(response)) as ApiErrorBody | null;
    const error = body && typeof body === "object" && "error" in body ? body.error : null;
    throw new ApiError(
      response.status,
      error?.code ?? "request_failed",
      error?.message ?? `The request failed (${response.status}).`,
      error?.details,
    );
  }

  return (await parse(response)) as T;
}

export const api = {
  get: <T>(path: string, query?: Query) => request<T>(path, { method: "GET", query }),
  post: <T>(path: string, body?: unknown, query?: Query) =>
    request<T>(path, {
      method: "POST",
      body: body instanceof FormData ? body : body === undefined ? undefined : JSON.stringify(body),
      query,
    }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body ?? {}) }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body ?? {}) }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

export function downloadUrl(path: string, query?: Query): string {
  return withQuery(path.startsWith("/api") ? path : `/api/v1${path}`, query);
}
