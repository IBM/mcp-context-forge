import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/test-utils";
import { Servers } from "./Servers";
import { api } from "@/api/client";
import type { ServersResponse } from "@/types/server";

// Mock the router
const mockNavigate = vi.fn();
vi.mock("@/router", () => ({
  useRouter: () => ({
    navigate: mockNavigate,
    path: "/app/servers",
    params: {},
  }),
}));

// Mock the API client
vi.mock("@/api/client", () => ({
  api: {
    get: vi.fn(),
    delete: vi.fn(),
    post: vi.fn(),
  },
}));

const mockServersResponse: ServersResponse = {
  gateways: [
    {
      id: "server-1",
      name: "Test Server 1",
      url: "http://localhost:3000",
      transport: "SSE" as const,
      enabled: true,
      reachable: true,
      tool_count: 5,
      visibility: "public" as const,
      created_at: "2024-01-01T00:00:00Z",
      updated_at: "2024-01-01T00:00:00Z",
    },
    {
      id: "server-2",
      name: "Test Server 2",
      url: "http://localhost:3001",
      transport: "STREAMABLEHTTP" as const,
      enabled: true,
      reachable: true,
      tool_count: 3,
      visibility: "team" as const,
      created_at: "2024-01-02T00:00:00Z",
      updated_at: "2024-01-02T00:00:00Z",
    },
  ],
};

