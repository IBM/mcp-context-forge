/**
 * API client — typed fetch wrapper.
 *
 * Security guarantees:
 *  - Authentication uses same-origin httpOnly cookies; JWTs are never stored in web storage.
 *  - CSRF tokens are read from the non-httpOnly CSRF cookie and sent on mutating requests.
 *  - Content-Type and X-Requested-With are always set on JSON requests.
 *  - Non-2xx responses throw a typed ApiError; callers never handle raw text.
 *  - Protected 401 responses redirect to /app/login.
 */

const LOGIN_PATH = "/app/login";

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
  // Kept for backward-compatible imports; cookies are cleared by /app/auth/logout.
}

function getCookie(name: string): string | null {
  const prefix = `${encodeURIComponent(name)}=`;
  const cookie = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix));

  if (!cookie) return null;
  return decodeURIComponent(cookie.slice(prefix.length));
}

function getRequestUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) {
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

  if (method !== "GET" && authenticated) {
    const csrfToken = getCookie("mcpgateway_csrf_token");
    if (csrfToken) {
      headers["X-CSRF-Token"] = csrfToken;
    }
  }

  const requestUrl = getRequestUrl(path);
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
    if (authenticated && path !== "/app/auth/me") {
      // replace() rather than href= so the failed page is not added to history
      // (the user can't hit Back into an unauthenticated state).
      // Preserve the current page so login can return the user to it; built
      // inline to keep the API layer free of router imports.
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
