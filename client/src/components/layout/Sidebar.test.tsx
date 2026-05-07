import { describe, expect, it, vi, beforeEach } from "vitest";
import userEvent from "@testing-library/user-event";
import { render, screen } from "@testing-library/react";
import { SidebarProvider } from "../ui/sidebar";
import { I18nProvider } from "@/i18n";
import { AppSidebar } from "./Sidebar";

const mockNavigate = vi.fn();
const mockUseRouter = vi.fn();

vi.mock("@/router", async () => {
  const actual = await vi.importActual<typeof import("@/router")>("@/router");
  return {
    ...actual,
    useRouter: () => mockUseRouter(),
  };
});

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

    expect(screen.getByRole("button", { name: "MCP Servers" })).toHaveAttribute("data-active", "true");
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
});
