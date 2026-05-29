import { useState } from "react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { renderWithProviders } from "@/test/test-utils";
import { MCPServerDetailsPanel } from "./MCPServerDetailsPanel";
import type { MCPServer } from "@/types/server";

const mockServer: MCPServer = {
  id: "test-server-123",
  name: "Test MCP Server",
  description: "A test server for unit testing",
  url: "http://test.example.com",
  transport: "SSE",
  enabled: true,
  reachable: true,
  visibility: "public",
  tool_count: 5,
  created_at: "2024-01-01T00:00:00Z",
  updated_at: "2024-01-02T00:00:00Z",
  last_seen: "2024-01-03T00:00:00Z",
  team: "Engineering",
  owner_email: "test@example.com",
};

const mockTools = [
  {
    id: "tool-1",
    name: "tool1",
    title: "Tool One",
    originalName: "original_tool_1",
    description: "First test tool",
  },
  {
    id: "tool-2",
    name: "tool2",
    originalName: "original_tool_2",
    description: "Second test tool without title",
  },
];

const mockResources = [
  {
    id: "resource-1",
    name: "resource1",
    title: "Resource One",
    uri: "file:///path/to/resource1",
  },
  {
    id: "resource-2",
    name: "resource2",
    uri: "file:///path/to/resource2",
  },
];

const mockPrompts = [
  {
    id: "prompt-1",
    name: "prompt1",
    title: "Prompt One",
    originalName: "original_prompt_1",
    description: "First test prompt",
  },
];

