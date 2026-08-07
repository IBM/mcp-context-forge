import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { RouterProvider } from "@/router";
import { I18nProvider } from "@/i18n";
import { Settings } from "./Settings";

const mockUseAuthContext = vi.fn();

vi.mock("@/auth/AuthContext", () => ({
  useAuthContext: () => mockUseAuthContext(),
}));

vi.mock("@/pages/Users", () => ({
  Users: () => <div>Users tab content</div>,
}));

vi.mock("@/pages/Teams", () => ({
  Teams: () => <div>Teams tab content</div>,
}));

function makeAuth(isAdmin: boolean) {
  return {
    user: {
      email: isAdmin ? "admin@example.com" : "user@example.com",
      full_name: "Test User",
      is_admin: isAdmin,
      is_active: true,
      auth_provider: "local",
      email_verified: true,
      password_change_required: false,
    },
    isAuthenticated: true,
    isLoading: false,
    selectedTeamId: null,
    login: vi.fn(),
    logout: vi.fn(),
  };
}

function renderWithRouter(ui: ReactElement, path = "/app/settings") {
  window.history.pushState({}, "", path);
  return render(
    <RouterProvider>
      <I18nProvider>{ui}</I18nProvider>
    </RouterProvider>,
  );
}

describe("Settings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseAuthContext.mockReturnValue(makeAuth(true));
  });

  it("renders Users and Teams tabs with Users content by default for admins", () => {
    renderWithRouter(<Settings />);

    expect(screen.getByRole("tab", { name: "Users" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Teams" })).toBeInTheDocument();
    expect(screen.getByText("Users tab content")).toBeInTheDocument();
  });

  it("shows the Teams content when the teams tab is active", () => {
    renderWithRouter(<Settings tab="teams" />, "/app/settings/teams");

    expect(screen.getByText("Teams tab content")).toBeInTheDocument();
  });

  it("navigates to the teams tab when the Teams trigger is clicked", async () => {
    const user = userEvent.setup();
    renderWithRouter(<Settings tab="users" />, "/app/settings/users");

    await user.click(screen.getByRole("tab", { name: "Teams" }));

    await waitFor(() => {
      expect(window.location.pathname).toBe("/app/settings/teams");
    });
  });

  it("renders no tabs for non-admin users", () => {
    mockUseAuthContext.mockReturnValue(makeAuth(false));
    renderWithRouter(<Settings />);

    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Settings" })).toBeInTheDocument();
  });

  it("redirects a non-admin away from a tab route", async () => {
    mockUseAuthContext.mockReturnValue(makeAuth(false));
    renderWithRouter(<Settings tab="users" />, "/app/settings/users");

    await waitFor(() => {
      expect(window.location.pathname).toBe("/app/settings");
    });
  });

  it("redirects an unknown tab to the settings root", async () => {
    renderWithRouter(<Settings tab="bogus" />, "/app/settings/bogus");

    await waitFor(() => {
      expect(window.location.pathname).toBe("/app/settings");
    });
  });
});
