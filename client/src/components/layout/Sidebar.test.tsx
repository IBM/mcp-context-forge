import { describe, expect, it, vi, beforeEach } from "vitest";
import userEvent from "@testing-library/user-event";
import { render, screen } from "@testing-library/react";
import { SidebarProvider } from "../ui/sidebar";
import { I18nProvider } from "@/i18n";
import { AppSidebar } from "./Sidebar";

const mockNavigate = vi.fn();
const mockUseRouter = vi.fn();
const mockUseQuery = vi.fn();
const mockUseAuthContext = vi.fn();

vi.mock("@/router", async () => {
  const actual = await vi.importActual<typeof import("@/router")>("@/router");
  return {
    ...actual,
    useRouter: () => mockUseRouter(),
  };
});

vi.mock("@/hooks/useQuery", () => ({
  useQuery: () => mockUseQuery(),
}));

vi.mock("@/auth/AuthContext", () => ({
  useAuthContext: () => mockUseAuthContext(),
}));

function renderSidebar() {
  return render(
    <I18nProvider>
      <SidebarProvider>
        <AppSidebar />
      </SidebarProvider>
    </I18nProvider>,
  );
}

describe("AppSidebar", () => {
  beforeEach(() => {
    mockNavigate.mockReset();
    mockUseRouter.mockReset();
    mockUseQuery.mockReturnValue({
      data: { teams: [{ id: "engineering", name: "Engineering" }] },
      isLoading: false,
      error: null,
      execute: vi.fn(),
      refetch: vi.fn(),
      setData: vi.fn(),
    });
    mockUseAuthContext.mockReturnValue({
      user: {
        email: "admin@example.com",
        full_name: "Admin User",
        is_admin: true,
        is_active: true,
        auth_provider: "local",
        email_verified: true,
        password_change_required: false,
      },
      isAuthenticated: true,
      isLoading: false,
      login: vi.fn(),
      logout: vi.fn(),
    });
  });

  it("renders the main navigation groups and footer link", () => {
    mockUseRouter.mockReturnValue({
      path: "/app/",
      params: {},
      navigate: mockNavigate,
    });

    renderSidebar();

    expect(screen.getByRole("button", { name: "Home" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Virtual Servers" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Select team. Current: All teams" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Components")).toBeInTheDocument();
    expect(screen.getByText("Ecosystem")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Settings" })).toBeInTheDocument();
  });

  it("marks the current route as active, including nested paths", () => {
    mockUseRouter.mockReturnValue({
      path: "/app/servers/abc",
      params: {},
      navigate: mockNavigate,
    });

    renderSidebar();

    expect(screen.getByRole("button", { name: "MCP Servers" })).toHaveAttribute(
      "data-active",
      "true",
    );
    expect(screen.getByRole("button", { name: "Home" })).toHaveAttribute("data-active", "false");
  });

  it("navigates when a navigation item is clicked", async () => {
    const user = userEvent.setup();
    mockUseRouter.mockReturnValue({
      path: "/app/",
      params: {},
      navigate: mockNavigate,
    });

    renderSidebar();

    await user.click(screen.getByRole("button", { name: "Plugins" }));

    expect(mockNavigate).toHaveBeenCalledWith("/app/plugins");
  });

  it("highlights the settings footer item when on the settings route", () => {
    mockUseRouter.mockReturnValue({
      path: "/app/settings",
      params: {},
      navigate: mockNavigate,
    });

    renderSidebar();

    expect(screen.getByRole("button", { name: "Settings" })).toHaveAttribute("data-active", "true");
  });

  it("shows Administration section for platform admin users", () => {
    mockUseRouter.mockReturnValue({
      path: "/app/",
      params: {},
      navigate: mockNavigate,
    });

    renderSidebar();

    expect(screen.getByText("Administration")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Users" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Teams" })).toBeInTheDocument();
  });

  it("hides Administration section for non-admin users", () => {
    mockUseAuthContext.mockReturnValue({
      user: {
        email: "user@example.com",
        full_name: "Regular User",
        is_admin: false,
        is_active: true,
        auth_provider: "local",
        email_verified: true,
        password_change_required: false,
      },
      isAuthenticated: true,
      isLoading: false,
      login: vi.fn(),
      logout: vi.fn(),
    });

    mockUseRouter.mockReturnValue({
      path: "/app/",
      params: {},
      navigate: mockNavigate,
    });

    renderSidebar();

    expect(screen.queryByText("Administration")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Users" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Teams" })).not.toBeInTheDocument();
  });
});
