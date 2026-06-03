import { createContext, useCallback, useContext, useState, useEffect, useRef } from "react";
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
  user: User;
  csrf_token: string;
}

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  selectedTeamId: string | null;
}

interface AuthContextValue extends AuthState {
  login: (email: string, password: string) => Promise<void>; // pragma: allowlist secret
  logout: () => Promise<void>;
  setSelectedTeamId: (teamId: string | null) => void;
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const authVersion = useRef(0);
  const [state, setState] = useState<AuthState>({
    user: null,
    isAuthenticated: false,
    isLoading: true,
    selectedTeamId: null,
  });

  const setSelectedTeamId = useCallback((teamId: string | null) => {
    setState((prev) => ({ ...prev, selectedTeamId: teamId }));
  }, []);

  useEffect(() => {
    let cancelled = false;
    const version = authVersion.current;

    api
      .get<User>("/app/auth/me")
      .then((user) => {
        if (!cancelled && version === authVersion.current) {
          setState({ user, isAuthenticated: true, isLoading: false, selectedTeamId: null });
        }
      })
      .catch((err) => {
        if (!cancelled && version === authVersion.current) {
          if (err instanceof ApiError && err.status === 401) {
            setState({
              user: null,
              isAuthenticated: false,
              isLoading: false,
              selectedTeamId: null,
            });
            return;
          }
          setState({ user: null, isAuthenticated: false, isLoading: false, selectedTeamId: null });
        }
      });

    return () => {
      cancelled = true;
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
        { authenticated: false },
      );

      authVersion.current += 1;
      setState({ user: data.user, isAuthenticated: true, isLoading: false, selectedTeamId: null });
    },
    [],
  );

  const logout = useCallback(async (): Promise<void> => {
    try {
      await api.post<{ message: string }>("/app/auth/logout");
    } catch {
      // Client-side logout should still complete if the server-side session is already gone
      // or the CSRF cookie has expired.
    } finally {
      authVersion.current += 1;
      setState({ user: null, isAuthenticated: false, isLoading: false, selectedTeamId: null });
      window.location.href = "/app/login";
    }
  }, []);

  return (
    <AuthContext.Provider value={{ ...state, login, logout, setSelectedTeamId }}>
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
