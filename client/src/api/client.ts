/**
 * API client — typed fetch wrapper for the BFF (client/server).
 *
 * Security guarantees:
 *  - Authentication uses a same-origin HttpOnly session cookie set by the BFF;
 *    the API JWT never reaches the browser.
 *  - The BFF's CSRF cookie is HttpOnly (it holds a secret, not the token) —
 *    the token itself is handed to us in the JSON body of /auth/login and
 *    /auth/session and kept in memory here (setCsrfToken), then echoed back
 *    via X-CSRF-Token on mutating requests. See client/server/src/plugins/csrf.ts.
 *  - Every path except the three BFF-owned auth routes is routed through the
 *    BFF's /api/* proxy — resolveApiPath prepends /api automatically, so
 *    callers keep writing bare paths like "/tools" or "/servers/:id". This
 *    must be an exact-match set, not a "/auth/*" prefix check: FastAPI's own
 *    user-management endpoints live under /auth/email/admin/users and need
 *    the /api prefix like everything else — only login/logout/session are
 *    the BFF's own routes.
 *  - Content-Type and X-Requested-With are always set on JSON requests.
 *  - Non-2xx responses throw a typed ApiError; callers never handle raw text.
 *  - Protected 401 responses redirect to /app/login.
 */

const LOGIN_PATH = "/app/login";
const API_PREFIX = "/api";
const SESSION_CHECK_PATH = "/auth/session";
const BFF_OWNED_AUTH_PATHS = new Set(["/auth/login", "/auth/logout", SESSION_CHECK_PATH]);

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: unknown,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function getToken(): string | null {
  return null;
}

export function setToken(): void {
  // Kept for backward-compatible imports; cookie auth does not expose JWTs to JS.
}

export function clearToken(): void {
  // Kept for backward-compatible imports; cookies are cleared by /auth/logout.
}

// In-memory CSRF token, set by AuthContext after login/session-check succeeds
// and cleared on logout. Not persisted anywhere — a full page reload always
// re-derives it from a fresh /auth/session call.
let currentCsrfToken: string | null = null;

export function setCsrfToken(token: string | null): void {
  currentCsrfToken = token;
}

function isAbsoluteUrl(path: string): boolean {
  return /^https?:\/\//i.test(path);
}

/** Bare paths get /api/* (BFF proxy to the API); the BFF's own auth routes and absolute URLs pass through untouched. */
function resolveApiPath(path: string): string {
  if (isAbsoluteUrl(path)) return path;
  if (BFF_OWNED_AUTH_PATHS.has(path)) return path;
  if (path === API_PREFIX || path.startsWith(`${API_PREFIX}/`)) return path;
  return path.startsWith("/") ? `${API_PREFIX}${path}` : `${API_PREFIX}/${path}`;
}

function getRequestUrl(path: string): string {
  if (isAbsoluteUrl(path)) {
    return path;
  }

  if (typeof window !== "undefined" && window.location?.origin) {
    return new URL(path, window.location.origin).toString();
  }

  return path;
}

function canUseSignal(url: string, signal: AbortSignal): boolean {
  if (typeof Request === "undefined") {
    return true;
  }

  try {
    new Request(url, { signal });
    return true;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Core request
// ---------------------------------------------------------------------------

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

interface RequestOptions {
  method?: Method;
  body?: unknown;
  /** Extra headers merged on top of the defaults. */
  headers?: Record<string, string>;
  /** Pass `false` for public endpoints that do not require auth or CSRF (e.g. login). */
  authenticated?: boolean;
  /** AbortSignal for request cancellation/timeout. */
  signal?: AbortSignal;
}

export interface ResponseWithMeta<T> {
  data: T;
  status: number;
}

async function requestWithMeta<T>(
  path: string,
  options: RequestOptions = {},
): Promise<ResponseWithMeta<T>> {
  const {
    method = "GET",
    body,
    headers: extraHeaders = {},
    authenticated = true,
    signal,
  } = options;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-Requested-With": "XMLHttpRequest",
    ...extraHeaders,
  };

  if (method !== "GET" && authenticated && currentCsrfToken) {
    headers["X-CSRF-Token"] = currentCsrfToken;
  }

  const resolvedPath = resolveApiPath(path);
  const requestUrl = getRequestUrl(resolvedPath);
  const requestOptions: RequestInit = {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    credentials: "same-origin", // pragma: allowlist secret
  };

  if (signal && canUseSignal(requestUrl, signal)) {
    requestOptions.signal = signal;
  }

  const response = await fetch(requestUrl, requestOptions);

  if (response.status === 401) {
    if (authenticated && resolvedPath !== SESSION_CHECK_PATH) {
      // replace() rather than href= so the failed page is not added to history
      // (the user can't hit Back into an unauthenticated state).
      // Preserve the current page so login can return the user to it; built
      // inline to keep the API layer free of router imports.
      // Diverges from router.buildLoginPath on purpose: the "/app/" gate below
      // has a trailing slash, so a bare "/app" location yields no next param.
      const current = window.location.pathname + window.location.search;
      const target =
        current.startsWith("/app/") && !current.startsWith(LOGIN_PATH)
          ? `${LOGIN_PATH}?next=${encodeURIComponent(current)}`
          : LOGIN_PATH;
      window.location.replace(target);
    }
    throw new ApiError(401, null, "Session expired — redirecting to login");
  }

  if (!response.ok) {
    let errorBody: unknown = null;
    try {
      errorBody = await response.json();
    } catch {
      // ignore parse failure
    }
    throw new ApiError(response.status, errorBody, `HTTP ${response.status}`);
  }

  // 204 No Content
  if (response.status === 204) {
    return { data: undefined as T, status: response.status };
  }

  const data = (await response.json()) as T;
  return { data, status: response.status };
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { data } = await requestWithMeta<T>(path, options);
  return data;
}

// ---------------------------------------------------------------------------
// Convenience methods
// ---------------------------------------------------------------------------

export const api = {
  get<T>(path: string, headers?: Record<string, string>, signal?: AbortSignal): Promise<T> {
    return request<T>(path, { method: "GET", headers, signal });
  },

  post<T>(
    path: string,
    body?: unknown,
    opts?: Omit<RequestOptions, "method" | "body">,
  ): Promise<T> {
    return request<T>(path, { method: "POST", body, ...opts });
  },

  postWithMeta<T>(
    path: string,
    body?: unknown,
    opts?: Omit<RequestOptions, "method" | "body">,
  ): Promise<ResponseWithMeta<T>> {
    return requestWithMeta<T>(path, { method: "POST", body, ...opts });
  },

  put<T>(path: string, body?: unknown, opts?: Omit<RequestOptions, "method" | "body">): Promise<T> {
    return request<T>(path, { method: "PUT", body, ...opts });
  },

  patch<T>(
    path: string,
    body?: unknown,
    opts?: Omit<RequestOptions, "method" | "body">,
  ): Promise<T> {
    return request<T>(path, { method: "PATCH", body, ...opts });
  },

  delete<T>(path: string, opts?: Omit<RequestOptions, "method" | "body">): Promise<T> {
    return request<T>(path, { method: "DELETE", ...opts });
  },
};
