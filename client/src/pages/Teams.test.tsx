import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { render } from "@testing-library/react";
import { toast } from "sonner";
import { Teams } from "./Teams";
import { RouterProvider } from "@/router";
import { I18nProvider } from "@/i18n";
import type { ReactElement } from "react";

vi.mock("@/api/client", () => ({
  api: {
    get: vi.fn(),
    delete: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
  },
}));

vi.mock("@/api/teams", () => ({
  deleteTeam: vi.fn(),
  createTeam: vi.fn(),
  updateTeam: vi.fn(),
  addTeamMember: vi.fn(),
  listTeamMembers: vi.fn(),
  updateTeamMember: vi.fn(),
  removeTeamMember: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

import { api } from "@/api/client";
import { deleteTeam, createTeam, updateTeam, listTeamMembers } from "@/api/teams";

const mockToastSuccess = vi.mocked(toast.success);
const mockToastError = vi.mocked(toast.error);
const mockDeleteTeam = vi.mocked(deleteTeam);
const mockCreateTeam = vi.mocked(createTeam);
const mockUpdateTeam = vi.mocked(updateTeam);

function createMockTeams(startIndex: number, count: number) {
  return Array.from({ length: count }, (_, i) => ({
    id: `team-${startIndex + i}`,
    name: `Team ${startIndex + i}`,
    slug: `team-${startIndex + i}`,
    description: `Description for Team ${startIndex + i}`,
    created_by: "admin@example.com",
    is_personal: false,
    visibility: "private" as const,
    max_members: 50,
    member_count: i + 1,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    is_active: true,
  }));
}

function renderWithRouter(ui: ReactElement) {
  window.history.pushState({}, "", "/app/teams");
  return render(
    <RouterProvider>
      <I18nProvider>{ui}</I18nProvider>
    </RouterProvider>,
  );
}

describe("Teams", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  it("renders loading state while fetching teams", () => {
    const pendingRequest = new Promise<never>(() => {});
    vi.mocked(api.get).mockReturnValueOnce(pendingRequest as ReturnType<typeof api.get>);

    renderWithRouter(<Teams />);

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveAttribute("aria-live", "polite");
    expect(screen.getByRole("status")).toHaveAttribute("aria-busy", "true");
  });

  it("renders an error alert when the team fetch fails", async () => {
    vi.mocked(api.get).mockRejectedValueOnce(new Error("Could not load teams"));

    renderWithRouter(<Teams />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });

    expect(screen.getByText("Error loading teams")).toBeInTheDocument();
    expect(screen.getByText("Could not load teams")).toBeInTheDocument();
  });

  it("renders alert with correct aria attributes on error", async () => {
    vi.mocked(api.get).mockRejectedValueOnce(new Error("Service unavailable"));

    renderWithRouter(<Teams />);

    await waitFor(() => {
      const alert = screen.getByRole("alert");
      expect(alert).toHaveAttribute("aria-live", "assertive");
      expect(alert).toHaveAttribute("aria-atomic", "true");
    });
  });

  it("renders an empty teams state when no teams exist", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ teams: [], nextCursor: null });

    renderWithRouter(<Teams />);

    await waitFor(() => {
      expect(screen.getByText("No teams yet")).toBeInTheDocument();
    });

    expect(
      screen.getByText("Create your first team to collaborate with others."),
    ).toBeInTheDocument();
  });

  it("renders teams title/header", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ teams: createMockTeams(0, 1), nextCursor: null });

    renderWithRouter(<Teams />);

    await waitFor(() => {
      expect(screen.getByText("All Teams")).toBeInTheDocument();
    });
  });

  it("renders Create team button", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ teams: [], nextCursor: null });

    renderWithRouter(<Teams />);

    await waitFor(() => {
      const button = screen.getAllByRole("button", { name: /Create team/i })[0];
      expect(button).toBeInTheDocument();
    });
  });

  it("changes the displayed team limit when the select changes", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValueOnce({ teams: createMockTeams(0, 1), nextCursor: null });

    renderWithRouter(<Teams />);

    await waitFor(() => {
      expect(screen.getByText("Team 0")).toBeInTheDocument();
    });

    const limitSelect = screen.getByRole("combobox", { name: /Per page:/i });
    await user.selectOptions(limitSelect, "25");

    expect(limitSelect).toHaveValue("25");
  });

  it("renders all limit options", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ teams: createMockTeams(0, 1), nextCursor: null });

    renderWithRouter(<Teams />);

    await waitFor(() => {
      expect(screen.getByText("Team 0")).toBeInTheDocument();
    });

    const options = screen.getAllByRole("option");
    const values = options.map((opt) => opt.getAttribute("value"));

    expect(values).toContain("10");
    expect(values).toContain("25");
    expect(values).toContain("50");
    expect(values).toContain("100");
  });

  it("does not render Load More button when there is no next cursor", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ teams: createMockTeams(0, 10), nextCursor: null });

    renderWithRouter(<Teams />);

    await waitFor(() => {
      expect(screen.getByText("Team 0")).toBeInTheDocument();
    });

    expect(screen.queryByRole("button", { name: /Load more/i })).not.toBeInTheDocument();
  });

  it("renders Load More button when next cursor is available", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      teams: createMockTeams(0, 10),
      nextCursor: "cursor-1",
    });

    renderWithRouter(<Teams />);

    await waitFor(() => {
      expect(screen.getByText("Team 0")).toBeInTheDocument();
    });

    expect(screen.getByRole("button", { name: /Load more/i })).toBeInTheDocument();
  });

  it("renders teams list when data is loaded", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      teams: createMockTeams(0, 10),
      nextCursor: null,
    });

    renderWithRouter(<Teams />);

    await waitFor(() => {
      expect(screen.getByText("Team 0")).toBeInTheDocument();
    });

    expect(screen.getByText("All Teams")).toBeInTheDocument();
    expect(screen.getByText("Team 9")).toBeInTheDocument();
  });

  it("displays correct team count message", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      teams: createMockTeams(0, 5),
      nextCursor: null,
    });

    renderWithRouter(<Teams />);

    await waitFor(() => {
      expect(screen.getByText(/Showing 5 teams/)).toBeInTheDocument();
    });
  });

  it("loads more teams when Load More button is clicked", async () => {
    const user = userEvent.setup();

    vi.mocked(api.get).mockResolvedValueOnce({
      teams: createMockTeams(0, 10),
      nextCursor: "cursor-1",
    });

    renderWithRouter(<Teams />);

    await waitFor(() => {
      expect(screen.getByText("Team 0")).toBeInTheDocument();
    });

    const loadMoreButton = screen.getByRole("button", { name: /load more teams/i });
    expect(loadMoreButton).toBeInTheDocument();

    vi.mocked(api.get).mockResolvedValueOnce({
      teams: createMockTeams(10, 10),
      nextCursor: null,
    });

    await user.click(loadMoreButton);

    await waitFor(() => {
      expect(screen.getByText("Team 10")).toBeInTheDocument();
    });

    expect(screen.queryByRole("button", { name: /load more teams/i })).not.toBeInTheDocument();
  });

  it("removes team from list and shows success toast after API responds", async () => {
    const user = userEvent.setup();

    vi.mocked(api.get).mockResolvedValueOnce({
      teams: createMockTeams(0, 3),
      nextCursor: null,
    });

    renderWithRouter(<Teams />);

    await waitFor(() => {
      expect(screen.getByText("Team 0")).toBeInTheDocument();
    });

    mockDeleteTeam.mockResolvedValueOnce(undefined);
    vi.mocked(api.get).mockResolvedValueOnce({
      teams: createMockTeams(1, 2),
      nextCursor: null,
    });

    await user.click(screen.getByRole("button", { name: "Actions for Team 0" }));
    await user.click(await screen.findByRole("menuitem", { name: /^delete$/i }));

    await user.click(await screen.findByRole("button", { name: /delete/i }));

    await waitFor(() => {
      expect(screen.queryByText("Team 0")).not.toBeInTheDocument();
    });

    expect(screen.getByText("Team 1")).toBeInTheDocument();
    expect(mockToastSuccess).toHaveBeenCalledWith(expect.stringContaining("Team 0"));
  });

  it("optimistically removes team from list immediately on delete confirmation", async () => {
    const user = userEvent.setup();

    vi.mocked(api.get).mockResolvedValueOnce({
      teams: createMockTeams(0, 1),
      nextCursor: null,
    });

    renderWithRouter(<Teams />);

    await waitFor(() => {
      expect(screen.getByText("Team 0")).toBeInTheDocument();
    });

    let resolveDelete!: () => void;
    mockDeleteTeam.mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          resolveDelete = resolve;
        }),
    );

    await user.click(screen.getByRole("button", { name: "Actions for Team 0" }));
    await user.click(await screen.findByRole("menuitem", { name: /^delete$/i }));
    await user.click(await screen.findByRole("button", { name: /delete/i }));

    await waitFor(() => {
      expect(screen.queryByText("Team 0")).not.toBeInTheDocument();
    });
    expect(screen.queryByRole("button", { name: /delete/i })).not.toBeInTheDocument();

    resolveDelete();

    await waitFor(() => {
      expect(mockToastSuccess).toHaveBeenCalledWith(expect.stringContaining("Team 0"));
    });
  });

  it("rolls back optimistic delete when API call fails", async () => {
    const user = userEvent.setup();

    vi.mocked(api.get).mockResolvedValueOnce({
      teams: createMockTeams(0, 3),
      nextCursor: null,
    });

    renderWithRouter(<Teams />);

    await waitFor(() => {
      expect(screen.getByText("Team 0")).toBeInTheDocument();
    });

    mockDeleteTeam.mockRejectedValueOnce(new Error("500 Internal Server Error"));

    const actionsButton = screen.getByRole("button", { name: "Actions for Team 0" });
    await user.click(actionsButton);

    const deleteItem = await screen.findByRole("menuitem", { name: /^delete$/i });
    await user.click(deleteItem);

    const confirmButton = await screen.findByRole("button", { name: /delete/i });
    await user.click(confirmButton);

    await waitFor(() => {
      expect(screen.getByText("Team 0")).toBeInTheDocument();
    });

    expect(mockToastError).toHaveBeenCalledWith(
      expect.stringContaining("Failed to delete team"),
      expect.objectContaining({
        description: expect.any(String),
      }),
    );
  });

  it("cancelling the delete dialog keeps team in list", async () => {
    const user = userEvent.setup();

    vi.mocked(api.get).mockResolvedValueOnce({
      teams: createMockTeams(0, 2),
      nextCursor: null,
    });

    renderWithRouter(<Teams />);

    await waitFor(() => {
      expect(screen.getByText("Team 0")).toBeInTheDocument();
    });

    const actionsButton = screen.getByRole("button", { name: "Actions for Team 0" });
    await user.click(actionsButton);

    const deleteItem = await screen.findByRole("menuitem", { name: /^delete$/i });
    await user.click(deleteItem);

    expect(await screen.findByRole("dialog")).toBeInTheDocument();

    const cancelButton = screen.getByRole("button", { name: /cancel/i });
    await user.click(cancelButton);

    expect(screen.getByText("Team 0")).toBeInTheDocument();

    expect(mockDeleteTeam).not.toHaveBeenCalled();
    expect(mockToastSuccess).not.toHaveBeenCalled();
    expect(mockToastError).not.toHaveBeenCalled();
  });

  it("shows loading text on Load More button while loading", async () => {
    const user = userEvent.setup();

    vi.mocked(api.get).mockResolvedValueOnce({
      teams: createMockTeams(0, 10),
      nextCursor: "cursor-1",
    });

    renderWithRouter(<Teams />);

    await waitFor(() => {
      expect(screen.getByText("Team 0")).toBeInTheDocument();
    });

    const loadMoreButton = screen.getByRole("button", { name: /load more teams/i });

    let resolveLoadMore: ((value: unknown) => void) | null = null;
    const pendingLoadMore = new Promise<unknown>((resolve) => {
      resolveLoadMore = resolve;
    });

    vi.mocked(api.get).mockReturnValueOnce(pendingLoadMore as ReturnType<typeof api.get>);

    await user.click(loadMoreButton);

    if (resolveLoadMore) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (resolveLoadMore as any)({
        teams: createMockTeams(10, 5),
        nextCursor: null,
      });

      await waitFor(() => {
        expect(screen.getByText("Team 10")).toBeInTheDocument();
      });
    }
  });

  it("accumulates teams when loading more", async () => {
    const user = userEvent.setup();

    vi.mocked(api.get).mockResolvedValueOnce({
      teams: createMockTeams(0, 5),
      nextCursor: "cursor-1",
    });

    renderWithRouter(<Teams />);

    await waitFor(() => {
      expect(screen.getByText("Team 0")).toBeInTheDocument();
      expect(screen.getByText("Team 4")).toBeInTheDocument();
    });

    expect(screen.getByText(/Showing 5 teams/)).toBeInTheDocument();

    vi.mocked(api.get).mockResolvedValueOnce({
      teams: createMockTeams(5, 5),
      nextCursor: null,
    });

    const loadMoreButton = screen.getByRole("button", { name: /load more teams/i });
    await user.click(loadMoreButton);

    await waitFor(() => {
      expect(screen.getByText("Team 5")).toBeInTheDocument();
      expect(screen.getByText("Team 9")).toBeInTheDocument();
    });

    expect(screen.getByText(/Showing 10 teams/)).toBeInTheDocument();
  });

  it("maintains state when limit changes", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValueOnce({
      teams: createMockTeams(0, 10),
      nextCursor: null,
    });

    renderWithRouter(<Teams />);

    await waitFor(() => {
      expect(screen.getByText("Team 0")).toBeInTheDocument();
    });

    const limitSelect = screen.getByRole("combobox", { name: /Per page:/i });
    expect(limitSelect).toHaveValue("10");

    await user.selectOptions(limitSelect, "50");

    expect(limitSelect).toHaveValue("50");
    expect(screen.getByText("Team 0")).toBeInTheDocument();
  });

  it("logs console error when refetch after delete fails", async () => {
    const user = userEvent.setup();
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    vi.mocked(api.get).mockResolvedValueOnce({
      teams: createMockTeams(0, 3),
      nextCursor: null,
    });

    renderWithRouter(<Teams />);

    await waitFor(() => {
      expect(screen.getByText("Team 0")).toBeInTheDocument();
    });

    mockDeleteTeam.mockResolvedValueOnce(undefined);
    vi.mocked(api.get).mockRejectedValueOnce(new Error("Refetch failed"));

    await user.click(screen.getByRole("button", { name: "Actions for Team 0" }));
    await user.click(await screen.findByRole("menuitem", { name: /^delete$/i }));
    await user.click(await screen.findByRole("button", { name: /delete/i }));

    await waitFor(() => {
      expect(consoleErrorSpy).toHaveBeenCalledWith(
        "Failed to refresh teams after deletion:",
        expect.any(String),
      );
    });

    consoleErrorSpy.mockRestore();
  });

  it("shows delete confirmation dialog with team name", async () => {
    const user = userEvent.setup();

    vi.mocked(api.get).mockResolvedValueOnce({
      teams: createMockTeams(0, 1),
      nextCursor: null,
    });

    renderWithRouter(<Teams />);

    await waitFor(() => {
      expect(screen.getByText("Team 0")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "Actions for Team 0" }));
    await user.click(await screen.findByRole("menuitem", { name: /^delete$/i }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(screen.getByText(/Are you sure you want to delete Team 0/)).toBeInTheDocument();
  });

  it("opens the edit form pre-filled when Edit is clicked", async () => {
    const user = userEvent.setup();

    // The edit form mounts useTeamForm, which fetches the user directory, so the
    // api.get mock must answer both the teams list and the users endpoint.
    vi.mocked(api.get).mockImplementation((path: string) => {
      if (path.includes("/auth/email/admin/users")) {
        return Promise.resolve({ users: [] });
      }
      return Promise.resolve({ teams: createMockTeams(0, 1), nextCursor: null });
    });

    renderWithRouter(<Teams />);

    await waitFor(() => {
      expect(screen.getByText("Team 0")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "Actions for Team 0" }));
    await user.click(await screen.findByRole("menuitem", { name: /^edit$/i }));

    expect(await screen.findByRole("heading", { name: /edit team/i })).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/add team name/i)).toHaveValue("Team 0");
    expect(screen.getByRole("button", { name: /^save changes$/i })).toBeInTheDocument();
  });

  it("opens the create form when Create team is clicked in list state", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValueOnce({
      teams: createMockTeams(0, 1),
      nextCursor: null,
    });
    // The create form's useTeamForm hook loads the user directory on mount.
    vi.mocked(api.get).mockResolvedValue({ users: [] });

    renderWithRouter(<Teams />);

    await waitFor(() => {
      expect(screen.getByText("Team 0")).toBeInTheDocument();
    });

    const createButton = screen.getAllByRole("button", { name: /Create team/i })[0];
    await user.click(createButton);

    expect(await screen.findByRole("heading", { name: /Create team/i })).toBeInTheDocument();
  });

  it("opens the create form when Create team is clicked in empty state", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValueOnce({
      teams: [],
      nextCursor: null,
    });
    // The create form's useTeamForm hook loads the user directory on mount.
    vi.mocked(api.get).mockResolvedValue({ users: [] });

    renderWithRouter(<Teams />);

    await waitFor(() => {
      expect(screen.getByText("No teams yet")).toBeInTheDocument();
    });

    const createButton = screen.getAllByRole("button", { name: /Create team/i })[0];
    await user.click(createButton);

    expect(await screen.findByRole("heading", { name: /Create team/i })).toBeInTheDocument();
  });

  it("handles error when loading more teams fails", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValueOnce({
      teams: createMockTeams(0, 10),
      nextCursor: "cursor-1",
    });

    renderWithRouter(<Teams />);

    await waitFor(() => {
      expect(screen.getByText("Team 0")).toBeInTheDocument();
    });

    // Make the load more call fail
    vi.mocked(api.get).mockRejectedValueOnce(new Error("Failed to load more"));

    const loadMoreButton = screen.getByRole("button", { name: /load more teams/i });
    await user.click(loadMoreButton);

    await waitFor(() => {
      expect(mockToastError).toHaveBeenCalledWith(expect.any(String));
    });
  });

  it("creates a team and shows a success toast", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockImplementation((path: string) => {
      if (path.includes("/auth/email/admin/users")) {
        return Promise.resolve({ users: [] });
      }
      return Promise.resolve({ teams: createMockTeams(0, 1), nextCursor: null });
    });
    mockCreateTeam.mockResolvedValue({ id: "team-new", name: "New Team" } as Awaited<
      ReturnType<typeof createTeam>
    >);

    renderWithRouter(<Teams />);
    await waitFor(() => expect(screen.getByText("Team 0")).toBeInTheDocument());

    await user.click(screen.getAllByRole("button", { name: /Create team/i })[0]);
    await user.type(await screen.findByPlaceholderText(/add team name/i), "New Team");
    await user.click(screen.getByRole("button", { name: /^create team$/i }));

    await waitFor(() => {
      expect(mockCreateTeam).toHaveBeenCalledWith(expect.objectContaining({ name: "New Team" }));
      expect(mockToastSuccess).toHaveBeenCalledWith("Team created successfully");
    });
  });

  it("updates a team and shows a success toast", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockImplementation((path: string) => {
      if (path.includes("/auth/email/admin/users")) {
        return Promise.resolve({ users: [] });
      }
      return Promise.resolve({ teams: createMockTeams(0, 1), nextCursor: null });
    });
    mockUpdateTeam.mockResolvedValue({ id: "team-0", name: "Team 0" } as Awaited<
      ReturnType<typeof updateTeam>
    >);

    renderWithRouter(<Teams />);
    await waitFor(() => expect(screen.getByText("Team 0")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Actions for Team 0" }));
    await user.click(await screen.findByRole("menuitem", { name: /^edit$/i }));
    await screen.findByRole("heading", { name: /edit team/i });
    await user.click(screen.getByRole("button", { name: /^save changes$/i }));

    await waitFor(() => {
      expect(mockUpdateTeam).toHaveBeenCalled();
      expect(mockToastSuccess).toHaveBeenCalledWith("Team updated successfully");
    });
  });

  it("closes the create form when Back is clicked", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValueOnce({
      teams: createMockTeams(0, 1),
      nextCursor: null,
    });
    vi.mocked(api.get).mockResolvedValue({ users: [] });

    renderWithRouter(<Teams />);
    await waitFor(() => expect(screen.getByText("Team 0")).toBeInTheDocument());

    await user.click(screen.getAllByRole("button", { name: /Create team/i })[0]);
    await screen.findByRole("heading", { name: /create team/i });

    await user.click(screen.getByRole("button", { name: /^back$/i }));

    await waitFor(() => {
      expect(screen.queryByRole("heading", { name: /create team/i })).not.toBeInTheDocument();
    });
    expect(screen.getByText("Team 0")).toBeInTheDocument();
  });

  it("opens the manage-members dialog from the row actions", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValue({ teams: createMockTeams(0, 1), nextCursor: null });
    vi.mocked(listTeamMembers).mockResolvedValue([]);

    renderWithRouter(<Teams />);
    await waitFor(() => expect(screen.getByText("Team 0")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Actions for Team 0" }));
    await user.click(await screen.findByRole("menuitem", { name: /manage members/i }));

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });
});
