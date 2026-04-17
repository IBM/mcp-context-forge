import { createContext, useCallback, useContext, useState, useEffect } from "react";
import type { ReactNode } from "react";
import { api, ApiError } from "../api/client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface User {
  email: string;
  full_name: string | null;
  is_admin: boolean;
  is_active: boolean;
  auth_provider: string;
  email_verified: boolean;
  password_change_required: boolean;
}

interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
}

interface AuthContextValue extends AuthState {
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    user: null,
    isAuthenticated: false,
  });

  useEffect(() => {
    api
      .get<User>("/auth/me")
      .then((user) => {
        setState({ user, isAuthenticated: true });
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          setState({ user: null, isAuthenticated: false });
        }
      });
  }, []);

  const login = useCallback(async (email: string, password: string): Promise<void> => {
    // pragma: allowlist secret
    const data = await api.post<LoginResponse>(
      "/auth/login",
      { email, password, set_cookie: true },
      { unauthenticated: true },
    );

    setState({ user: data.user, isAuthenticated: true });
  }, []);

  const logout = useCallback(async (): Promise<void> => {
    try {
      await api.post("/auth/logout");
    } catch {
      // Ignore errors - proceed with logout
    }
    setState({ user: null, isAuthenticated: false });
    window.location.href = "/app/login";
  }, []);

  return (
    <AuthContext.Provider value={{ ...state, login, logout }}>{children}</AuthContext.Provider>
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
