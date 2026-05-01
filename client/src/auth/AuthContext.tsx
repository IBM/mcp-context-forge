import { createContext, useCallback, useContext, useState, useEffect } from "react";
import type { ReactNode } from "react";
import { api, setCsrfToken, clearCsrfToken, clearToken, ApiError } from "../api/client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface User {
  id: number;
  email: string;
  is_admin: boolean;
  created_at: string;
  updated_at: string;
}

interface LoginResponse {
  user: User;
  csrf_token: string;
  access_token?: string;
}

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
}

interface AuthContextValue extends AuthState {
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    user: null,
    isAuthenticated: false,
    isLoading: true,
  });

  // Rehydrate user on mount from cookie session
  useEffect(() => {
    let mounted = true;

    const fetchUser = async () => {
      try {
        const user = await api.get<User>("/app/auth/me");
        if (mounted) {
          setState({ user, isAuthenticated: true, isLoading: false });
        }
      } catch (err) {
        if (!mounted) return;

        // No valid session - clear any stale state
        if (err instanceof ApiError && err.status === 401) {
          clearCsrfToken();
          clearToken(); // Clear legacy token if present
          setState({ user: null, isAuthenticated: false, isLoading: false });
        } else {
          // Other errors (network, etc.) - assume not authenticated
          setState({ user: null, isAuthenticated: false, isLoading: false });
        }
      }
    };

    fetchUser();

    return () => {
      mounted = false;
    };
  }, []);

  const login = useCallback(
    async (
      email: string,
      password: string, // pragma: allowlist secret
    ): Promise<void> => {
      const data = await api.post<LoginResponse>(
        "/app/auth/login",
        { email, password },
        { unauthenticated: true },
      );

      // Store CSRF token for logout
      setCsrfToken(data.csrf_token);
      setState({ user: data.user, isAuthenticated: true, isLoading: false });
    },
    [],
  );

  const logout = useCallback(async (): Promise<void> => {
    try {
      // Call logout endpoint with CSRF token
      await api.post("/app/auth/logout", undefined, { includeCsrf: true });
    } catch (err) {
      // Ignore errors - clear local state regardless
      console.error("Logout request failed:", err);
    } finally {
      // Always clear local state
      clearCsrfToken();
      clearToken(); // Clear legacy token if present
      setState({ user: null, isAuthenticated: false, isLoading: false });
      window.location.href = "/app/login";
    }
  }, []);

  const refreshUser = useCallback(async (): Promise<void> => {
    try {
      const user = await api.get<User>("/app/auth/me");
      setState((prev) => ({ ...prev, user, isAuthenticated: true }));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        clearCsrfToken();
        clearToken();
        setState({ user: null, isAuthenticated: false, isLoading: false });
      }
      throw err;
    }
  }, []);

  return (
    <AuthContext.Provider value={{ ...state, login, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useAuthContext(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuthContext must be used inside <AuthProvider>");
  return ctx;
}

// Re-export ApiError so auth callers can catch login errors without importing client
export { ApiError };
