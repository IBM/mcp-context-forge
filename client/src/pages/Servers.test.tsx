import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
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

const mockServerDetails = {
  id: "server-0",
  name: "Test Server 0",
  url: "http://test0.example.com",
  transport: "SSE" as const,
  enabled: true,
  reachable: true,
  toolCount: 5,
  visibility: "public" as const,
  createdAt: "2024-01-01T00:00:00Z",
  updatedAt: "2024-01-01T00:00:00Z",
  team: "Engineering",
  owner_email: "test@example.com",
};

// Helper to create mock servers
function createMockServers(startId: number, count: number) {
  return Array.from({ length: count }, (_, i) => ({
    id: `server-${startId + i}`,
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

  it("opens details panel when View Details is clicked", async () => {
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

    // Components fetches fire first (panel child effects run before parent detail effect).
    vi.mocked(api.get).mockResolvedValueOnce({ tools: [] });
    vi.mocked(api.get).mockResolvedValueOnce({ resources: [] });
    vi.mocked(api.get).mockResolvedValueOnce({ prompts: [] });
    vi.mocked(api.get).mockResolvedValueOnce(mockServerDetails);

    // Find the first server row's actions menu
    const actionsButtons = screen.getAllByRole("button", { name: /actions for/i });
    await user.click(actionsButtons[0]);

    // Click View Details menu item
    const viewDetailsItem = await screen.findByRole("menuitem", { name: /view details/i });
    await user.click(viewDetailsItem);

    // Drawer should open with server details
    await waitFor(() => {
      expect(screen.getByText("Details")).toBeInTheDocument();
    });
  });

  it("closes details panel when close button is clicked", async () => {
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

    // Components fetches fire first (panel child effects run before parent detail effect).
    vi.mocked(api.get).mockResolvedValueOnce({ tools: [] });
    vi.mocked(api.get).mockResolvedValueOnce({ resources: [] });
    vi.mocked(api.get).mockResolvedValueOnce({ prompts: [] });
    vi.mocked(api.get).mockResolvedValueOnce(mockServerDetails);

    // Open details drawer
    const actionsButtons = screen.getAllByRole("button", { name: /actions for/i });
    await user.click(actionsButtons[0]);

    const viewDetailsItem = await screen.findByRole("menuitem", { name: /view details/i });
    await user.click(viewDetailsItem);

    await waitFor(() => {
      expect(screen.getByText("Details")).toBeInTheDocument();
    });

    // Close drawer
    const closeButton = screen.getByRole("button", { name: /close mcp server details/i });
    await user.click(closeButton);

    // Drawer should close
    await waitFor(() => {
      expect(
        screen.queryByRole("button", { name: /close mcp server details/i }),
      ).not.toBeInTheDocument();
    });
  });

  it("shows inline error notification when toggleEnabled fails", async () => {
    const user = userEvent.setup();

    vi.mocked(api.get).mockResolvedValueOnce({
      gateways: [{ ...createMockServers(0, 1)[0], enabled: true }],
      nextCursor: null,
    });

    renderWithRouter(<Servers />);

    await waitFor(() => {
      expect(screen.getByText("Test Server 0")).toBeInTheDocument();
    });

    vi.mocked(api.post).mockRejectedValueOnce(new Error("403 Forbidden"));

    const actionsButtons = screen.getAllByRole("button", { name: /actions for/i });
    await user.click(actionsButtons[0]);

    const deactivateItem = await screen.findByRole("menuitem", { name: /deactivate/i });
    await user.click(deactivateItem);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
      expect(screen.getByText(/you don't have permission/i)).toBeInTheDocument();
    });
  });

  it("shows inline error notification when testConnection fails", async () => {
    const user = userEvent.setup();

    vi.mocked(api.get).mockResolvedValueOnce({
      gateways: createMockServers(0, 1),
      nextCursor: null,
    });

    renderWithRouter(<Servers />);

    await waitFor(() => {
      expect(screen.getByText("Test Server 0")).toBeInTheDocument();
    });

    vi.mocked(api.post).mockRejectedValueOnce(new Error("500 Internal Server Error"));

    const actionsButtons = screen.getAllByRole("button", { name: /actions for/i });
    await user.click(actionsButtons[0]);

    const testItem = await screen.findByRole("menuitem", { name: /test connection/i });
    await user.click(testItem);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
      expect(screen.getByText(/server error/i)).toBeInTheDocument();
    });
  });

  it("displays server metadata in details panel", async () => {
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

    // Components fetches fire first (panel child effects run before parent detail effect).
    vi.mocked(api.get).mockResolvedValueOnce({ tools: [] });
    vi.mocked(api.get).mockResolvedValueOnce({ resources: [] });
    vi.mocked(api.get).mockResolvedValueOnce({ prompts: [] });
    vi.mocked(api.get).mockResolvedValueOnce(mockServerDetails);

    // Open details drawer
    const actionsButtons = screen.getAllByRole("button", { name: /actions for/i });
    await user.click(actionsButtons[0]);

    const viewDetailsItem = await screen.findByRole("menuitem", { name: /view details/i });
    await user.click(viewDetailsItem);

    // Check for server metadata inside the details panel region
    const detailsPanel = await screen.findByRole("region", { name: /test server 0/i });
    await waitFor(() => {
      const panel = within(detailsPanel);
      expect(panel.getByText("Active")).toBeInTheDocument();
      expect(panel.getByText("Public")).toBeInTheDocument();
      expect(panel.getByText("Server-Sent Events (SSE)")).toBeInTheDocument();
      expect(panel.getByText("Engineering")).toBeInTheDocument();
      expect(panel.getByText("test@example.com")).toBeInTheDocument();
    });
  });
});
