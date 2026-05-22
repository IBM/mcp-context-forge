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
});
