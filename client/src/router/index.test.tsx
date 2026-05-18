import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { AuthGuard, RouterProvider } from ".";
import { I18nProvider } from "../i18n";

vi.mock("../auth/AuthContext", () => ({
  useAuthContext: vi.fn(),
}));

import { useAuthContext } from "../auth/AuthContext";

const mockUseAuthContext = useAuthContext as ReturnType<typeof vi.fn>;

function renderAuthGuard(
  path: string,
  authState: { isAuthenticated: boolean; isLoading: boolean } = {
    isAuthenticated: false,
    isLoading: false,
  },
) {
  mockUseAuthContext.mockReturnValue(authState);
  window.history.pushState({}, "", path);
  return render(
    <I18nProvider>
      <RouterProvider>
        <AuthGuard>
          <div>protected content</div>
        </AuthGuard>
      </RouterProvider>
    </I18nProvider>,
  );
}

describe("AuthGuard", () => {
  beforeEach(() => {
    mockUseAuthContext.mockClear();
  });

  describe("public paths — AuthGuard returns null, not children", () => {
    // Regression: AuthGuard previously returned <>{children}</> on public paths.
    // That rendered AppShell (with TeamSwitcher) on /app/login, causing TeamSwitcher
    // to call /teams → 401 → window.location.replace("/app/login") → reload → repeat.
    // The fix is: if (isPublic) return null.
    it("does not render children on /app/login when unauthenticated", () => {
      renderAuthGuard("/app/login", { isAuthenticated: false, isLoading: false });
      expect(screen.queryByText("protected content")).not.toBeInTheDocument();
    });

    it("does not render children on /app/login even when authenticated", () => {
      renderAuthGuard("/app/login", { isAuthenticated: true, isLoading: false });
      expect(screen.queryByText("protected content")).not.toBeInTheDocument();
    });

    it("does not render children on /app/forgot-password", () => {
      renderAuthGuard("/app/forgot-password", { isAuthenticated: false, isLoading: false });
      expect(screen.queryByText("protected content")).not.toBeInTheDocument();
    });

    it("does not render children on /app/reset-password/:token prefix", () => {
      renderAuthGuard("/app/reset-password/abc123", { isAuthenticated: false, isLoading: false });
      expect(screen.queryByText("protected content")).not.toBeInTheDocument();
    });
  });

  describe("protected paths", () => {
    it("renders children when authenticated", () => {
      renderAuthGuard("/app/", { isAuthenticated: true, isLoading: false });
      expect(screen.getByText("protected content")).toBeInTheDocument();
    });

    it("renders nothing while auth is loading", () => {
      renderAuthGuard("/app/", { isAuthenticated: false, isLoading: true });
      expect(screen.queryByText("protected content")).not.toBeInTheDocument();
    });

    it("shows loading indicator while auth is loading", () => {
      renderAuthGuard("/app/", { isAuthenticated: false, isLoading: true });
      expect(screen.getByText("Context Forge")).toBeInTheDocument();
    });

    it("renders nothing when unauthenticated", () => {
      renderAuthGuard("/app/gateways", { isAuthenticated: false, isLoading: false });
      expect(screen.queryByText("protected content")).not.toBeInTheDocument();
    });
  });
});
