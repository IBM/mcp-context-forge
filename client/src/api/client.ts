/**
 * API client — typed fetch wrapper.
 *
 * Security guarantees:
 *  - JWT is read from sessionStorage; never from a URL query param.
 *  - Authorization: Bearer header is added on every authenticated request.
 *  - Content-Type and X-Requested-With are always set on mutating requests.
 *  - Non-2xx responses throw a typed ApiError; callers never handle raw text.
 *  - 401 responses clear the stored token and redirect to /app/login.
 */

const TOKEN_KEY = "mcpgateway_token";
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

// ---------------------------------------------------------------------------
// Token helpers — sessionStorage only
// ---------------------------------------------------------------------------

export function getToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  sessionStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  sessionStorage.removeItem(TOKEN_KEY);
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
  /** Pass `true` to skip adding the Authorization header (e.g. login). */
  unauthenticated?: boolean;
  /** AbortSignal for request cancellation/timeout. */
  signal?: AbortSignal;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const {
    method = "GET",
    body,
    headers: extraHeaders = {},
    unauthenticated = false,
    signal,
  } = options;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-Requested-With": "XMLHttpRequest",
    ...extraHeaders,
  };

  if (!unauthenticated) {
    const token = getToken();
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
  }

  const response = await fetch(path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    // Credentials: omit — auth is via Bearer header, not cookies.  // pragma: allowlist secret
    // This also means the browser will NOT auto-send cookies cross-origin,
    // making CSRF attacks structurally impossible for these requests.
    credentials: "omit", // pragma: allowlist secret
    signal,
  });

  if (response.status === 401) {
    clearToken();
    // replace() rather than href= so the failed page is not added to history
    // (the user can't hit Back into an unauthenticated state).
    window.location.replace(LOGIN_PATH);
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
    return undefined as T;
  }

  return response.json() as Promise<T>;
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
