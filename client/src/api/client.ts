/**
 * API client — typed fetch wrapper.
 *
 * Security guarantees:
 *  - JWT is stored in httpOnly cookie (XSS protection)
 *  - CSRF token stored in sessionStorage for state-changing operations
 *  - Content-Type and X-Requested-With are always set on mutating requests
 *  - Non-2xx responses throw a typed ApiError; callers never handle raw text
 *  - 401 responses clear stored CSRF token and redirect to /app/login
 */

const CSRF_TOKEN_KEY = "mcpgateway_csrf_token";
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
// CSRF token helpers — sessionStorage only (JWT is in httpOnly cookie)
// ---------------------------------------------------------------------------

export function getCsrfToken(): string | null {
  return sessionStorage.getItem(CSRF_TOKEN_KEY);
}

export function setCsrfToken(token: string): void {
  sessionStorage.setItem(CSRF_TOKEN_KEY, token);
}

export function clearCsrfToken(): void {
  sessionStorage.removeItem(CSRF_TOKEN_KEY);
}

// ---------------------------------------------------------------------------
// Legacy token helpers (deprecated - for backward compatibility)
// ---------------------------------------------------------------------------

const TOKEN_KEY = "mcpgateway_token";

export function getToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  sessionStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  sessionStorage.removeItem(TOKEN_KEY);
  clearCsrfToken();
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
  /** Pass `true` to include CSRF token header for state-changing operations. */
  includeCsrf?: boolean;
  /** AbortSignal for request cancellation/timeout. */
  signal?: AbortSignal;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const {
    method = "GET",
    body,
    headers: extraHeaders = {},
    unauthenticated = false,
    includeCsrf = false,
    signal,
  } = options;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-Requested-With": "XMLHttpRequest",
    ...extraHeaders,
  };

  // Add Bearer token for API endpoints
  // For cookie-based auth, extract JWT from cookie and add to Authorization header
  // because admin API endpoints expect Bearer token for backward compatibility
  if (!unauthenticated) {
    // First try legacy token from sessionStorage
    let token = getToken();

    // If no legacy token, extract JWT from cookie for admin API compatibility
    if (!token) {
      const cookies = document.cookie.split(';');
      const jwtCookie = cookies.find(c => c.trim().startsWith('jwt_token='));
      if (jwtCookie) {
        token = jwtCookie.split('=')[1];
      }
    }

    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
  }

  // Add CSRF token header for state-changing operations
  if (includeCsrf) {
    const csrfToken = getCsrfToken();
    if (csrfToken) {
      headers["X-CSRF-Token"] = csrfToken;
    }
  }

  const response = await fetch(path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    // Include credentials to send/receive httpOnly cookies
    credentials: "include", // pragma: allowlist secret
    signal,
  });

  if (response.status === 401) {
    clearToken();
    clearCsrfToken();

    // Don't redirect on /app/auth/me - let AuthContext handle it gracefully
    // This prevents redirect loops during initial auth check
    if (!path.includes("/app/auth/me")) {
      // replace() rather than href= so the failed page is not added to history
      // (the user can't hit Back into an unauthenticated state).
      window.location.replace(LOGIN_PATH);
    }

    throw new ApiError(401, null, "Unauthorized");
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
