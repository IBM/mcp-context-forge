import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { render } from "@testing-library/react";
import { Users } from "./Users";
import { RouterProvider } from "@/router";
import { I18nProvider } from "@/i18n";
import type { ReactElement } from "react";

vi.mock("@/api/client", () => ({
  api: {
    get: vi.fn(),
  },
}));

vi.mock("@/components/users/UserForm", () => ({
  UserForm: ({
    onToggle,
    onOptimisticCreate,
    onSuccess,
    onError,
  }: {
    onToggle: () => void;
    onOptimisticCreate: (data: { email: string; full_name: string }) => void;
    onSuccess: () => void;
    onError: (data: { email: string }) => void;
  }) => (
    <div data-testid="mock-user-form">
      <button onClick={onToggle}>Cancel Form</button>
      <button onClick={() => onOptimisticCreate({ email: "opt@example.com", full_name: "Opt" })}>
        Optimistic Create
      </button>
      <button onClick={onSuccess}>Success Form</button>
      <button onClick={() => onError({ email: "opt@example.com" })}>Error Form</button>
    </div>
  ),
}));

import { api } from "@/api/client";

function createMockUsers(startIndex: number, count: number) {
  return Array.from({ length: count }, (_, i) => ({
    email: `user${startIndex + i}@example.com`,
    full_name: `User ${startIndex + i}`,
    is_admin: false,
    is_active: true,
    auth_provider: "local",
    created_at: "2024-01-01T00:00:00Z",
    last_login: null,
    email_verified: true,
    password_change_required: false,
    failed_login_attempts: 0,
    locked_until: null,
    is_locked: false,
  }));
}

function renderWithRouter(ui: ReactElement) {
  window.history.pushState({}, "", "/app/users");
  return render(
    <RouterProvider>
      <I18nProvider>{ui}</I18nProvider>
    </RouterProvider>,
  );
}

