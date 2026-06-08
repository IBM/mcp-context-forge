import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, render, waitFor } from "@testing-library/react";
import { AuthProvider, useAuthContext, ApiError } from "./AuthContext";
import { useAuth } from "./useAuth";
import { api } from "../api/client";
import { useEffect } from "react";

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
  };
});

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

describe("AuthContext", () => {
  const originalLocation = window.location;

  beforeEach(() => {
    vi.clearAllMocks();
    // Mock window.location
    delete (window as any).location;
    window.location = { href: "" } as any;
  });

  afterEach(() => {
    window.location = originalLocation;
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
    const mockUser = {
      email: "user@example.com",
      full_name: "Test User",
      is_admin: true,
      is_active: true,
      auth_provider: "local",
      email_verified: true,
      password_change_required: false,
    };

    vi.mocked(api.get).mockResolvedValueOnce(mockUser);

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
    expect(api.get).toHaveBeenCalledWith("/app/auth/me");
  });

  it("handles failed initial authentication (401)", async () => {
    const error = new ApiError(401, "Unauthorized");
    vi.mocked(api.get).mockRejectedValueOnce(error);

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

  it("handles failed initial authentication (generic error)", async () => {
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
    vi.mocked(api.get).mockRejectedValueOnce(new ApiError(401, "Unauthorized"));

    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.queryByTestId("loading")).not.toBeInTheDocument();
    });

    const mockUser = {
      email: "user@example.com",
      full_name: "Test User",
      is_admin: false,
      is_active: true,
      auth_provider: "local",
      email_verified: true,
      password_change_required: false,
    };

    vi.mocked(api.post).mockResolvedValueOnce({
      user: mockUser,
      csrf_token: "csrf-token-123",
    });

    screen.getByText("Login").click();

    await waitFor(() => {
      expect(screen.getByTestId("auth-status")).toHaveTextContent("authenticated");
      expect(screen.getByTestId("user-email")).toHaveTextContent("user@example.com");
    });

    expect(api.post).toHaveBeenCalledWith(
      "/app/auth/login",
      { email: "test@example.com", password: "pass" },
      { authenticated: false },
    );
  });

  it("handles successful logout", async () => {
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

    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.queryByTestId("loading")).not.toBeInTheDocument();
    });

    vi.mocked(api.post).mockResolvedValueOnce({ message: "logged out" });

    screen.getByText("Logout").click();

    await waitFor(() => {
      expect(screen.getByTestId("auth-status")).toHaveTextContent("guest");
      expect(window.location.href).toBe("/app/login");
    });

    expect(api.post).toHaveBeenCalledWith("/app/auth/logout");
  });

  it("handles logout server failure gracefully", async () => {
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

  it("re-exports useAuth correctly", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      email: "user@example.com",
      full_name: "Test User",
      is_admin: false,
      is_active: true,
      auth_provider: "local",
      email_verified: true,
      password_change_required: false,
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
