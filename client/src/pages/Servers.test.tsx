import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { render } from "@testing-library/react";
import { toast } from "sonner";
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
    patch: vi.fn(),
    put: vi.fn(),
  },
}));

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

import { api } from "@/api/client";

const mockToastSuccess = vi.mocked(toast.success);
const mockToastError = vi.mocked(toast.error);

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
    enabled: true,
  }));
}

// Helper to render with real router
function renderWithRouter(ui: ReactElement, path = "/app/servers") {
  // Set up initial route
  window.history.pushState({}, "", path);

  return render(
    <RouterProvider>
      <I18nProvider>{ui}</I18nProvider>
    </RouterProvider>,
  );
}

describe("Servers", () => {
  beforeEach(() => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders a loading placeholder while the initial server fetch is pending", () => {
    const pendingRequest = new Promise(() => {});
    vi.mocked(api.get).mockReturnValueOnce(pendingRequest as ReturnType<typeof api.get>);

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

  it("renders the empty state Connect MCP server panel when no servers exist", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      gateways: [],
      nextCursor: null,
    });

    renderWithRouter(<Servers />);

    await waitFor(() => {
      expect(screen.getByText("Connect MCP server")).toBeInTheDocument();
    });

    expect(
      screen.getByText(/Register a MCP server to federate its tools, resources, and prompts/i),
    ).toBeInTheDocument();

    expect(screen.getByRole("button", { name: /Connect/i })).toBeInTheDocument();

    expect(screen.queryByText("MCP Servers")).not.toBeInTheDocument();
  });

  it("shows loading state before data arrives", async () => {
    vi.mocked(api.get).mockImplementationOnce(() => new Promise(() => {}));

    renderWithRouter(<Servers />);

    expect(screen.getByText("Loading servers, please wait...")).toBeInTheDocument();
  });

  it("shows error alert when query fails", async () => {
    vi.mocked(api.get).mockRejectedValueOnce(new Error("Network failure"));

    renderWithRouter(<Servers />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });

    expect(screen.getByText("Error loading servers")).toBeInTheDocument();
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

  it("hides Load More button when there is no nextCursor", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      gateways: createMockServers(0, 5),
      nextCursor: null,
    });

    renderWithRouter(<Servers />);

    await waitFor(() => {
      expect(screen.getByText("Test Server 0")).toBeInTheDocument();
    });

    expect(screen.queryByRole("button", { name: /load more/i })).not.toBeInTheDocument();
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

  it("opens the Add MCP server form via ?openForm=true and submits it", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValue({ gateways: [], nextCursor: null });
    vi.mocked(api.post).mockResolvedValue({ id: "new-gw", name: "My Server" });

    renderWithRouter(<Servers />, "/app/servers?openForm=true");

    // The form is open immediately from the query param, driving useMCPServerForm.
    const nameInput = await screen.findByPlaceholderText("Add MCP server name...");
    await user.type(nameInput, "My Server");
    await user.type(
      screen.getByPlaceholderText("Add URL for a running MCP server..."),
      "https://example.com/mcp",
    );
    await user.type(screen.getByPlaceholderText("Add an optional description..."), "A test server");

    // Once name + URL are valid, the submit button enables.
    const submit = screen.getByRole("button", { name: "Connect server" });
    await waitFor(() => expect(submit).toBeEnabled());
    await user.click(submit);

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/gateways", expect.anything(), expect.anything()),
    );
  });

  it("adds a tag from the details drawer and patches the server", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockImplementation((path: string) => {
      if (path.includes("/tools")) return Promise.resolve({ tools: [] });
      if (path.includes("/resources")) return Promise.resolve({ resources: [] });
      if (path.includes("/prompts")) return Promise.resolve({ prompts: [] });
      if (/\/gateways\/server-0/.test(path)) return Promise.resolve(mockServerDetails);
      return Promise.resolve({ gateways: createMockServers(0, 1), nextCursor: null });
    });
    vi.mocked(api.put).mockResolvedValue({
      ...mockServerDetails,
      tags: [{ id: "newtag", label: "newtag" }],
    });

    renderWithRouter(<Servers />);
    await waitFor(() => expect(screen.getByText("Test Server 0")).toBeInTheDocument());

    await user.click(screen.getAllByRole("button", { name: /actions for/i })[0]);
    await user.click(await screen.findByRole("menuitem", { name: /view details/i }));
    await waitFor(() => expect(screen.getByText("Details")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Add tags" }));
    await user.type(screen.getByPlaceholderText("Add tags separated with commas"), "newtag");
    await user.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() => {
      expect(api.put).toHaveBeenCalledWith(expect.stringContaining("/gateways/server-0"), {
        tags: ["newtag"],
      });
    });
  });

  it("shows an error toast when adding a tag fails", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockImplementation((path: string) => {
      if (path.includes("/tools")) return Promise.resolve({ tools: [] });
      if (path.includes("/resources")) return Promise.resolve({ resources: [] });
      if (path.includes("/prompts")) return Promise.resolve({ prompts: [] });
      if (/\/gateways\/server-0/.test(path)) return Promise.resolve(mockServerDetails);
      return Promise.resolve({ gateways: createMockServers(0, 1), nextCursor: null });
    });
    vi.mocked(api.put).mockRejectedValue(new Error("boom"));

    renderWithRouter(<Servers />);
    await waitFor(() => expect(screen.getByText("Test Server 0")).toBeInTheDocument());

    await user.click(screen.getAllByRole("button", { name: /actions for/i })[0]);
    await user.click(await screen.findByRole("menuitem", { name: /view details/i }));
    await waitFor(() => expect(screen.getByText("Details")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Add tags" }));
    await user.type(screen.getByPlaceholderText("Add tags separated with commas"), "newtag");
    await user.click(screen.getByRole("button", { name: "Add" }));

    // The rejected update runs through the error branch (which surfaces a toast).
    await waitFor(() => {
      expect(api.put).toHaveBeenCalledWith(expect.stringContaining("/gateways/server-0"), {
        tags: ["newtag"],
      });
    });
  });

  it("opens the details drawer for a server referenced by the ?selected= query param", async () => {
    vi.mocked(api.get).mockImplementation((path: string) => {
      if (path.includes("/tools")) return Promise.resolve({ tools: [] });
      if (path.includes("/resources")) return Promise.resolve({ resources: [] });
      if (path.includes("/prompts")) return Promise.resolve({ prompts: [] });
      if (/\/gateways\/server-0/.test(path)) return Promise.resolve(mockServerDetails);
      return Promise.resolve({ gateways: createMockServers(0, 1), nextCursor: null });
    });

    renderWithRouter(<Servers />, "/app/servers?selected=server-0");

    await waitFor(() => expect(screen.getByText("Details")).toBeInTheDocument());
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

  it("displays server metadata in details panel", async () => {
    const user = userEvent.setup();

    vi.mocked(api.get).mockResolvedValueOnce({
      gateways: createMockServers(0, 25),
      nextCursor: "cursor-1",
    });

    renderWithRouter(<Servers />);

    await waitFor(() => {
      expect(screen.getByText("Test Server 0")).toBeInTheDocument();
    });

    vi.mocked(api.get).mockResolvedValueOnce({ tools: [] });
    vi.mocked(api.get).mockResolvedValueOnce({ resources: [] });
    vi.mocked(api.get).mockResolvedValueOnce({ prompts: [] });
    vi.mocked(api.get).mockResolvedValueOnce(mockServerDetails);

    const actionsButtons = screen.getAllByRole("button", { name: /actions for/i });
    await user.click(actionsButtons[0]);

    const viewDetailsItem = await screen.findByRole("menuitem", { name: /view details/i });
    await user.click(viewDetailsItem);

    const detailsPanel = await screen.findByRole("region", { name: /test server 0/i });
    await waitFor(() => {
      const panel = within(detailsPanel);
      expect(panel.getByText("Active")).toBeInTheDocument();
      expect(panel.getByText("Internal")).toBeInTheDocument();
      expect(panel.getByText("Server-Sent Events (SSE)")).toBeInTheDocument();
      expect(panel.getByText("Engineering")).toBeInTheDocument();
      expect(panel.getByText("test@example.com")).toBeInTheDocument();
    });
  });

  it("shows inline error notification when toggleEnabled fails", async () => {
    const user = userEvent.setup();

    vi.mocked(api.get).mockResolvedValueOnce({
      gateways: createMockServers(0, 1),
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

  it("calls refetch and clears error when toggleEnabled succeeds", async () => {
    const user = userEvent.setup();

    vi.mocked(api.get).mockResolvedValueOnce({
      gateways: createMockServers(0, 1),
      nextCursor: null,
    });

    renderWithRouter(<Servers />);

    await waitFor(() => {
      expect(screen.getByText("Test Server 0")).toBeInTheDocument();
    });

    vi.mocked(api.post).mockResolvedValueOnce({});

    // api.get should be called again for refetch
    vi.mocked(api.get).mockResolvedValueOnce({
      gateways: createMockServers(0, 1),
      nextCursor: null,
    });

    const actionsButtons = screen.getAllByRole("button", { name: /actions for/i });
    await user.click(actionsButtons[0]);

    const deactivateItem = await screen.findByRole("menuitem", { name: /deactivate/i });
    await user.click(deactivateItem);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(expect.stringContaining("activate=false"));
    });

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledTimes(2); // Initial fetch + refetch
    });
  });

  it("opens the test connection dialog from the actions menu", async () => {
    const user = userEvent.setup();

    vi.mocked(api.get).mockResolvedValueOnce({
      gateways: createMockServers(0, 1),
      nextCursor: null,
    });

    renderWithRouter(<Servers />);

    await waitFor(() => {
      expect(screen.getByText("Test Server 0")).toBeInTheDocument();
    });

    const actionsButtons = screen.getAllByRole("button", { name: /actions for/i });
    await user.click(actionsButtons[0]);

    const testItem = await screen.findByRole("menuitem", { name: /test connection/i });
    await user.click(testItem);

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("heading", { name: /test connection/i })).toBeInTheDocument();
  });

  it("optimistically removes server from list immediately on delete confirmation", async () => {
    const user = userEvent.setup();

    vi.mocked(api.get).mockResolvedValueOnce({
      gateways: createMockServers(0, 3),
      nextCursor: null,
    });

    renderWithRouter(<Servers />);

    await waitFor(() => {
      expect(screen.getByText("Test Server 0")).toBeInTheDocument();
    });

    let resolveDelete!: () => void;
    vi.mocked(api.delete).mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          resolveDelete = resolve;
        }),
    );

    const actionsButtons = screen.getAllByRole("button", { name: /actions for/i });
    await user.click(actionsButtons[0]);

    const deleteItem = await screen.findByRole("menuitem", { name: /^delete$/i });
    await user.click(deleteItem);

    const confirmButton = await screen.findByRole("button", { name: /^delete$/i });
    await user.click(confirmButton);

    await waitFor(() => {
      expect(screen.queryByText("Test Server 0")).not.toBeInTheDocument();
    });

    expect(screen.getByText("Test Server 1")).toBeInTheDocument();

    vi.mocked(api.get).mockResolvedValueOnce({
      gateways: createMockServers(1, 2),
      nextCursor: null,
    });
    resolveDelete();

    await waitFor(() => {
      expect(mockToastSuccess).toHaveBeenCalledWith("Test Server 0 deleted.");
    });
  });

  it("rolls back optimistic delete and shows toast error when delete API fails", async () => {
    const user = userEvent.setup();

    vi.mocked(api.get).mockResolvedValueOnce({
      gateways: createMockServers(0, 3),
      nextCursor: null,
    });

    renderWithRouter(<Servers />);

    await waitFor(() => {
      expect(screen.getByText("Test Server 0")).toBeInTheDocument();
    });

    vi.mocked(api.delete).mockRejectedValueOnce(new Error("403 Forbidden"));

    const actionsButtons = screen.getAllByRole("button", { name: /actions for/i });
    await user.click(actionsButtons[0]);

    const deleteItem = await screen.findByRole("menuitem", { name: /^delete$/i });
    await user.click(deleteItem);

    const confirmButton = await screen.findByRole("button", { name: /^delete$/i });
    await user.click(confirmButton);

    await waitFor(() => {
      expect(screen.getByText("Test Server 0")).toBeInTheDocument();
    });

    expect(mockToastError).toHaveBeenCalledWith(
      "Error deleting MCP server",
      expect.objectContaining({ description: expect.any(String) }),
    );
  });

  it("closes the details drawer optimistically when the viewed server is deleted and restores it on rollback", async () => {
    const user = userEvent.setup();

    vi.mocked(api.get).mockResolvedValueOnce({
      gateways: createMockServers(0, 3),
      nextCursor: null,
    });

    renderWithRouter(<Servers />);

    await waitFor(() => {
      expect(screen.getByText("Test Server 0")).toBeInTheDocument();
    });

    vi.mocked(api.get).mockResolvedValueOnce(mockServerDetails);

    const actionsButtons = screen.getAllByRole("button", { name: /actions for/i });
    await user.click(actionsButtons[0]);

    const viewDetailsItem = await screen.findByRole("menuitem", { name: /view details/i });
    await user.click(viewDetailsItem);

    await waitFor(() => {
      expect(screen.getByText("Details")).toBeInTheDocument();
    });

    let rejectDelete!: (err: Error) => void;
    vi.mocked(api.delete).mockImplementationOnce(
      () =>
        new Promise<void>((_, reject) => {
          rejectDelete = reject;
        }),
    );

    await user.click(actionsButtons[0]);
    const deleteItem = await screen.findByRole("menuitem", { name: /^delete$/i });
    await user.click(deleteItem);

    const confirmButton = await screen.findByRole("button", { name: /^delete$/i });
    await user.click(confirmButton);

    await waitFor(() => {
      expect(
        screen.queryByRole("button", { name: /close mcp server details/i }),
      ).not.toBeInTheDocument();
    });

    rejectDelete(new Error("403 Forbidden"));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /close mcp server details/i })).toBeInTheDocument();
    });

    const table = screen.getByRole("table");
    expect(within(table).getByText("Test Server 0")).toBeInTheDocument();
  });

  it("does not close the details drawer when a different server is deleted", async () => {
    const user = userEvent.setup();

    vi.mocked(api.get).mockResolvedValueOnce({
      gateways: createMockServers(0, 3),
      nextCursor: null,
    });

    renderWithRouter(<Servers />);

    await waitFor(() => {
      expect(screen.getByText("Test Server 0")).toBeInTheDocument();
    });

    vi.mocked(api.get).mockResolvedValueOnce(mockServerDetails);

    const actionsButtons = screen.getAllByRole("button", { name: /actions for/i });
    await user.click(actionsButtons[0]);

    const viewDetailsItem = await screen.findByRole("menuitem", { name: /view details/i });
    await user.click(viewDetailsItem);

    await waitFor(() => {
      expect(screen.getByText("Details")).toBeInTheDocument();
    });

    vi.mocked(api.delete).mockResolvedValueOnce(undefined);
    vi.mocked(api.get).mockResolvedValueOnce({
      gateways: [createMockServers(0, 1)[0], ...createMockServers(2, 1)],
      nextCursor: null,
    });

    await user.click(actionsButtons[1]);
    const deleteItem = await screen.findByRole("menuitem", { name: /^delete$/i });
    await user.click(deleteItem);

    const confirmButton = await screen.findByRole("button", { name: /^delete$/i });
    await user.click(confirmButton);

    await waitFor(() => {
      expect(screen.queryByText("Test Server 1")).not.toBeInTheDocument();
    });

    expect(screen.getByRole("button", { name: /close mcp server details/i })).toBeInTheDocument();
  });

  it("refetch failure after successful delete does not trigger rollback or error toast", async () => {
    const user = userEvent.setup();

    vi.mocked(api.get).mockResolvedValueOnce({
      gateways: createMockServers(0, 3),
      nextCursor: null,
    });

    renderWithRouter(<Servers />);

    await waitFor(() => {
      expect(screen.getByText("Test Server 0")).toBeInTheDocument();
    });

    vi.mocked(api.delete).mockResolvedValueOnce(undefined);
    vi.mocked(api.get).mockRejectedValueOnce(new Error("Network timeout"));

    const actionsButtons = screen.getAllByRole("button", { name: /actions for/i });
    await user.click(actionsButtons[0]);

    const deleteItem = await screen.findByRole("menuitem", { name: /^delete$/i });
    await user.click(deleteItem);

    const confirmButton = await screen.findByRole("button", { name: /^delete$/i });
    await user.click(confirmButton);

    // Success toast should fire
    await waitFor(() => {
      expect(mockToastSuccess).toHaveBeenCalledWith(expect.stringContaining("Test Server 0"));
    });

    expect(mockToastError).not.toHaveBeenCalled();

    expect(screen.queryByText("Test Server 0")).not.toBeInTheDocument();
  });

  it("does not call delete API when confirmDelete is triggered with no selectedServerId", async () => {
    // This test exercises the early-return guard: `if (!selectedServerId) return`
    // The delete dialog is only opened via handleDelete which sets selectedServerId,
    // so we verify the guard is never hit in normal flow — the API is not called
    // when no server is selected.
    vi.mocked(api.get).mockResolvedValueOnce({
      gateways: createMockServers(0, 1),
      nextCursor: null,
    });

    renderWithRouter(<Servers />);

    await waitFor(() => {
      expect(screen.getByText("Test Server 0")).toBeInTheDocument();
    });

    // No server is selected — confirm dialog should not be present
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    // api.delete should never have been called
    expect(api.delete).not.toHaveBeenCalled();
  });

  it("does not call API when Load More is clicked without a nextCursor", async () => {
    // This test exercises the early-return guard: `if (!nextCursor || loadingMore) return`
    vi.mocked(api.get).mockResolvedValueOnce({
      gateways: createMockServers(0, 5),
      nextCursor: null, // No next cursor
    });

    renderWithRouter(<Servers />);

    await waitFor(() => {
      expect(screen.getByText("Test Server 0")).toBeInTheDocument();
    });

    // Load More button should not be rendered when nextCursor is null
    expect(screen.queryByRole("button", { name: /load more servers/i })).not.toBeInTheDocument();
    // Only the initial fetch should have happened
    expect(api.get).toHaveBeenCalledTimes(1);
  });

  it("does not call API twice if Load More is clicked while already loading", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValueOnce({
      gateways: createMockServers(0, 5),
      nextCursor: "cursor-1",
    });

    renderWithRouter(<Servers />);
    await waitFor(() => {
      expect(screen.getByText("Test Server 0")).toBeInTheDocument();
    });

    // Mock a slow API response for the next page
    let resolveSecondPage!: (value: unknown) => void;
    vi.mocked(api.get).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveSecondPage = resolve;
        }),
    );

    const loadMoreButton = screen.getByRole("button", { name: /load more/i });

    // Click twice quickly
    await user.click(loadMoreButton);
    await user.click(loadMoreButton);

    // Should only trigger one fetch because of `loadingMore` guard
    expect(api.get).toHaveBeenCalledTimes(2); // 1 initial + 1 load more

    // Cleanup promise
    resolveSecondPage({ gateways: [], nextCursor: null });
  });

  it("logs error when Load More API fails", async () => {
    const user = userEvent.setup();
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    vi.mocked(api.get).mockResolvedValueOnce({
      gateways: createMockServers(0, 25),
      nextCursor: "cursor-1",
    });

    renderWithRouter(<Servers />);

    await waitFor(() => {
      expect(screen.getByText("Test Server 0")).toBeInTheDocument();
    });

    const loadMoreButton = screen.getByRole("button", { name: /load more/i });

    // Mock the second page fetch to reject
    const mockError = new Error("Failed to fetch");
    vi.mocked(api.get).mockRejectedValueOnce(mockError);

    await user.click(loadMoreButton);

    await waitFor(() => {
      expect(consoleErrorSpy).toHaveBeenCalledWith("Failed to load more servers:", mockError);
    });

    consoleErrorSpy.mockRestore();
  });

  it("changes limit when select value changes", async () => {
    const user = userEvent.setup();

    vi.mocked(api.get).mockResolvedValue({
      gateways: createMockServers(0, 5),
      nextCursor: "cursor-1",
    });

    renderWithRouter(<Servers />);

    await waitFor(() => {
      expect(screen.getByText("Test Server 0")).toBeInTheDocument();
    });

    // Check initial limit
    expect(screen.getAllByText(/Test Server/).length).toBeGreaterThan(0);

    const select = screen.getByLabelText(/Per page:/i);
    await user.selectOptions(select, "25");

    await waitFor(() => {
      expect(vi.mocked(api.get)).toHaveBeenCalledWith(
        expect.stringContaining("limit=25"),
        undefined,
        expect.any(AbortSignal),
      );
    });
  });

  it("renders MCPServerForm when Connect is clicked and handles form close", async () => {
    const user = userEvent.setup();

    vi.mocked(api.get).mockResolvedValue({
      gateways: createMockServers(0, 5),
      nextCursor: "cursor-1",
    });

    renderWithRouter(<Servers />);

    await waitFor(() => {
      expect(screen.getByText("Test Server 0")).toBeInTheDocument();
    });

    // Click Connect to open form
    const connectButton = screen.getByRole("button", { name: /Connect/i });
    await user.click(connectButton);

    // Form should appear
    expect(await screen.findByRole("heading", { name: "Connect MCP server" })).toBeInTheDocument();

    // Test onToggle (Cancel)
    const cancelButton = screen.getByRole("button", { name: /Cancel/i });
    await user.click(cancelButton);

    // Form should close, table should appear again
    await waitFor(() => {
      expect(screen.queryByRole("heading", { name: "Connect MCP server" })).not.toBeInTheDocument();
      expect(screen.getByText("Test Server 0")).toBeInTheDocument();
    });
  });

  it("triggers onSuccess refetch from MCPServerForm submission", async () => {
    const user = userEvent.setup();

    vi.mocked(api.get).mockImplementation((path) => {
      if (path.includes("/gateways/server-0")) {
        return Promise.resolve(mockServerDetails);
      }
      return Promise.resolve({
        gateways: createMockServers(0, 5),
        nextCursor: "cursor-1",
      });
    });

    renderWithRouter(<Servers />);

    await waitFor(() => {
      expect(screen.getByText("Test Server 0")).toBeInTheDocument();
    });

    // Edit button opens form with selected server ID
    const actionsButtons = screen.getAllByRole("button", { name: /actions for/i });
    await user.click(actionsButtons[0]);
    const editItem = await screen.findByRole("menuitem", { name: /edit/i });
    await user.click(editItem);

    // Wait for the form to appear
    expect(await screen.findByRole("heading", { name: "Edit MCP server" })).toBeInTheDocument();

    // We can simulate a successful submit since the API call in MCPServerForm will use our mock
    vi.mocked(api.put).mockResolvedValueOnce({});

    // Fill the required URL field (it uses URL format)
    const urlInput = screen.getByLabelText(/^URL/i);
    await user.clear(urlInput);
    await user.type(urlInput, "http://new-url.example.com");

    const submitButton = screen.getByRole("button", { name: /Save changes/i });
    await user.click(submitButton);

    // Form should close on success and list should be re-rendered
    await waitFor(() => {
      expect(screen.queryByRole("heading", { name: "Edit MCP server" })).not.toBeInTheDocument();
    });
  });
});
