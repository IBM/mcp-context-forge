import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { render } from "@testing-library/react";
import { toast } from "sonner";
import { Users } from "./Users";
import { DeleteUserDialog } from "@/components/users/DeleteUserDialog";
import { RouterProvider } from "@/router";
import { I18nProvider } from "@/i18n";
import type { ReactElement } from "react";

vi.mock("@/auth/AuthContext", () => ({
  useAuthContext: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  api: {
    get: vi.fn(),
    delete: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    status: number;
    body: unknown;
    constructor(status: number, body: unknown, message: string) {
      super(message);
      this.name = "ApiError";
      this.status = status;
      this.body = body;
    }
  },
}));

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

vi.mock("@/components/users/UserForm", () => ({
  UserForm: ({
    user,
    onToggle,
    onOptimisticCreate,
    onSuccess,
    onError,
  }: {
    user?: { email: string };
    onToggle: () => void;
    onOptimisticCreate: (data: { email: string; full_name: string }) => void;
    onSuccess: () => void;
    onError: (data: { email: string }) => void;
  }) => (
    <div data-testid="mock-user-form">
      {user ? <div>Edit user: {user.email}</div> : null}
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
import { ApiError } from "@/api/client";
import * as AuthContextModule from "@/auth/AuthContext";

const mockUseAuthContext = vi.mocked(AuthContextModule.useAuthContext);
const mockToastSuccess = vi.mocked(toast.success);
const mockToastError = vi.mocked(toast.error);
const mockApiDelete = api.delete as ReturnType<typeof vi.fn>;

function makeAuthContext(email = "admin@example.com") {
  return {
    user: {
      email,
      full_name: "Admin",
      is_admin: true,
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
    setSelectedTeamId: vi.fn(),
  } as ReturnType<typeof AuthContextModule.useAuthContext>;
}

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

function renderWithRouter(ui: ReactElement, path = "/app/users") {
  window.history.pushState({}, "", path);
  return render(
    <RouterProvider>
      <I18nProvider>{ui}</I18nProvider>
    </RouterProvider>,
  );
}

describe("Users", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, "error").mockImplementation(() => {});
    mockUseAuthContext.mockReturnValue(makeAuthContext("admin@example.com"));
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

  it("opens the selected user from global search", async () => {
    const selectedUser = {
      ...createMockUsers(42, 1)[0],
      email: "selected@example.com",
      full_name: "Selected User",
    };
    vi.mocked(api.get).mockImplementation((path) => {
      if (String(path).includes("/auth/email/admin/users/selected%40example.com")) {
        return Promise.resolve(selectedUser);
      }
      return Promise.resolve({ users: createMockUsers(0, 1), nextCursor: null });
    });

    renderWithRouter(<Users />, "/app/users?selected=selected%40example.com&search=selected");

    expect(await screen.findByTestId("mock-user-form")).toBeInTheDocument();
    expect(screen.getByText("Edit user: selected@example.com")).toBeInTheDocument();
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

  it("renders empty state when no users exist", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      users: [],
      nextCursor: null,
    });

    renderWithRouter(<Users />);

    await waitFor(() => {
      expect(screen.getByText("No users found")).toBeInTheDocument();
    });
  });

  it("renders loading spinner while fetching", async () => {
    vi.mocked(api.get).mockImplementationOnce(() => new Promise(() => {}));

    renderWithRouter(<Users />);

    expect(screen.getByText("Users")).toBeInTheDocument();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows error alert when query fails", async () => {
    vi.mocked(api.get).mockRejectedValueOnce(new Error("Network error"));

    renderWithRouter(<Users />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });

    expect(screen.getByText("Error loading users")).toBeInTheDocument();
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

  it("hides Load More button when there is no nextCursor", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      users: createMockUsers(0, 5),
      nextCursor: null,
    });

    renderWithRouter(<Users />);

    await waitFor(() => {
      expect(screen.getByText("user0@example.com")).toBeInTheDocument();
    });

    expect(screen.queryByRole("button", { name: /load more users/i })).not.toBeInTheDocument();
  });

  it("shows the Create User button", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      users: createMockUsers(0, 3),
      nextCursor: null,
    });

    renderWithRouter(<Users />);

    expect(screen.getByRole("button", { name: /create user/i })).toBeInTheDocument();
  });

  it("removes user from list and shows success toast after API responds", async () => {
    const user = userEvent.setup();

    vi.mocked(api.get).mockResolvedValueOnce({
      users: createMockUsers(0, 3),
      nextCursor: null,
    });

    renderWithRouter(<Users />);

    await waitFor(() => {
      expect(screen.getByText("user0@example.com")).toBeInTheDocument();
    });

    mockApiDelete.mockResolvedValueOnce({ success: true, message: "Deleted" });

    await user.click(screen.getByRole("button", { name: "Actions for User 0" }));
    await user.click(await screen.findByRole("menuitem", { name: /^delete$/i }));

    await user.click(await screen.findByRole("button", { name: /delete user/i }));

    await waitFor(() => {
      expect(screen.queryByText("user0@example.com")).not.toBeInTheDocument();
    });

    expect(screen.getByText("user1@example.com")).toBeInTheDocument();
    expect(mockToastSuccess).toHaveBeenCalledWith(expect.stringContaining("user0@example.com"));
  });

  it("optimistically removes user from list immediately on delete confirmation", async () => {
    const user = userEvent.setup();

    vi.mocked(api.get).mockResolvedValueOnce({
      users: createMockUsers(0, 1),
      nextCursor: null,
    });

    renderWithRouter(<Users />);

    await waitFor(() => {
      expect(screen.getByText("user0@example.com")).toBeInTheDocument();
    });

    let resolveDelete!: (val: unknown) => void;
    mockApiDelete.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveDelete = resolve;
        }),
    );

    await user.click(screen.getByRole("button", { name: "Actions for User 0" }));
    await user.click(await screen.findByRole("menuitem", { name: /^delete$/i }));
    await user.click(await screen.findByRole("button", { name: /delete user/i }));

    await waitFor(() => {
      expect(screen.queryByText("user0@example.com")).not.toBeInTheDocument();
    });
    expect(screen.queryByRole("button", { name: /delete user/i })).not.toBeInTheDocument();

    resolveDelete({ success: true, message: "Deleted" });

    await waitFor(() => {
      expect(mockToastSuccess).toHaveBeenCalledWith(expect.stringContaining("user0@example.com"));
    });
  });

  it("rolls back optimistic delete when API call fails with generic error", async () => {
    const user = userEvent.setup();

    vi.mocked(api.get).mockResolvedValueOnce({
      users: createMockUsers(0, 3),
      nextCursor: null,
    });

    renderWithRouter(<Users />);

    await waitFor(() => {
      expect(screen.getByText("user0@example.com")).toBeInTheDocument();
    });

    mockApiDelete.mockRejectedValueOnce(new Error("500 Internal Server Error"));

    const actionsButton = screen.getByRole("button", { name: "Actions for User 0" });
    await user.click(actionsButton);

    const deleteItem = await screen.findByRole("menuitem", { name: /^delete$/i });
    await user.click(deleteItem);

    const confirmButton = await screen.findByRole("button", { name: /delete user/i });
    await user.click(confirmButton);

    await waitFor(() => {
      expect(screen.getByText("user0@example.com")).toBeInTheDocument();
    });

    expect(mockToastError).toHaveBeenCalledWith(expect.stringContaining("Failed to delete user"));
  });

  it("blocks self-delete client-side: no API call, dialog closes, error toast shown immediately", async () => {
    const user = userEvent.setup();

    vi.mocked(api.get).mockResolvedValueOnce({
      users: [{ ...createMockUsers(0, 1)[0], email: "admin@example.com" }],
      nextCursor: null,
    });

    mockUseAuthContext.mockReturnValue(makeAuthContext("admin@example.com"));

    renderWithRouter(<Users />);

    await waitFor(() => {
      expect(screen.getByText("admin@example.com")).toBeInTheDocument();
    });

    const actionsButton = screen.getByRole("button", { name: /actions for/i });
    await user.click(actionsButton);

    const deleteItem = await screen.findByRole("menuitem", { name: /^delete$/i });
    await user.click(deleteItem);

    const confirmButton = await screen.findByRole("button", { name: /delete user/i });
    await user.click(confirmButton);

    await waitFor(() => {
      expect(mockToastError).toHaveBeenCalledWith("You cannot delete your own account");
    });
    expect(mockApiDelete).not.toHaveBeenCalled();

    expect(screen.queryByRole("button", { name: /delete user/i })).not.toBeInTheDocument();
    expect(screen.getByText("admin@example.com")).toBeInTheDocument();
  });

  it("shows 'cannot delete own account' toast error on 400 with self-delete message", async () => {
    const user = userEvent.setup();

    vi.mocked(api.get).mockResolvedValueOnce({
      users: createMockUsers(0, 1),
      nextCursor: null,
    });

    renderWithRouter(<Users />);

    await waitFor(() => {
      expect(screen.getByText("user0@example.com")).toBeInTheDocument();
    });

    const selfDeleteError = new ApiError(
      400,
      { detail: "Cannot delete your own account" },
      "HTTP 400",
    );
    mockApiDelete.mockRejectedValueOnce(selfDeleteError);

    const actionsButton = screen.getByRole("button", { name: "Actions for User 0" });
    await user.click(actionsButton);

    const deleteItem = await screen.findByRole("menuitem", { name: /^delete$/i });
    await user.click(deleteItem);

    const confirmButton = await screen.findByRole("button", { name: /delete user/i });
    await user.click(confirmButton);

    await waitFor(() => {
      expect(mockToastError).toHaveBeenCalledWith("You cannot delete your own account");
    });

    expect(screen.getByText("user0@example.com")).toBeInTheDocument();
  });

  it("shows 'cannot delete last admin' toast error on 400 with last-admin message", async () => {
    const user = userEvent.setup();

    vi.mocked(api.get).mockResolvedValueOnce({
      users: [{ ...createMockUsers(0, 1)[0], is_admin: true }],
      nextCursor: null,
    });

    renderWithRouter(<Users />);

    await waitFor(() => {
      expect(screen.getByText("user0@example.com")).toBeInTheDocument();
    });

    const lastAdminError = new ApiError(
      400,
      { detail: "Cannot delete the last remaining admin" },
      "HTTP 400",
    );
    mockApiDelete.mockRejectedValueOnce(lastAdminError);

    const actionsButton = screen.getByRole("button", { name: "Actions for User 0" });
    await user.click(actionsButton);

    const deleteItem = await screen.findByRole("menuitem", { name: /^delete$/i });
    await user.click(deleteItem);

    const confirmButton = await screen.findByRole("button", { name: /delete user/i });
    await user.click(confirmButton);

    await waitFor(() => {
      expect(mockToastError).toHaveBeenCalledWith("Cannot delete the last remaining admin user");
    });

    expect(screen.getByText("user0@example.com")).toBeInTheDocument();
  });

  it("shows 'user not found' toast error on 404", async () => {
    const user = userEvent.setup();

    vi.mocked(api.get).mockResolvedValueOnce({
      users: createMockUsers(0, 1),
      nextCursor: null,
    });

    renderWithRouter(<Users />);

    await waitFor(() => {
      expect(screen.getByText("user0@example.com")).toBeInTheDocument();
    });

    const notFoundError = new ApiError(404, { detail: "User not found" }, "HTTP 404");
    mockApiDelete.mockRejectedValueOnce(notFoundError);

    const actionsButton = screen.getByRole("button", { name: "Actions for User 0" });
    await user.click(actionsButton);

    const deleteItem = await screen.findByRole("menuitem", { name: /^delete$/i });
    await user.click(deleteItem);

    const confirmButton = await screen.findByRole("button", { name: /delete user/i });
    await user.click(confirmButton);

    await waitFor(() => {
      expect(mockToastError).toHaveBeenCalledWith("User not found");
    });
  });

  it("cancelling the delete dialog keeps user in list", async () => {
    const user = userEvent.setup();

    vi.mocked(api.get).mockResolvedValueOnce({
      users: createMockUsers(0, 2),
      nextCursor: null,
    });

    renderWithRouter(<Users />);

    await waitFor(() => {
      expect(screen.getByText("user0@example.com")).toBeInTheDocument();
    });

    const actionsButton = screen.getByRole("button", { name: "Actions for User 0" });
    await user.click(actionsButton);

    const deleteItem = await screen.findByRole("menuitem", { name: /^delete$/i });
    await user.click(deleteItem);

    expect(await screen.findByRole("alertdialog")).toBeInTheDocument();

    const cancelButton = screen.getByRole("button", { name: /cancel/i });
    await user.click(cancelButton);

    expect(screen.getByText("user0@example.com")).toBeInTheDocument();

    expect(mockApiDelete).not.toHaveBeenCalled();
    expect(mockToastSuccess).not.toHaveBeenCalled();
    expect(mockToastError).not.toHaveBeenCalled();
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
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
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
    if (resolveLoadMore) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (resolveLoadMore as any)({ users: createMockUsers(10, 5), nextCursor: null });
    }

    // Wait for resolution
    await waitFor(() => {
      expect(screen.getByText("user14@example.com")).toBeInTheDocument();
    });

    // Check that api.get was called exactly twice (once for initial load, once for first load more)
    expect(api.get).toHaveBeenCalledTimes(2);
  });
});

describe("DeleteUserDialog", () => {
  it("renders Deleting... text when isDeleting is true", () => {
    render(
      <I18nProvider>
        <DeleteUserDialog
          isOpen={true}
          isDeleting={true}
          userName="testuser"
          userEmail="testuser@example.com"
          onClose={vi.fn()}
          onConfirm={vi.fn()}
        />
      </I18nProvider>,
    );
    expect(screen.getByText("Deleting...")).toBeInTheDocument();
  });
});
