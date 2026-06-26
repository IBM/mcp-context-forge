import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { Teams } from "./Teams";
import { I18nProvider } from "@/i18n";
import type { Team } from "@/types/team";

vi.mock("@/api/client", () => ({
  api: {
    get: vi.fn(),
  },
}));

import { api } from "@/api/client";

function renderTeams(ui: ReactElement) {
  return render(<I18nProvider>{ui}</I18nProvider>);
}

function createMockTeams(startIndex: number, count: number): Team[] {
  return Array.from({ length: count }, (_, i) => ({
    id: `team-${startIndex + i}`,
    name: `Team ${startIndex + i}`,
    slug: `team-${startIndex + i}`,
    description: `Description ${startIndex + i}`,
    created_by: "owner@example.com",
    is_personal: false,
    visibility: "private" as const,
    max_members: 50,
    member_count: startIndex + i,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-02T00:00:00Z",
    is_active: true,
  }));
}

describe("Teams", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders loading state while fetching teams", () => {
    const pendingRequest = new Promise<never>(() => {});
    vi.mocked(api.get).mockReturnValueOnce(pendingRequest as ReturnType<typeof api.get>);

    renderTeams(<Teams />);

    const status = screen.getByRole("status", { busy: true });
    expect(status).toBeInTheDocument();
    expect(status).toHaveAttribute("aria-live", "polite");
    expect(screen.getByText(/Loading teams, please wait/i)).toBeInTheDocument();
  });

  it("renders an error alert when the team fetch fails", async () => {
    vi.mocked(api.get).mockRejectedValueOnce(new Error("Could not load teams"));

    renderTeams(<Teams />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });

    expect(screen.getByText("Error loading teams")).toBeInTheDocument();
    expect(screen.getByText("Could not load teams")).toBeInTheDocument();
  });

  it("renders alert with correct aria attributes on error", async () => {
    vi.mocked(api.get).mockRejectedValueOnce(new Error("Service unavailable"));

    renderTeams(<Teams />);

    await waitFor(() => {
      const alert = screen.getByRole("alert");
      expect(alert).toHaveAttribute("aria-live", "assertive");
      expect(alert).toHaveAttribute("aria-atomic", "true");
    });
  });

  it("renders the empty state when no teams exist", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ teams: [], nextCursor: null });

    renderTeams(<Teams />);

    await waitFor(() => {
      expect(screen.getByText("No teams yet")).toBeInTheDocument();
    });

    expect(
      screen.getByText("Create your first team to collaborate with others."),
    ).toBeInTheDocument();

    // The empty-state Create button is clickable (handler is a placeholder for now).
    const createButton = screen.getByRole("button", { name: /Create team/i });
    expect(createButton).toBeInTheDocument();
    await userEvent.setup().click(createButton);
    expect(screen.getByText("No teams yet")).toBeInTheDocument();
  });

  it("renders the teams list and header when data is loaded", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      teams: createMockTeams(0, 3),
      nextCursor: null,
    });

    renderTeams(<Teams />);

    await waitFor(() => {
      expect(screen.getByText("Team 0")).toBeInTheDocument();
    });

    expect(screen.getByText("All Teams")).toBeInTheDocument();
    expect(screen.getByText("Team 2")).toBeInTheDocument();
  });

  it("renders the Create team button with a Plus icon", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      teams: createMockTeams(0, 1),
      nextCursor: null,
    });

    renderTeams(<Teams />);

    await waitFor(() => {
      expect(screen.getByText("Team 0")).toBeInTheDocument();
    });

    const button = screen.getByRole("button", { name: /Create team/i });
    expect(button).toBeInTheDocument();
    expect(button.querySelector("svg")).toBeInTheDocument();

    // The list-view Create button is clickable (handler is a placeholder for now).
    await userEvent.setup().click(button);
    expect(screen.getByText("All Teams")).toBeInTheDocument();
  });

  it("displays a pluralized team count message", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      teams: createMockTeams(0, 5),
      nextCursor: null,
    });

    renderTeams(<Teams />);

    await waitFor(() => {
      expect(screen.getByText("Showing 5 teams")).toBeInTheDocument();
    });
  });

  it("displays a singular team count message for one team", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      teams: createMockTeams(0, 1),
      nextCursor: null,
    });

    renderTeams(<Teams />);

    await waitFor(() => {
      expect(screen.getByText("Showing 1 team")).toBeInTheDocument();
    });
  });

  it("renders all per-page limit options", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      teams: createMockTeams(0, 1),
      nextCursor: null,
    });

    renderTeams(<Teams />);

    await waitFor(() => {
      expect(screen.getByText("Team 0")).toBeInTheDocument();
    });

    const values = screen.getAllByRole("option").map((opt) => opt.getAttribute("value"));
    expect(values).toEqual(expect.arrayContaining(["10", "25", "50", "100"]));
  });

  it("changes the per-page limit when the select changes", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValue({
      teams: createMockTeams(0, 1),
      nextCursor: null,
    });

    renderTeams(<Teams />);

    await waitFor(() => {
      expect(screen.getByText("Team 0")).toBeInTheDocument();
    });

    const limitSelect = screen.getByRole("combobox", { name: /Per page:/i });
    expect(limitSelect).toHaveValue("10");

    await user.selectOptions(limitSelect, "25");

    expect(limitSelect).toHaveValue("25");
  });

  it("requests a new page size when the limit changes", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValue({
      teams: createMockTeams(0, 1),
      nextCursor: null,
    });

    renderTeams(<Teams />);

    await waitFor(() => {
      expect(screen.getByText("Team 0")).toBeInTheDocument();
    });

    await user.selectOptions(screen.getByRole("combobox", { name: /Per page:/i }), "50");

    await waitFor(() => {
      const requestedPaths = vi.mocked(api.get).mock.calls.map((call) => call[0]);
      expect(
        requestedPaths.some((path) => typeof path === "string" && path.includes("limit=50")),
      ).toBe(true);
    });
  });

  it("treats a missing nextCursor as no further pages", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ teams: createMockTeams(0, 3) });

    renderTeams(<Teams />);

    await waitFor(() => {
      expect(screen.getByText("Team 0")).toBeInTheDocument();
    });

    expect(screen.queryByRole("button", { name: /Load more teams/i })).not.toBeInTheDocument();
  });

  it("does not render the Load More button when there is no next cursor", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      teams: createMockTeams(0, 10),
      nextCursor: null,
    });

    renderTeams(<Teams />);

    await waitFor(() => {
      expect(screen.getByText("Team 0")).toBeInTheDocument();
    });

    expect(screen.queryByRole("button", { name: /Load more teams/i })).not.toBeInTheDocument();
  });

  it("renders the Load More button when a next cursor is available", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      teams: createMockTeams(0, 10),
      nextCursor: "cursor-1",
    });

    renderTeams(<Teams />);

    await waitFor(() => {
      expect(screen.getByText("Team 0")).toBeInTheDocument();
    });

    expect(screen.getByRole("button", { name: /Load more teams/i })).toBeInTheDocument();
  });

  it("accumulates teams when Load More is clicked", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValueOnce({
      teams: createMockTeams(0, 10),
      nextCursor: "cursor-1",
    });

    renderTeams(<Teams />);

    await waitFor(() => {
      expect(screen.getByText("Team 0")).toBeInTheDocument();
    });

    expect(screen.getByText("Showing 10 teams")).toBeInTheDocument();

    vi.mocked(api.get).mockResolvedValueOnce({
      teams: createMockTeams(10, 5),
      nextCursor: null,
    });

    await user.click(screen.getByRole("button", { name: /Load more teams/i }));

    await waitFor(() => {
      expect(screen.getByText("Team 14")).toBeInTheDocument();
    });

    expect(screen.getByText("Team 0")).toBeInTheDocument();
    expect(screen.getByText("Showing 15 teams")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Load more teams/i })).not.toBeInTheDocument();
  });

  it("forwards the cursor and limit when loading more", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValueOnce({
      teams: createMockTeams(0, 10),
      nextCursor: "cursor-abc",
    });

    renderTeams(<Teams />);

    await waitFor(() => {
      expect(screen.getByText("Team 0")).toBeInTheDocument();
    });

    vi.mocked(api.get).mockResolvedValueOnce({
      teams: createMockTeams(10, 5),
      nextCursor: null,
    });

    await user.click(screen.getByRole("button", { name: /Load more teams/i }));

    await waitFor(() => {
      expect(api.get).toHaveBeenLastCalledWith(
        expect.stringMatching(/cursor=cursor-abc.*limit=10|limit=10.*cursor=cursor-abc/),
      );
    });
  });

  it("shows loading text and disables the button while loading more", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValueOnce({
      teams: createMockTeams(0, 10),
      nextCursor: "cursor-1",
    });

    renderTeams(<Teams />);

    await waitFor(() => {
      expect(screen.getByText("Team 0")).toBeInTheDocument();
    });

    let resolveLoadMore: (value: unknown) => void = () => {};
    const pending = new Promise<unknown>((resolve) => {
      resolveLoadMore = resolve;
    });
    vi.mocked(api.get).mockReturnValueOnce(pending as ReturnType<typeof api.get>);

    await user.click(screen.getByRole("button", { name: /Load more teams/i }));

    await waitFor(() => {
      expect(screen.getByText("Loading...")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: /Load more teams/i })).toBeDisabled();

    resolveLoadMore({ teams: createMockTeams(10, 5), nextCursor: null });

    await waitFor(() => {
      expect(screen.getByText("Team 14")).toBeInTheDocument();
    });
  });

  it("does not load more when a load is already in progress", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValueOnce({
      teams: createMockTeams(0, 10),
      nextCursor: "cursor-1",
    });

    renderTeams(<Teams />);

    await waitFor(() => {
      expect(screen.getByText("Team 0")).toBeInTheDocument();
    });

    let resolveLoadMore: (value: unknown) => void = () => {};
    const pending = new Promise<unknown>((resolve) => {
      resolveLoadMore = resolve;
    });
    vi.mocked(api.get).mockReturnValueOnce(pending as ReturnType<typeof api.get>);

    const loadMoreButton = screen.getByRole("button", { name: /Load more teams/i });
    await user.click(loadMoreButton);
    await user.click(loadMoreButton);

    resolveLoadMore({ teams: createMockTeams(10, 5), nextCursor: null });

    await waitFor(() => {
      expect(screen.getByText("Team 14")).toBeInTheDocument();
    });

    // Once for the initial load, once for the single accepted load-more.
    expect(api.get).toHaveBeenCalledTimes(2);
  });

  it("logs a console error when loading more fails", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValueOnce({
      teams: createMockTeams(0, 10),
      nextCursor: "cursor-1",
    });

    renderTeams(<Teams />);

    await waitFor(() => {
      expect(screen.getByText("Team 0")).toBeInTheDocument();
    });

    vi.mocked(api.get).mockRejectedValueOnce(new Error("Load more network failure"));
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    await user.click(screen.getByRole("button", { name: /Load more teams/i }));

    await waitFor(() => {
      expect(consoleErrorSpy).toHaveBeenCalledWith("Failed to load more teams:", expect.any(Error));
    });

    consoleErrorSpy.mockRestore();
  });
});