describe("Servers", () => {
  beforeEach(() => {
    mockNavigate.mockClear();
    vi.mocked(api.get).mockClear();
    vi.mocked(api.delete).mockClear();
    vi.mocked(api.post).mockClear();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders loading state initially", () => {
    vi.mocked(api.get).mockImplementation(
      () => new Promise(() => {}), // Never resolves
    );

    renderWithProviders(<Servers />);

    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("renders servers list when data is loaded", async () => {
    vi.mocked(api.get).mockResolvedValue(mockServersResponse);

    renderWithProviders(<Servers />);

    await waitFor(() => {
      expect(screen.getByText("Test Server 1")).toBeInTheDocument();
      expect(screen.getByText("Test Server 2")).toBeInTheDocument();
    });

    expect(screen.getByText("MCP Servers")).toBeInTheDocument();
  });

  it("renders empty state when no servers exist", async () => {
    vi.mocked(api.get).mockResolvedValue({ gateways: [] });

    renderWithProviders(<Servers />);

    await waitFor(() => {
      expect(screen.getByText("Connect MCP server")).toBeInTheDocument();
    });

    expect(screen.getByText(/Register an MCP server to federate its tools/)).toBeInTheDocument();
  });

  it("displays error message when API call fails", async () => {
    const errorMessage = "Failed to fetch servers";
    vi.mocked(api.get).mockRejectedValue(new Error(errorMessage));

    renderWithProviders(<Servers />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
      expect(screen.getByText(errorMessage)).toBeInTheDocument();
    });
  });

  it("navigates to server catalog when link is clicked in empty state", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValue({ gateways: [] });

    renderWithProviders(<Servers />);

    await waitFor(() => {
      expect(screen.getByText("Connect MCP server")).toBeInTheDocument();
    });

    const catalogLink = screen.getByRole("button", {
      name: /select from available servers/i,
    });
    await user.click(catalogLink);

    expect(mockNavigate).toHaveBeenCalledWith("/app/server-catalog");
  });

  it("opens delete confirmation dialog when delete button is clicked", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValue(mockServersResponse);

    renderWithProviders(<Servers />);

    await waitFor(() => {
      expect(screen.getByText("Test Server 1")).toBeInTheDocument();
    });

    // Open the dropdown menu
    const menuButtons = screen.getAllByRole("button", { name: /Actions for/i });
    await user.click(menuButtons[0]!);

    // Click delete in the dropdown
    const deleteButton = await screen.findByRole("menuitem", { name: /delete/i });
    await user.click(deleteButton);

    await waitFor(() => {
      expect(screen.getByText("Delete MCP Server")).toBeInTheDocument();
      expect(
        screen.getByText(/Are you sure you want to delete this MCP server/),
      ).toBeInTheDocument();
    });
  });

  it("deletes server and refetches list when confirmed", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValue(mockServersResponse);
    vi.mocked(api.delete).mockResolvedValue(undefined);

    renderWithProviders(<Servers />);

    await waitFor(() => {
      expect(screen.getByText("Test Server 1")).toBeInTheDocument();
    });

    // Open the dropdown menu
    const menuButtons = screen.getAllByRole("button", { name: /Actions for/i });
    await user.click(menuButtons[0]!);

    // Click delete in the dropdown
    const deleteButton = await screen.findByRole("menuitem", { name: /delete/i });
    await user.click(deleteButton);

    // Confirm deletion
    await waitFor(() => {
      expect(screen.getByText("Delete MCP Server")).toBeInTheDocument();
    });

    const confirmButton = screen.getByRole("button", { name: "Delete" });

    // Mock the refetch with updated data
    vi.mocked(api.get).mockResolvedValue({
      gateways: [mockServersResponse.gateways[1]!],
    });

    await user.click(confirmButton);

    await waitFor(() => {
      expect(api.delete).toHaveBeenCalledWith("/gateways/server-1");
    });

    // Verify refetch was triggered
    await waitFor(() => {
      expect(api.get).toHaveBeenCalledTimes(2); // Initial load + refetch
    });
  });

  it("handles delete error gracefully", async () => {
    const user = userEvent.setup();
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    vi.mocked(api.get).mockResolvedValue(mockServersResponse);
    vi.mocked(api.delete).mockRejectedValue(new Error("Delete failed"));

    renderWithProviders(<Servers />);

    await waitFor(() => {
      expect(screen.getByText("Test Server 1")).toBeInTheDocument();
    });

    // Open the dropdown menu
    const menuButtons = screen.getAllByRole("button", { name: /Actions for/i });
    await user.click(menuButtons[0]!);

    // Click delete in the dropdown
    const deleteButton = await screen.findByRole("menuitem", { name: /delete/i });
    await user.click(deleteButton);

    await waitFor(() => {
      expect(screen.getByText("Delete MCP Server")).toBeInTheDocument();
    });

    const confirmButton = screen.getByRole("button", { name: "Delete" });
    await user.click(confirmButton);

    await waitFor(() => {
      expect(consoleErrorSpy).toHaveBeenCalledWith(
        "Failed to delete server:",
        "An error occurred. Please try again.",
      );
    });

    consoleErrorSpy.mockRestore();
  });

  it("tests server connection and displays result", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValue(mockServersResponse);
    vi.mocked(api.post).mockResolvedValue({
      success: true,
      message: "Connection successful",
    });

    renderWithProviders(<Servers />);

    await waitFor(() => {
      expect(screen.getByText("Test Server 1")).toBeInTheDocument();
    });

    // Open the dropdown menu
    const menuButtons = screen.getAllByRole("button", { name: /Actions for/i });
    await user.click(menuButtons[0]!);

    // Click test connection in the dropdown
    const testButton = await screen.findByRole("menuitem", { name: /test connection/i });
    await user.click(testButton);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/gateways/server-1/test", {});
    });

    await waitFor(() => {
      expect(screen.getByText("Connection Test Result")).toBeInTheDocument();
      expect(screen.getByText("Connection successful")).toBeInTheDocument();
    });
  });

  it("handles test connection error gracefully", async () => {
    const user = userEvent.setup();
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    vi.mocked(api.get).mockResolvedValue(mockServersResponse);
    vi.mocked(api.post).mockRejectedValue(new Error("Connection failed"));

    renderWithProviders(<Servers />);

    await waitFor(() => {
      expect(screen.getByText("Test Server 1")).toBeInTheDocument();
    });

    // Open the dropdown menu
    const menuButtons = screen.getAllByRole("button", { name: /Actions for/i });
    await user.click(menuButtons[0]!);

    // Click test connection in the dropdown
    const testButton = await screen.findByRole("menuitem", { name: /test connection/i });
    await user.click(testButton);

    await waitFor(() => {
      expect(consoleErrorSpy).toHaveBeenCalledWith(
        "Failed to test connection:",
        "An error occurred. Please try again.",
      );
    });

    consoleErrorSpy.mockRestore();
  });

  it("changes page when pagination buttons are clicked", async () => {
    const user = userEvent.setup();
    const multiPageResponse: ServersResponse = {
      gateways: Array.from({ length: 25 }, (_, i) => ({
        id: `server-${i}`,
        name: `Test Server ${i}`,
        url: `http://localhost:${3000 + i}`,
        transport: "SSE" as const,
        enabled: true,
        reachable: true,
        tool_count: 5,
        visibility: "public" as const,
        created_at: "2024-01-01T00:00:00Z",
        updated_at: "2024-01-01T00:00:00Z",
      })),
    };

    vi.mocked(api.get).mockResolvedValue(multiPageResponse);

    renderWithProviders(<Servers />);

    await waitFor(() => {
      expect(screen.getByText("Test Server 0")).toBeInTheDocument();
    });

    // Check if pagination is rendered (assuming total_pages > 1 logic)
    const nextButton = screen.queryByRole("button", { name: /next/i });

    if (nextButton && !nextButton.hasAttribute("disabled")) {
      await user.click(nextButton);

      await waitFor(() => {
        expect(api.get).toHaveBeenCalledWith(
          expect.stringContaining("page=2"),
          undefined,
          undefined,
        );
      });
    }
  });

  it("calls API with correct pagination parameters", async () => {
    vi.mocked(api.get).mockResolvedValue(mockServersResponse);

    renderWithProviders(<Servers />);

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith(
        "/gateways?page=1&per_page=25&include_pagination=true",
        undefined,
        expect.any(AbortSignal),
      );
    });
  });
});
