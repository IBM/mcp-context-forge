import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nProvider } from "@/i18n";
import { SidebarProvider } from "@/components/ui/sidebar";
import { TeamSwitcher } from "./TeamSwitcher";

function renderTeamSwitcher() {
  return render(
    <I18nProvider>
      <SidebarProvider>
        <TeamSwitcher />
      </SidebarProvider>
    </I18nProvider>,
  );
}

// Mock the useQuery hook
const mockUseQuery = vi.fn();
vi.mock("@/hooks/useQuery", () => ({
  useQuery: () => mockUseQuery(),
}));

describe("TeamSwitcher", () => {
  beforeEach(() => {
    mockUseQuery.mockClear();
  });

  it("renders loading state while fetching teams", () => {
    mockUseQuery.mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
      execute: vi.fn(),
      refetch: vi.fn(),
    });

    renderTeamSwitcher();
    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });

  it("renders 'All teams' by default when teams are loaded", () => {
    mockUseQuery.mockReturnValue({
      data: {
        teams: [
          { id: "1", name: "Engineering" },
          { id: "2", name: "Marketing" },
        ],
      },
      isLoading: false,
      error: null,
      execute: vi.fn(),
      refetch: vi.fn(),
    });

    renderTeamSwitcher();
    expect(screen.getByText("All teams")).toBeInTheDocument();
  });

  it("displays error message when teams fail to load", async () => {
    const user = userEvent.setup();
    mockUseQuery.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: { message: "Network error", status: 500 },
      execute: vi.fn(),
      refetch: vi.fn(),
    });

    renderTeamSwitcher();

    // Click the dropdown trigger
    const trigger = screen.getByRole("button", { name: /all teams/i });
    await user.click(trigger);

    // Wait for dropdown to open and check for error message
    await waitFor(() => {
      expect(screen.getByText("Failed to load teams")).toBeInTheDocument();
    });
  });

  it("displays 'No teams available' when teams array is empty", async () => {
    const user = userEvent.setup();
    mockUseQuery.mockReturnValue({
      data: { teams: [] },
      isLoading: false,
      error: null,
      execute: vi.fn(),
      refetch: vi.fn(),
    });

    renderTeamSwitcher();

    // Click the dropdown trigger
    const trigger = screen.getByRole("button", { name: /all teams/i });
    await user.click(trigger);

    // Wait for dropdown to open and check for empty state
    await waitFor(() => {
      expect(screen.getByText("No teams available")).toBeInTheDocument();
    });
  });

  it("renders all teams in dropdown menu", async () => {
    const user = userEvent.setup();
    mockUseQuery.mockReturnValue({
      data: {
        teams: [
          { id: "1", name: "Engineering" },
          { id: "2", name: "Marketing" },
          { id: "3", name: "Sales" },
        ],
      },
      isLoading: false,
      error: null,
      execute: vi.fn(),
      refetch: vi.fn(),
    });

    renderTeamSwitcher();

    // Click the dropdown trigger
    const trigger = screen.getByRole("button", { name: /all teams/i });
    await user.click(trigger);

    // Wait for dropdown to open and check for all teams
    await waitFor(() => {
      expect(screen.getByText("Engineering")).toBeInTheDocument();
      expect(screen.getByText("Marketing")).toBeInTheDocument();
      expect(screen.getByText("Sales")).toBeInTheDocument();
    });
  });

  it("updates selected team when clicking on a team", async () => {
    const user = userEvent.setup();
    mockUseQuery.mockReturnValue({
      data: {
        teams: [
          { id: "1", name: "Engineering" },
          { id: "2", name: "Marketing" },
        ],
      },
      isLoading: false,
      error: null,
      execute: vi.fn(),
      refetch: vi.fn(),
    });

    renderTeamSwitcher();

    // Click the dropdown trigger
    const trigger = screen.getByRole("button", { name: /all teams/i });
    await user.click(trigger);

    // Click on Engineering team
    const engineeringOption = await screen.findByText("Engineering");
    await user.click(engineeringOption);

    // Wait for dropdown to close and trigger to update
    await waitFor(() => {
      const updatedTrigger = screen.getByRole("button", { name: /engineering/i });
      expect(updatedTrigger).toBeInTheDocument();
    });
  });

  it("resets to 'All teams' when clicking the All teams option", async () => {
    const user = userEvent.setup();
    mockUseQuery.mockReturnValue({
      data: {
        teams: [
          { id: "1", name: "Engineering" },
          { id: "2", name: "Marketing" },
        ],
      },
      isLoading: false,
      error: null,
      execute: vi.fn(),
      refetch: vi.fn(),
    });

    renderTeamSwitcher();

    // First select a team
    const trigger = screen.getByRole("button", { name: /all teams/i });
    await user.click(trigger);

    const engineeringOption = await screen.findByText("Engineering");
    await user.click(engineeringOption);

    // Wait for selection to update and dropdown to close
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /engineering/i })).toBeInTheDocument();
    });

    // Wait a bit for any animations/transitions to complete
    await new Promise((resolve) => setTimeout(resolve, 100));

    // Now click to open dropdown again
    const updatedTrigger = screen.getByRole("button", { name: /engineering/i });
    await user.click(updatedTrigger);

    // Find and click the "All teams" menu item (not the trigger button)
    const menuItems = await screen.findAllByRole("menuitem");
    const allTeamsMenuItem = menuItems.find((item) => item.textContent?.includes("All teams"));
    expect(allTeamsMenuItem).toBeDefined();
    await user.click(allTeamsMenuItem!);

    // Wait for selection to reset
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /all teams/i })).toBeInTheDocument();
    });
  });

  it("renders Globe icon for each team", async () => {
    const user = userEvent.setup();
    mockUseQuery.mockReturnValue({
      data: {
        teams: [
          { id: "1", name: "Engineering" },
          { id: "2", name: "Marketing" },
        ],
      },
      isLoading: false,
      error: null,
      execute: vi.fn(),
      refetch: vi.fn(),
    });

    renderTeamSwitcher();

    // Click the dropdown trigger
    const trigger = screen.getByRole("button", { name: /all teams/i });
    await user.click(trigger);

    // Wait for dropdown to open
    await waitFor(() => {
      expect(screen.getByText("Engineering")).toBeInTheDocument();
    });

    // Check that Globe icons are rendered (they have specific classes)
    const container = screen.getByRole("menu");
    const globeIcons = container.querySelectorAll("svg");
    // Should have at least 3 icons: All teams + 2 team items
    expect(globeIcons.length).toBeGreaterThanOrEqual(3);
  });
});