describe("MCPServerDetailsPanel", () => {
  beforeEach(() => {
    server.use(
      http.get("*/tools", ({ request }) => {
        const url = new URL(request.url);
        const gatewayId = url.searchParams.get("gateway_id");
        if (gatewayId === mockServer.id) {
          return HttpResponse.json({ tools: mockTools });
        }
        return HttpResponse.json({ tools: [] });
      }),
      http.get("*/resources", ({ request }) => {
        const url = new URL(request.url);
        const gatewayId = url.searchParams.get("gateway_id");
        if (gatewayId === mockServer.id) {
          return HttpResponse.json({ resources: mockResources });
        }
        return HttpResponse.json({ resources: [] });
      }),
      http.get("*/prompts", ({ request }) => {
        const url = new URL(request.url);
        const gatewayId = url.searchParams.get("gateway_id");
        if (gatewayId === mockServer.id) {
          return HttpResponse.json({ prompts: mockPrompts });
        }
        return HttpResponse.json({ prompts: [] });
      }),
    );
  });

  it("marks region as hidden when closed", () => {
    renderWithProviders(
      <MCPServerDetailsPanel
        server={mockServer}
        isLoading={false}
        error={null}
        open={false}
        onClose={() => {}}
      />,
    );

    const region = screen.getByRole("region", { hidden: true });
    expect(region).toHaveAttribute("aria-hidden", "true");
    expect(region).toHaveAttribute("data-state", "closed");
  });

  it("renders server details when open", async () => {
    renderWithProviders(
      <MCPServerDetailsPanel
        server={mockServer}
        isLoading={false}
        error={null}
        open={true}
        onClose={() => {}}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Test MCP Server")).toBeInTheDocument();
    });

    expect(screen.getByText("A test server for unit testing")).toBeInTheDocument();

    const region = screen.getByRole("region");
    expect(region).toHaveAttribute("data-state", "open");
    expect(region).toHaveAttribute("aria-hidden", "false");
  });

  it("displays loading state", () => {
    renderWithProviders(
      <MCPServerDetailsPanel
        server={mockServer}
        isLoading={true}
        error={null}
        open={true}
        onClose={() => {}}
      />,
    );

    expect(screen.getByText(/loading components/i)).toBeInTheDocument();
  });

  it("displays error message", () => {
    renderWithProviders(
      <MCPServerDetailsPanel
        server={mockServer}
        isLoading={false}
        error={{ message: "Failed to load server" }}
        open={true}
        onClose={() => {}}
      />,
    );

    expect(screen.getByText("Failed to load server")).toBeInTheDocument();
  });

  it("fetches and displays tools, resources, and prompts", async () => {
    renderWithProviders(
      <MCPServerDetailsPanel
        server={mockServer}
        isLoading={false}
        error={null}
        open={true}
        onClose={() => {}}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Tool One")).toBeInTheDocument();
    });

    expect(screen.getByText("Resource One")).toBeInTheDocument();
    expect(screen.getByText("Prompt One")).toBeInTheDocument();
  });

  it("switches between component tabs", async () => {
    const user = userEvent.setup();

    renderWithProviders(
      <MCPServerDetailsPanel
        server={mockServer}
        isLoading={false}
        error={null}
        open={true}
        onClose={() => {}}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Tool One")).toBeInTheDocument();
    });

    const toolsTab = screen.getByRole("tab", { name: "Tools" });
    await user.click(toolsTab);

    await waitFor(() => {
      expect(screen.getByText("Tool One")).toBeInTheDocument();
      expect(screen.queryByText("Resource One")).not.toBeInTheDocument();
    });

    const resourcesTab = screen.getByRole("tab", { name: "Resources" });
    await user.click(resourcesTab);

    await waitFor(() => {
      expect(screen.getByText("Resource One")).toBeInTheDocument();
      expect(screen.queryByText("Tool One")).not.toBeInTheDocument();
    });

    const promptsTab = screen.getByRole("tab", { name: "Prompts" });
    await user.click(promptsTab);

    await waitFor(() => {
      expect(screen.getByText("Prompt One")).toBeInTheDocument();
      expect(screen.queryByText("Tool One")).not.toBeInTheDocument();
    });

    const allTab = screen.getByRole("tab", { name: "All" });
    await user.click(allTab);

    await waitFor(() => {
      expect(screen.getByText("Tool One")).toBeInTheDocument();
      expect(screen.getByText("Resource One")).toBeInTheDocument();
      expect(screen.getByText("Prompt One")).toBeInTheDocument();
    });
  });

  it("expands and collapses search input", async () => {
    const user = userEvent.setup();

    renderWithProviders(
      <MCPServerDetailsPanel
        server={mockServer}
        isLoading={false}
        error={null}
        open={true}
        onClose={() => {}}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Tool One")).toBeInTheDocument();
    });

    const searchButton = screen.getByRole("button", { name: /search components/i });
    expect(searchButton).toBeInTheDocument();

    await user.click(searchButton);

    const searchInput = screen.getByPlaceholderText("Search...");
    expect(searchInput).toBeInTheDocument();
    expect(searchInput).toHaveFocus();
  });

  it("filters components by search query", async () => {
    const user = userEvent.setup();

    renderWithProviders(
      <MCPServerDetailsPanel
        server={mockServer}
        isLoading={false}
        error={null}
        open={true}
        onClose={() => {}}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Tool One")).toBeInTheDocument();
    });

    const searchButton = screen.getByRole("button", { name: /search components/i });
    await user.click(searchButton);

    const searchInput = screen.getByPlaceholderText("Search...");

    await user.type(searchInput, "Tool One");

    await waitFor(() => {
      expect(screen.getByText("Tool One")).toBeInTheDocument();
      expect(screen.queryByText("Resource One")).not.toBeInTheDocument();
      expect(screen.queryByText("Prompt One")).not.toBeInTheDocument();
    });

    await user.clear(searchInput);

    await waitFor(() => {
      expect(screen.getByText("Tool One")).toBeInTheDocument();
      expect(screen.getByText("Resource One")).toBeInTheDocument();
      expect(screen.getByText("Prompt One")).toBeInTheDocument();
    });
  });

  it("searches by originalName when no title", async () => {
    const user = userEvent.setup();

    renderWithProviders(
      <MCPServerDetailsPanel
        server={mockServer}
        isLoading={false}
        error={null}
        open={true}
        onClose={() => {}}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("original_tool_2")).toBeInTheDocument();
    });

    const searchButton = screen.getByRole("button", { name: /search components/i });
    await user.click(searchButton);

    const searchInput = screen.getByPlaceholderText("Search...");

    await user.type(searchInput, "original_tool_2");

    await waitFor(() => {
      expect(screen.getByText("original_tool_2")).toBeInTheDocument();
      expect(screen.queryByText("Tool One")).not.toBeInTheDocument();
    });
  });

  it("searches by uri for resources", async () => {
    const user = userEvent.setup();

    renderWithProviders(
      <MCPServerDetailsPanel
        server={mockServer}
        isLoading={false}
        error={null}
        open={true}
        onClose={() => {}}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Resource One")).toBeInTheDocument();
    });

    const searchButton = screen.getByRole("button", { name: /search components/i });
    await user.click(searchButton);

    const searchInput = screen.getByPlaceholderText("Search...");

    await user.type(searchInput, "resource1");

    await waitFor(() => {
      expect(screen.getByText("Resource One")).toBeInTheDocument();
      expect(screen.queryByText("file:///path/to/resource2")).not.toBeInTheDocument();
    });
  });

  it("displays component with title and identifier", async () => {
    renderWithProviders(
      <MCPServerDetailsPanel
        server={mockServer}
        isLoading={false}
        error={null}
        open={true}
        onClose={() => {}}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Tool One")).toBeInTheDocument();
    });

    expect(screen.getByText("Tool One")).toBeInTheDocument();
    expect(screen.getByText("original_tool_1")).toBeInTheDocument();
  });

  it("displays component without title showing only identifier", async () => {
    renderWithProviders(
      <MCPServerDetailsPanel
        server={mockServer}
        isLoading={false}
        error={null}
        open={true}
        onClose={() => {}}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("original_tool_2")).toBeInTheDocument();
    });

    expect(screen.getByText("original_tool_2")).toBeInTheDocument();
  });

  it("displays server metadata in details sidebar", async () => {
    renderWithProviders(
      <MCPServerDetailsPanel
        server={mockServer}
        isLoading={false}
        error={null}
        open={true}
        onClose={() => {}}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Details")).toBeInTheDocument();
    });

    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText("Public")).toBeInTheDocument();
    expect(screen.getByText("Server-Sent Events (SSE)")).toBeInTheDocument();
    expect(screen.getByText("Engineering")).toBeInTheDocument();
    expect(screen.getByText("test@example.com")).toBeInTheDocument();
  });

  it("displays correct status for inactive server", async () => {
    const inactiveServer = { ...mockServer, enabled: false };

    renderWithProviders(
      <MCPServerDetailsPanel
        server={inactiveServer}
        isLoading={false}
        error={null}
        open={true}
        onClose={() => {}}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Inactive")).toBeInTheDocument();
    });
  });

  it("displays correct status for unreachable server", async () => {
    const unreachableServer = { ...mockServer, reachable: false };

    renderWithProviders(
      <MCPServerDetailsPanel
        server={unreachableServer}
        isLoading={false}
        error={null}
        open={true}
        onClose={() => {}}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Unreachable")).toBeInTheDocument();
    });
  });

  it("closes panel when close button is clicked", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();

    renderWithProviders(
      <MCPServerDetailsPanel
        server={mockServer}
        isLoading={false}
        error={null}
        open={true}
        onClose={onClose}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Test MCP Server")).toBeInTheDocument();
    });

    const closeButton = screen.getByRole("button", { name: /close mcp server details/i });
    await user.click(closeButton);

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes panel when Escape is pressed", async () => {
    const onClose = vi.fn();

    renderWithProviders(
      <MCPServerDetailsPanel
        server={mockServer}
        isLoading={false}
        error={null}
        open={true}
        onClose={onClose}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Test MCP Server")).toBeInTheDocument();
    });

    fireEvent.keyDown(window, { key: "Escape" });

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does not close on Escape when already closed", async () => {
    const onClose = vi.fn();

    renderWithProviders(
      <MCPServerDetailsPanel
        server={mockServer}
        isLoading={false}
        error={null}
        open={false}
        onClose={onClose}
      />,
    );

    fireEvent.keyDown(window, { key: "Escape" });

    expect(onClose).not.toHaveBeenCalled();
  });

  it("closes panel when backdrop is clicked", async () => {
    const onClose = vi.fn();

    const { container } = renderWithProviders(
      <MCPServerDetailsPanel
        server={mockServer}
        isLoading={false}
        error={null}
        open={true}
        onClose={onClose}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Test MCP Server")).toBeInTheDocument();
    });

    const backdrop = container.querySelector('[aria-hidden="true"][data-state="open"]');
    expect(backdrop).not.toBeNull();
    fireEvent.click(backdrop!);

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("focuses the close button when opened", async () => {
    const { rerender } = renderWithProviders(
      <MCPServerDetailsPanel
        server={mockServer}
        isLoading={false}
        error={null}
        open={false}
        onClose={() => {}}
      />,
    );

    rerender(
      <MCPServerDetailsPanel
        server={mockServer}
        isLoading={false}
        error={null}
        open={true}
        onClose={() => {}}
      />,
    );

    await waitFor(() => {
      const closeButton = screen.getByRole("button", { name: /close mcp server details/i });
      expect(closeButton).toHaveFocus();
    });
  });

  it("restores focus to the previously focused element when closed", async () => {
    const user = userEvent.setup();

    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Open
          </button>
          <MCPServerDetailsPanel
            server={mockServer}
            isLoading={false}
            error={null}
            open={open}
            onClose={() => setOpen(false)}
          />
        </>
      );
    }

    renderWithProviders(<Harness />);

    const trigger = screen.getByRole("button", { name: "Open" });
    trigger.focus();
    expect(trigger).toHaveFocus();

    await user.click(trigger);

    await waitFor(() => {
      const closeButton = screen.getByRole("button", { name: /close mcp server details/i });
      expect(closeButton).toHaveFocus();
    });

    const closeButton = screen.getByRole("button", { name: /close mcp server details/i });
    await user.click(closeButton);

    await waitFor(() => {
      expect(trigger).toHaveFocus();
    });
  });

  it("resets tab and search when server changes", async () => {
    const user = userEvent.setup();

    const { rerender } = renderWithProviders(
      <MCPServerDetailsPanel
        server={mockServer}
        isLoading={false}
        error={null}
        open={true}
        onClose={() => {}}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Tool One")).toBeInTheDocument();
    });

    const toolsTab = screen.getByRole("tab", { name: "Tools" });
    await user.click(toolsTab);

    const searchButton = screen.getByRole("button", { name: /search components/i });
    await user.click(searchButton);
    const searchInput = screen.getByPlaceholderText("Search...");
    await user.type(searchInput, "test query");

    const newServer = { ...mockServer, id: "new-server-456", name: "New Server" };

    server.use(
      http.get("*/tools", ({ request }) => {
        const url = new URL(request.url);
        const gatewayId = url.searchParams.get("gateway_id");
        if (gatewayId === newServer.id) {
          return HttpResponse.json({ tools: mockTools });
        }
        return HttpResponse.json({ tools: [] });
      }),
    );

    rerender(
      <MCPServerDetailsPanel
        server={newServer}
        isLoading={false}
        error={null}
        open={true}
        onClose={() => {}}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("New Server")).toBeInTheDocument();
    });

    const newSearchInput = screen.queryByDisplayValue("test query");
    expect(newSearchInput).not.toBeInTheDocument();
  });

  it("displays 'No components found' when no data", async () => {
    server.use(
      http.get("*/tools", () => HttpResponse.json({ tools: [] })),
      http.get("*/resources", () => HttpResponse.json({ resources: [] })),
      http.get("*/prompts", () => HttpResponse.json({ prompts: [] })),
    );

    renderWithProviders(
      <MCPServerDetailsPanel
        server={mockServer}
        isLoading={false}
        error={null}
        open={true}
        onClose={() => {}}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText(/no components found/i)).toBeInTheDocument();
    });
  });

  it("displays 'No tools found' when filtering by Tools tab with no results", async () => {
    const user = userEvent.setup();

    server.use(
      http.get("*/tools", () => HttpResponse.json({ tools: [] })),
      http.get("*/resources", () => HttpResponse.json({ resources: mockResources })),
      http.get("*/prompts", () => HttpResponse.json({ prompts: mockPrompts })),
    );

    renderWithProviders(
      <MCPServerDetailsPanel
        server={mockServer}
        isLoading={false}
        error={null}
        open={true}
        onClose={() => {}}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Resource One")).toBeInTheDocument();
    });

    const toolsTab = screen.getByRole("tab", { name: "Tools" });
    await user.click(toolsTab);

    await waitFor(() => {
      expect(screen.getByText(/no tools found/i)).toBeInTheDocument();
    });
  });

  it("handles array and object-wrapped API responses", async () => {
    server.use(
      http.get("*/tools", () => HttpResponse.json(mockTools)),
      http.get("*/resources", () => HttpResponse.json(mockResources)),
      http.get("*/prompts", () => HttpResponse.json(mockPrompts)),
    );

    renderWithProviders(
      <MCPServerDetailsPanel
        server={mockServer}
        isLoading={false}
        error={null}
        open={true}
        onClose={() => {}}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Tool One")).toBeInTheDocument();
    });

    expect(screen.getByText("Resource One")).toBeInTheDocument();
    expect(screen.getByText("Prompt One")).toBeInTheDocument();
  });

  it("displays component badges with correct types", async () => {
    renderWithProviders(
      <MCPServerDetailsPanel
        server={mockServer}
        isLoading={false}
        error={null}
        open={true}
        onClose={() => {}}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Tool One")).toBeInTheDocument();
    });

    expect(screen.getAllByText("tool").length).toBeGreaterThan(0);
    expect(screen.getAllByText("resource").length).toBeGreaterThan(0);
    expect(screen.getAllByText("prompt").length).toBeGreaterThan(0);
  });

  it("does not fetch data when panel is closed", () => {
    const getRequests: string[] = [];

    server.use(
      http.get("*/tools", ({ request }) => {
        getRequests.push(request.url);
        return HttpResponse.json({ tools: mockTools });
      }),
    );

    renderWithProviders(
      <MCPServerDetailsPanel
        server={mockServer}
        isLoading={false}
        error={null}
        open={false}
        onClose={() => {}}
      />,
    );

    expect(getRequests.length).toBe(0);
  });

  it("displays copy buttons for identifiers", async () => {
    renderWithProviders(
      <MCPServerDetailsPanel
        server={mockServer}
        isLoading={false}
        error={null}
        open={true}
        onClose={() => {}}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Tool One")).toBeInTheDocument();
    });

    const copyButtons = screen.getAllByRole("button", { name: /copy/i });
    expect(copyButtons.length).toBeGreaterThan(0);
  });
});
