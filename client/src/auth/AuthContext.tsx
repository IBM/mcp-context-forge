import { createContext, useCallback, useContext, useState, useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { api, ApiError, setCsrfToken } from "../api/client";
import { permissionsApi } from "../api/permissions";

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

// BFF's GET /auth/session — always 200, never 401 (see client/server/src/routes/auth/session.ts).
interface SessionResponse {
  authenticated: boolean;
  user?: User;
  csrfToken?: string;
}

interface LoginResponse {
  user: User;
  csrfToken: string;
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
  /** Caller's effective permissions from GET /rbac/my/permissions (in-memory only). */
  permissions: string[];
  permissionsLoading: boolean;
  /** True when the permissions fetch failed; gates fail closed (deny). */
  permissionsError: boolean;
  /**
   * Presentational gate: true when the caller holds `perm` (or the `*` wildcard).
   * NOT a security boundary — endpoints enforce RBAC server-side. Fails closed
   * on error and on an empty permission set.
   */
  hasPermission: (perm: string) => boolean;
}

interface PermissionsState {
  permissions: string[];
  loading: boolean;
  error: boolean;
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
  // Effective permissions are kept in a separate slice (in memory only, never
  // persisted) so the existing auth setState calls are untouched.
  const [perms, setPerms] = useState<PermissionsState>({
    permissions: [],
    loading: false,
    error: false,
  });

  const setSelectedTeamId = useCallback((teamId: string | null) => {
    setState((prev) => ({ ...prev, selectedTeamId: teamId }));
  }, []);

  useEffect(() => {
    let cancelled = false;
    const version = authVersion.current;

    api
      .get<SessionResponse>("/auth/session")
      .then((data) => {
        if (cancelled || version !== authVersion.current) return;
        setCsrfToken(data.csrfToken ?? null);
        if (data.authenticated && data.user) {
          setState({
            user: data.user,
            isAuthenticated: true,
            isLoading: false,
            selectedTeamId: null,
          });
        } else {
          setState({ user: null, isAuthenticated: false, isLoading: false, selectedTeamId: null });
        }
      })
      .catch(() => {
        if (!cancelled && version === authVersion.current) {
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
        "/auth/login",
        { email, password },
        { authenticated: false },
      );

      setCsrfToken(data.csrfToken);
      authVersion.current += 1;
      setState({ user: data.user, isAuthenticated: true, isLoading: false, selectedTeamId: null });
    },
    [],
  );

  const logout = useCallback(async (): Promise<void> => {
    try {
      await api.post<{ ok: boolean }>("/auth/logout");
    } catch {
      // Client-side logout should still complete if the server-side session is already gone
      // or the CSRF token has expired.
    } finally {
      setCsrfToken(null);
      authVersion.current += 1;
      setState({ user: null, isAuthenticated: false, isLoading: false, selectedTeamId: null });
      window.location.href = "/app/login";
    }
  }, []);

  // Load effective permissions after authentication, and refetch on team
  // change (permissions are team-scoped). Fail closed on error.
  useEffect(() => {
    if (!state.isAuthenticated || !state.user) {
      setPerms({ permissions: [], loading: false, error: false });
      return;
    }

    const controller = new AbortController();
    setPerms((prev) => ({ ...prev, loading: true, error: false }));

    permissionsApi
      .listMine({ teamId: state.selectedTeamId ?? undefined, signal: controller.signal })
      .then((permissions) => {
        setPerms({ permissions, loading: false, error: false });
      })
      .catch((err) => {
        if (err instanceof Error && err.name === "AbortError") return;
        // Fail closed: empty permission set + error flag (gates deny).
        setPerms({ permissions: [], loading: false, error: true });
      });

    return () => controller.abort();
  }, [state.isAuthenticated, state.user, state.selectedTeamId]);

  const hasPermission = useCallback(
    (perm: string): boolean => {
      // Fail closed while permissions are (re)loading or on error, so a team
      // switch never briefly grants a permission carried over from the previous
      // team (which could fire admin-only probes or flash gated UI).
      if (perms.loading || perms.error) return false;
      return perms.permissions.includes("*") || perms.permissions.includes(perm);
    },
    [perms],
  );

  return (
    <AuthContext.Provider
      value={{
        ...state,
        login,
        logout,
        setSelectedTeamId,
        permissions: perms.permissions,
        permissionsLoading: perms.loading,
        permissionsError: perms.error,
        hasPermission,
      }}
    >
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
