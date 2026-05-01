import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { render } from "@testing-library/react";
import { Servers } from "./Servers";
import { RouterProvider } from "@/router";
import { I18nProvider } from "@/i18n";
import type { ReactElement } from "react";

// Mock the api client to avoid AbortSignal issues with MSW in Node.js
vi.mock("@/api/client", () => ({
  api: {
    get: vi.fn(),
    delete: vi.fn(),
    post: vi.fn(),
  },
}));

import { api } from "@/api/client";

// Helper to create mock servers
function createMockServers(startId: number, count: number) {
  return Array.from({ length: count }, (_, i) => ({
    id: startId + i,
    name: `Test Server ${startId + i}`,
    url: `http://test${startId + i}.example.com`,
    status: "active",
  }));
}

// Helper to render with real router
function renderWithRouter(ui: ReactElement) {
  // Set up initial route
  window.history.pushState({}, "", "/app/servers");

  return render(
    <RouterProvider>
      <I18nProvider>{ui}</I18nProvider>
    </RouterProvider>,
  );
}

describe("Servers", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders servers list when data is loaded", async () => {
    // Mock the initial servers fetch - useQuery expects direct response, not wrapped in data
    vi.mocked(api.get).mockResolvedValueOnce({
      gateways: createMockServers(0, 25),
      nextCursor: "cursor-1",
    });

    renderWithRouter(<Servers />);

    await waitFor(() => {
      expect(screen.getByText("Test Server 0")).toBeInTheDocument();
    });

    expect(screen.getByText("MCP Servers")).toBeInTheDocument();
  });

  it("loads more servers when Load More button is clicked", async () => {
    const user = userEvent.setup();

    // Mock the initial servers fetch
    vi.mocked(api.get).mockResolvedValueOnce({
      gateways: createMockServers(0, 25),
      nextCursor: "cursor-1",
    });

    renderWithRouter(<Servers />);

    await waitFor(() => {
      expect(screen.getByText("Test Server 0")).toBeInTheDocument();
    });

    const loadMoreButton = screen.getByRole("button", { name: /load more/i });
    expect(loadMoreButton).toBeInTheDocument();

    // Mock the second page fetch
    vi.mocked(api.get).mockResolvedValueOnce({
      gateways: createMockServers(25, 25),
      nextCursor: null,
    });

    await user.click(loadMoreButton);

    await waitFor(() => {
      expect(screen.getByText("Test Server 25")).toBeInTheDocument();
    });
  });
});
