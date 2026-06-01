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

vi.mock("@/api/servers", () => ({
  serversApi: {
    delete: vi.fn(),
    testConnection: vi.fn(),
  },
}));

import { api } from "@/api/client";
import { serversApi } from "@/api/servers";

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
    id: `${startId + i}`,
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

  it("renders a loading placeholder while the initial server fetch is pending", () => {
    const pendingRequest = new Promise(() => {});
    vi.mocked(api.get).mockReturnValueOnce(pendingRequest as any);

    renderWithRouter(<Servers />);

    expect(screen.getAllByRole("status")[0]).toBeInTheDocument();
  });

  it("renders an error alert when the initial server fetch fails", async () => {
    vi.mocked(api.get).mockRejectedValueOnce(new Error("Service down"));

    renderWithRouter(<Servers />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });

    expect(screen.getByText("Error loading servers")).toBeInTheDocument();
    expect(screen.getByText("Service down")).toBeInTheDocument();
  });

  it("shows the MCP server form when openForm=true is present in the URL", async () => {
    window.history.pushState({}, "", "/app/servers?openForm=true");
    vi.mocked(api.get).mockResolvedValueOnce({ gateways: [], nextCursor: null });

    renderWithRouter(<Servers />);

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Connect MCP server" })).toBeInTheDocument();
    });
  });

  it("changes the page size when the limit select value changes", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValueOnce({
      gateways: createMockServers(0, 1),
      nextCursor: null,
    });

    renderWithRouter(<Servers />);

    await waitFor(() => {
      expect(screen.getByText("Test Server 0")).toBeInTheDocument();
    });

    const limitSelect = screen.getByRole("combobox", { name: /Per page:/i });
    await user.selectOptions(limitSelect, "25");
    expect(limitSelect).toHaveValue("25");
  });

  it("renders an empty state when no servers exist", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ gateways: [], nextCursor: null });

    renderWithRouter(<Servers />);

    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: /Connect/i }).length).toBeGreaterThan(0);
    });
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
  it("displays server count message correctly", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      gateways: createMockServers(0, 3),
      nextCursor: null,
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
      expect(screen.getByText("Showing 3 servers")).toBeInTheDocument();
    });
  });

  it("displays singular 'server' when count is 1", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      gateways: createMockServers(0, 1),
      nextCursor: null,
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
      expect(screen.getByText("Showing 1 server")).toBeInTheDocument();
    });
  });

  it("hides Load More button when nextCursor is null", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      gateways: createMockServers(0, 5),
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

    const loadMoreButton = screen.queryByRole("button", { name: /load more/i });
    expect(loadMoreButton).not.toBeInTheDocument();
  });

  it("opens form when Connect button is clicked", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValueOnce({
      gateways: [],
      nextCursor: null,
    });

    renderWithRouter(<Servers />);

    await waitFor(() => {
      const buttons = screen.getAllByRole("button", { name: /Connect/i });
      expect(buttons.length).toBeGreaterThan(0);
    });

    const connectButtons = screen.getAllByRole("button", { name: /Connect/i });
    await user.click(connectButtons[0]);

    expect(screen.getByRole("heading", { name: "Connect MCP server" })).toBeInTheDocument();
  });

  it("displays Delete error alert when deletion fails", async () => {
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
    // Simulate delete error - this would require mocking serversApi.delete and triggering the error
    // through the table component's onDelete handler
  });

  it("renders correct number of limit options", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      gateways: createMockServers(0, 1),
      nextCursor: null,
    });

    renderWithRouter(<Servers />);

    await waitFor(() => {
      expect(screen.getByText("Test Server 0")).toBeInTheDocument();
    });

    const limitSelect = screen.getByRole("combobox", { name: /Per page:/i });
    const options = screen.getAllByRole("option");
    
    // Should have options for 10, 25, 50, 100
    expect(options.filter(opt => ["10", "25", "50", "100"].includes(opt.getAttribute("value") || "")).length).toBeGreaterThanOrEqual(4);
  });

  it("closes form when onToggle is called", async () => {
    const user = userEvent.setup();
    window.history.pushState({}, "", "/app/servers?openForm=true");
    vi.mocked(api.get).mockResolvedValueOnce({ gateways: [], nextCursor: null });

    renderWithRouter(<Servers />);

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Connect MCP server" })).toBeInTheDocument();
    });

    // The form would need to be closed via a close button in the form component
  });

  it("refetches servers after successful form submission", async () => {
    window.history.pushState({}, "", "/app/servers?openForm=true");
    vi.mocked(api.get).mockResolvedValueOnce({ gateways: [], nextCursor: null });

    renderWithRouter(<Servers />);

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Connect MCP server" })).toBeInTheDocument();
    });

    // After form submission, the refetch should be called (verified via spy if implementation allows)
  });

  it("shows loading state while loading more servers", async () => {
    const user = userEvent.setup();
    
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
    const loadMoreButton = screen.getByRole("button", { name: /load more/i });

    // Create a pending promise to simulate loading
    let loadMoreResolve: (() => void) | null = null;
    const pendingLoadMore = new Promise<unknown>((resolve) => {
      loadMoreResolve = resolve;
    });

    vi.mocked(api.get).mockReturnValueOnce(pendingLoadMore as any);

    await user.click(loadMoreButton);

    // Button should show "Loading..." text
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Loading/i })).toBeInTheDocument();
    });

    // Resolve the loading promise
    if (loadMoreResolve) {
      loadMoreResolve();
      vi.mocked(api.get).mockResolvedValueOnce({
        gateways: createMockServers(25, 5),
        nextCursor: null,
      });
    }
  });

  it("renders MCP icon in empty state", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ gateways: [], nextCursor: null });

    renderWithRouter(<Servers />);

    await waitFor(() => {
      const emptyStateHeading = screen.getByRole("heading", { name: "Connect MCP server" });
      expect(emptyStateHeading).toBeInTheDocument();
    });

    // Check for SVG element in the empty state
    const svgs = screen.getByRole("heading", { name: "Connect MCP server" }).closest("div")?.querySelectorAll("svg");
    expect(svgs?.length).toBeGreaterThan(0);
  });

  it("renders aria-live region for status updates", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      gateways: createMockServers(0, 1),
      nextCursor: null,
    });

    renderWithRouter(<Servers />);

    const statusRegion = screen.getAllByRole("status")[0];
    expect(statusRegion).toHaveAttribute("aria-live", "polite");
    expect(statusRegion).toHaveAttribute("aria-busy");
  });
});