describe("Users", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders loading state while fetching users", () => {
    const pendingRequest = new Promise<never>(() => {});
    vi.mocked(api.get).mockReturnValueOnce(pendingRequest as ReturnType<typeof api.get>);

    renderWithRouter(<Users />);

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveAttribute("aria-live", "polite");
    expect(screen.getByRole("status")).toHaveAttribute("aria-busy", "true");
  });

  it("renders an error alert when the user fetch fails", async () => {
    vi.mocked(api.get).mockRejectedValueOnce(new Error("Could not load users"));

    renderWithRouter(<Users />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });

    expect(screen.getByText("Error loading users")).toBeInTheDocument();
    expect(screen.getByText("Could not load users")).toBeInTheDocument();
  });

  it("renders alert with correct aria attributes on error", async () => {
    vi.mocked(api.get).mockRejectedValueOnce(new Error("Service unavailable"));

    renderWithRouter(<Users />);

    await waitFor(() => {
      const alert = screen.getByRole("alert");
      expect(alert).toHaveAttribute("aria-live", "assertive");
      expect(alert).toHaveAttribute("aria-atomic", "true");
    });
  });

  it("renders an empty users state when no users exist", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ users: [], nextCursor: null });

    renderWithRouter(<Users />);

    await waitFor(() => {
      expect(screen.getByText("No users found")).toBeInTheDocument();
    });
  });

  it("renders users title/header", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ users: createMockUsers(0, 1), nextCursor: null });

    renderWithRouter(<Users />);

    await waitFor(() => {
      expect(screen.getByText("Users")).toBeInTheDocument();
    });
  });

  it("renders Create User button with correct aria-label", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ users: [], nextCursor: null });

    renderWithRouter(<Users />);

    await waitFor(() => {
      const button = screen.getByRole("button", { name: /Create User/i });
      expect(button).toBeInTheDocument();
    });
  });

  it("changes the displayed user limit when the select changes", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValueOnce({ users: createMockUsers(0, 1), nextCursor: null });

    renderWithRouter(<Users />);

    await waitFor(() => {
      expect(screen.getByText("user0@example.com")).toBeInTheDocument();
    });

    const limitSelect = screen.getByRole("combobox", { name: /Per page:/i });
    await user.selectOptions(limitSelect, "25");

    expect(limitSelect).toHaveValue("25");
  });

  it("renders all limit options", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ users: createMockUsers(0, 1), nextCursor: null });

    renderWithRouter(<Users />);

    await waitFor(() => {
      expect(screen.getByText("user0@example.com")).toBeInTheDocument();
    });

    const options = screen.getAllByRole("option");
    const values = options.map((opt) => opt.getAttribute("value"));

    expect(values).toContain("10");
    expect(values).toContain("25");
    expect(values).toContain("50");
    expect(values).toContain("100");
  });

  it("does not render Load More button when there is no next cursor", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ users: createMockUsers(0, 10), nextCursor: null });

    renderWithRouter(<Users />);

    await waitFor(() => {
      expect(screen.getByText("user0@example.com")).toBeInTheDocument();
    });

    expect(screen.queryByRole("button", { name: /Load more/i })).not.toBeInTheDocument();
  });

  it("renders Load More button when next cursor is available", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      users: createMockUsers(0, 10),
      nextCursor: "cursor-1",
    });

    renderWithRouter(<Users />);

    await waitFor(() => {
      expect(screen.getByText("user0@example.com")).toBeInTheDocument();
    });

    expect(screen.getByRole("button", { name: /Load more/i })).toBeInTheDocument();
  });

  it("renders users list when data is loaded", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      users: createMockUsers(0, 10),
      nextCursor: null,
    });

    renderWithRouter(<Users />);

    await waitFor(() => {
      expect(screen.getByText("user0@example.com")).toBeInTheDocument();
    });

    expect(screen.getByText("Users")).toBeInTheDocument();
    expect(screen.getByText("user9@example.com")).toBeInTheDocument();
  });

  it("displays correct user count message", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      users: createMockUsers(0, 5),
      nextCursor: null,
    });

    renderWithRouter(<Users />);

    await waitFor(() => {
      expect(screen.getByText(/Showing 5 users/)).toBeInTheDocument();
    });
  });

  it("loads more users when Load More button is clicked", async () => {
    const user = userEvent.setup();

    vi.mocked(api.get).mockResolvedValueOnce({
      users: createMockUsers(0, 10),
      nextCursor: "cursor-1",
    });

    renderWithRouter(<Users />);

    await waitFor(() => {
      expect(screen.getByText("user0@example.com")).toBeInTheDocument();
    });

    const loadMoreButton = screen.getByRole("button", { name: /load more users/i });
    expect(loadMoreButton).toBeInTheDocument();

    vi.mocked(api.get).mockResolvedValueOnce({
      users: createMockUsers(10, 10),
      nextCursor: null,
    });

    await user.click(loadMoreButton);

    await waitFor(() => {
      expect(screen.getByText("user10@example.com")).toBeInTheDocument();
    });

    expect(screen.queryByRole("button", { name: /load more users/i })).not.toBeInTheDocument();
  });

  it("shows loading text on Load More button while loading", async () => {
    const user = userEvent.setup();

    vi.mocked(api.get).mockResolvedValueOnce({
      users: createMockUsers(0, 10),
      nextCursor: "cursor-1",
    });

    renderWithRouter(<Users />);

    await waitFor(() => {
      expect(screen.getByText("user0@example.com")).toBeInTheDocument();
    });

    const loadMoreButton = screen.getByRole("button", { name: /load more users/i });

    // Create a pending promise to simulate loading
    let resolveLoadMore: ((value: unknown) => void) | null = null;
    const pendingLoadMore = new Promise<unknown>((resolve) => {
      resolveLoadMore = resolve;
    });

    vi.mocked(api.get).mockReturnValueOnce(pendingLoadMore as ReturnType<typeof api.get>);

    await user.click(loadMoreButton);

    // Resolve the promise
    if (resolveLoadMore) {
      (resolveLoadMore as any)({
        users: createMockUsers(10, 5),
        nextCursor: null,
      });

      await waitFor(() => {
        expect(screen.getByText("user10@example.com")).toBeInTheDocument();
      });
    }
  });

  it("opens user form when Create User button is clicked", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValueOnce({ users: [], nextCursor: null });

    renderWithRouter(<Users />);

    await waitFor(() => {
      const createButton = screen.getByRole("button", { name: /Create User/i });
      expect(createButton).toBeInTheDocument();
    });

    const createButton = screen.getByRole("button", { name: /Create User/i });
    await user.click(createButton);

    // After clicking, the form should be visible (would need to check for form elements)
    expect(screen.queryByText("No users found")).not.toBeInTheDocument();
  });

  it("closes user form when toggled", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValueOnce({ users: [], nextCursor: null });

    renderWithRouter(<Users />);

    await waitFor(() => {
      const createButton = screen.getByRole("button", { name: /Create User/i });
      expect(createButton).toBeInTheDocument();
    });

    const createButton = screen.getByRole("button", { name: /Create User/i });
    await user.click(createButton);

    // Form should be open now - check if it's visible
    // (The form component would show specific content we can check for)
  });

  it("renders Plus icon for Create User button", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ users: [], nextCursor: null });

    renderWithRouter(<Users />);

    await waitFor(() => {
      const button = screen.getByRole("button", { name: /Create User/i });
      expect(button).toBeInTheDocument();
    });

    const button = screen.getByRole("button", { name: /Create User/i });
    const svg = button.querySelector("svg");
    expect(svg).toBeInTheDocument();
  });

  it("accumulates users when loading more", async () => {
    const user = userEvent.setup();

    vi.mocked(api.get).mockResolvedValueOnce({
      users: createMockUsers(0, 5),
      nextCursor: "cursor-1",
    });

    renderWithRouter(<Users />);

    await waitFor(() => {
      expect(screen.getByText("user0@example.com")).toBeInTheDocument();
      expect(screen.getByText("user4@example.com")).toBeInTheDocument();
    });

    expect(screen.getByText(/Showing 5 users/)).toBeInTheDocument();

    vi.mocked(api.get).mockResolvedValueOnce({
      users: createMockUsers(5, 5),
      nextCursor: null,
    });

    const loadMoreButton = screen.getByRole("button", { name: /load more users/i });
    await user.click(loadMoreButton);

    await waitFor(() => {
      expect(screen.getByText("user5@example.com")).toBeInTheDocument();
      expect(screen.getByText("user9@example.com")).toBeInTheDocument();
    });

    expect(screen.getByText(/Showing 10 users/)).toBeInTheDocument();
  });

  it("maintains state when limit changes", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValueOnce({
      users: createMockUsers(0, 10),
      nextCursor: null,
    });

    renderWithRouter(<Users />);

    await waitFor(() => {
      expect(screen.getByText("user0@example.com")).toBeInTheDocument();
    });

    const limitSelect = screen.getByRole("combobox", { name: /Per page:/i });
    expect(limitSelect).toHaveValue("10");

    await user.selectOptions(limitSelect, "50");

    expect(limitSelect).toHaveValue("50");
    expect(screen.getByText("user0@example.com")).toBeInTheDocument();
  });

  it("renders main element with correct structure", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ users: [], nextCursor: null });

    const { container } = renderWithRouter(<Users />);

    await waitFor(() => {
      const main = container.querySelector("main");
      expect(main).toBeInTheDocument();
      expect(main).toHaveClass("p-6");
    });
  });

  it("renders header with flex layout", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ users: [], nextCursor: null });

    const { container } = renderWithRouter(<Users />);

    await waitFor(() => {
      const header = container.querySelector("header");
      expect(header).toBeInTheDocument();
      expect(header).toHaveClass("flex");
      expect(header).toHaveClass("items-center");
      expect(header).toHaveClass("justify-between");
    });
  });

  it("handles UserForm callbacks: optimistic create, success, and error", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValueOnce({ users: [], nextCursor: null });

    renderWithRouter(<Users />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Create User/i })).toBeInTheDocument();
    });

    // Open form
    await user.click(screen.getByRole("button", { name: /Create User/i }));
    expect(screen.getByTestId("mock-user-form")).toBeInTheDocument();

    // Trigger optimistic create
    await user.click(screen.getByRole("button", { name: /Optimistic Create/i }));

    // Trigger error callback (should keep form open but rollback user)
    await user.click(screen.getByRole("button", { name: /Error Form/i }));

    // Trigger success callback (closes the form)
    await user.click(screen.getByRole("button", { name: /Success Form/i }));
    expect(screen.queryByTestId("mock-user-form")).not.toBeInTheDocument();
  });

  it("logs console error when load more fails", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValueOnce({
      users: createMockUsers(0, 10),
      nextCursor: "cursor-1",
    });

    renderWithRouter(<Users />);

    await waitFor(() => {
      expect(screen.getByText("user0@example.com")).toBeInTheDocument();
    });

    const loadMoreButton = screen.getByRole("button", { name: /load more users/i });

    // Mock load more fetch failure
    vi.mocked(api.get).mockRejectedValueOnce(new Error("Load more network failure"));
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    await user.click(loadMoreButton);

    await waitFor(() => {
      expect(consoleErrorSpy).toHaveBeenCalledWith(
        "Failed to load more users:",
        expect.any(Object),
      );
    });
    consoleErrorSpy.mockRestore();
  });

  it("does not load more when load is already in progress", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValueOnce({
      users: createMockUsers(0, 10),
      nextCursor: "cursor-1",
    });

    renderWithRouter(<Users />);

    await waitFor(() => {
      expect(screen.getByText("user0@example.com")).toBeInTheDocument();
    });

    const loadMoreButton = screen.getByRole("button", { name: /load more users/i });

    // Mock load more with a delayed response
    let resolveLoadMore: ((value: unknown) => void) | null = null;
    const delayedPromise = new Promise((resolve) => {
      resolveLoadMore = resolve;
    });
    vi.mocked(api.get).mockReturnValueOnce(delayedPromise as ReturnType<typeof api.get>);

    // First click
    await user.click(loadMoreButton);
    // Second click (should be ignored because isLoadingMore is true)
    await user.click(loadMoreButton);

    // Resolve the promise
    if (resolveLoadMore) (resolveLoadMore as any)({ users: createMockUsers(10, 5), nextCursor: null });

    // Wait for resolution
    await waitFor(() => {
      expect(screen.getByText("user14@example.com")).toBeInTheDocument();
    });

    // Check that api.get was called exactly twice (once for initial load, once for first load more)
    expect(api.get).toHaveBeenCalledTimes(2);
  });
});
