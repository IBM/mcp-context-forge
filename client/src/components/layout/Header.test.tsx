import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Header } from "./Header";
import { useQuery } from "../../hooks/useQuery";
import { SidebarProvider } from "../ui/sidebar";

// Mock dependencies
vi.mock("../../hooks/useQuery", () => ({
  useQuery: vi.fn(),
}));

vi.mock("./HeaderQuickNav", () => ({
  HeaderQuickNav: () => <div data-testid="quick-nav" />,
}));

vi.mock("./HeaderProfileMenu", () => ({
  HeaderProfileMenu: () => <div data-testid="profile-menu" />,
}));

describe("Header", () => {
  const renderHeader = () => {
    return render(
      <SidebarProvider>
        <Header />
      </SidebarProvider>,
    );
  };

  it("renders without version when useQuery returns no data", () => {
    (useQuery as any).mockReturnValue({ data: null });
    renderHeader();

    expect(screen.getByTestId("quick-nav")).toBeInTheDocument();
    expect(screen.getByTestId("profile-menu")).toBeInTheDocument();

    // Check that there is no version string visible (like v1.2.3)
    const versionMatch = screen.queryByText(/v\d+\.\d+\.\d+/);
    expect(versionMatch).not.toBeInTheDocument();
  });

  it("renders with version when useQuery returns version data", () => {
    (useQuery as any).mockReturnValue({
      data: {
        app: {
          version: "1.0.0",
        },
      },
    });
    renderHeader();

    expect(screen.getByText("v1.0.0")).toBeInTheDocument();
  });
});
