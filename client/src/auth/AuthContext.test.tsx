import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, render, waitFor } from "@testing-library/react";
import { AuthProvider, useAuthContext } from "./AuthContext";
import { useAuth } from "./useAuth";
import { api, setCsrfToken } from "../api/client";
import { permissionsApi } from "../api/permissions";

// Mock the API client
vi.mock("../api/client", () => {
  class MockApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.name = "ApiError";
      this.status = status;
    }
  }
  return {
    api: {
      get: vi.fn(),
      post: vi.fn(),
    },
    ApiError: MockApiError,
    setCsrfToken: vi.fn(),
  };
});

// The permissions effect fires after authentication; mock it so it resolves
// deterministically and does not hit the (mocked) api.get for /app/auth/me.
vi.mock("../api/permissions", () => ({
  permissionsApi: { listMine: vi.fn().mockResolvedValue([]) },
}));

const mockUser = {
  email: "user@example.com",
  full_name: "Test User",
  is_admin: false,
  is_active: true,
  auth_provider: "local",
  email_verified: true,
  password_change_required: false,
};

// Helper component to test context values
function TestComponent() {
  const auth = useAuthContext();
  if (auth.isLoading) {
    return <div data-testid="loading">Loading...</div>;
  }
  return (
    <div>
      <div data-testid="auth-status">{auth.isAuthenticated ? "authenticated" : "guest"}</div>
      {auth.user && <div data-testid="user-email">{auth.user.email}</div>}
      <button onClick={() => auth.login("test@example.com", "pass")}>Login</button>
      <button onClick={() => auth.logout()}>Logout</button>
    </div>
  );
}

// Helper for useAuth re-export
function UseAuthTestComponent() {
  const auth = useAuth();
  return <div data-testid="reexport-status">{auth.isAuthenticated ? "yes" : "no"}</div>;
}

// Probe that reports permission state directly (not gated on loading) so a test
// can observe the fail-closed window.
function PermProbe() {
  const { hasPermission, permissionsLoading } = useAuth();
  return (
    <div>
      <div data-testid="perm-loading">{String(permissionsLoading)}</div>
      <div data-testid="perm-has">{String(hasPermission("tools.read"))}</div>
    </div>
  );
}

describe("AuthContext", () => {
  const originalLocation = window.location;

  beforeEach(() => {
    vi.clearAllMocks();
    // Mock window.location
    delete (window as unknown as { location?: unknown }).location;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    window.location = { href: "" } as any;
  });

  afterEach(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    window.location = originalLocation as any;
  });

  it("throws error when useAuthContext is used outside AuthProvider", () => {
    // Suppress console.error for expected boundary throw
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<TestComponent />)).toThrow(
      "useAuthContext must be used inside <AuthProvider>",
    );
    consoleSpy.mockRestore();
  });

  it("handles successful initial authentication", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      authenticated: true,
      user: mockUser,
      csrfToken: "session-csrf-token",
    });

    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>,
    );

    expect(screen.getByTestId("loading")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.queryByTestId("loading")).not.toBeInTheDocument();
    });

    expect(screen.getByTestId("auth-status")).toHaveTextContent("authenticated");
    expect(screen.getByTestId("user-email")).toHaveTextContent("user@example.com");
    expect(api.get).toHaveBeenCalledWith("/auth/session");
    expect(setCsrfToken).toHaveBeenCalledWith("session-csrf-token");
  });

  it("handles an unauthenticated initial session check", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ authenticated: false });

    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.queryByTestId("loading")).not.toBeInTheDocument();
    });

    expect(screen.getByTestId("auth-status")).toHaveTextContent("guest");
    expect(screen.queryByTestId("user-email")).not.toBeInTheDocument();
  });

  it("handles failed initial authentication (network/generic error)", async () => {
    vi.mocked(api.get).mockRejectedValueOnce(new Error("Network Failure"));

    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.queryByTestId("loading")).not.toBeInTheDocument();
    });

    expect(screen.getByTestId("auth-status")).toHaveTextContent("guest");
  });

  it("handles successful login", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ authenticated: false });

    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.queryByTestId("loading")).not.toBeInTheDocument();
    });

    vi.mocked(api.post).mockResolvedValueOnce({
      user: mockUser,
      csrfToken: "csrf-token-123",
    });

    screen.getByText("Login").click();

    await waitFor(() => {
      expect(screen.getByTestId("auth-status")).toHaveTextContent("authenticated");
      expect(screen.getByTestId("user-email")).toHaveTextContent("user@example.com");
    });

    expect(api.post).toHaveBeenCalledWith(
      "/auth/login",
      { email: "test@example.com", password: "pass" },
      { authenticated: false },
    );
    expect(setCsrfToken).toHaveBeenCalledWith("csrf-token-123");
  });

  it("handles successful logout", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      authenticated: true,
      user: mockUser,
      csrfToken: "t",
    });

    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.queryByTestId("loading")).not.toBeInTheDocument();
    });

    vi.mocked(api.post).mockResolvedValueOnce({ ok: true });

    screen.getByText("Logout").click();

    await waitFor(() => {
      expect(screen.getByTestId("auth-status")).toHaveTextContent("guest");
      expect(window.location.href).toBe("/app/login");
    });

    expect(api.post).toHaveBeenCalledWith("/auth/logout");
    expect(setCsrfToken).toHaveBeenCalledWith(null);
  });

  it("handles logout server failure gracefully", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      authenticated: true,
      user: mockUser,
      csrfToken: "t",
    });

    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.queryByTestId("loading")).not.toBeInTheDocument();
    });

    vi.mocked(api.post).mockRejectedValueOnce(new Error("Server error"));

    screen.getByText("Logout").click();

    await waitFor(() => {
      expect(screen.getByTestId("auth-status")).toHaveTextContent("guest");
      expect(window.location.href).toBe("/app/login");
    });
  });

  it("fails closed: hasPermission is false while permissions are (re)loading", async () => {
    const mockUser = {
      email: "user@example.com",
      full_name: "Test User",
      is_admin: false,
      is_active: true,
      auth_provider: "local",
      email_verified: true,
      password_change_required: false,
    };
    vi.mocked(api.get).mockResolvedValueOnce(mockUser);

    // Hold the permissions fetch open so we can observe the loading window.
    let resolvePerms!: (perms: string[]) => void;
    const permsPromise = new Promise<string[]>((resolve) => {
      resolvePerms = resolve;
    });
    vi.mocked(permissionsApi.listMine).mockReturnValueOnce(permsPromise);

    render(
      <AuthProvider>
        <PermProbe />
      </AuthProvider>,
    );

    // Auth has resolved but permissions are still in flight -> deny.
    await waitFor(() => expect(screen.getByTestId("perm-loading")).toHaveTextContent("true"));
    expect(screen.getByTestId("perm-has")).toHaveTextContent("false");

    // Once the permissions arrive, the grant applies.
    resolvePerms(["tools.read"]);
    await waitFor(() => expect(screen.getByTestId("perm-loading")).toHaveTextContent("false"));
    expect(screen.getByTestId("perm-has")).toHaveTextContent("true");
  });

  it("re-exports useAuth correctly", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      authenticated: true,
      user: mockUser,
      csrfToken: "t",
    });

    render(
      <AuthProvider>
        <UseAuthTestComponent />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("reexport-status")).toHaveTextContent("yes");
    });
  });
});
