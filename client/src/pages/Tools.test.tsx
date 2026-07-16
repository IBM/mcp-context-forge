import { describe, it, expect, beforeEach, vi } from "vitest";

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

import { screen, waitFor, within, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { render } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import { server } from "@/test/mocks/server";
import { Tools } from "./Tools";
import { RouterProvider } from "@/router";
import { I18nProvider } from "@/i18n";
import { AuthProvider } from "@/auth/AuthContext";
import type { ReactElement } from "react";
import type { Tool } from "@/types/tool";

// Helper to create mock tools
function createMockTool(id: number, gatewaySlug: string, enabled = true, reachable = true): Tool {
  return {
    id: `tool-${id}`,
    name: `Tool ${id}`,
    originalName: `tool_${id}`,
    description: `Description for tool ${id}`,
    originalDescription: `Original description for tool ${id}`,
    title: `Tool ${id} Title`,
    gatewayId: `gateway-${gatewaySlug}`,
    gatewaySlug,
    customName: `Tool ${id}`,
    customNameSlug: `tool-${id}`,
    enabled,
    reachable,
    deprecated: false,
    executionCount: 0,
    tags: [],
    integrationType: "mcp",
    requestType: "http",
    url: `https://example.com/tool-${id}`,
    headers: {},
    inputSchema: { type: "object", properties: {} },
    annotations: {},
    jsonpathFilter: null,
    auth: null,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
}

// Helper to render with real router and auth context driven by MSW /app/auth/me
function renderWithRouter(ui: ReactElement) {
  window.history.pushState({}, "", "/app/tools");

  return render(
    <AuthProvider>
      <RouterProvider>
        <I18nProvider>{ui}</I18nProvider>
      </RouterProvider>
    </AuthProvider>,
  );
}

describe("Tools", () => {
  beforeEach(() => {
    // Reset any runtime request handlers we add during tests
    server.resetHandlers();
  });

  it("renders loading state initially", () => {
    // Mock a delayed response
    server.use(
      http.get("/tools", async () => {
        await new Promise(() => {}); // Never resolves
        return HttpResponse.json([]);
      }),
    );

    renderWithRouter(<Tools />);

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByText("Loading tools, please wait...")).toBeInTheDocument();
  });

  it("renders tools list when data is loaded", async () => {
    const mockTools: Tool[] = [
      createMockTool(1, "server-1"),
      createMockTool(2, "server-1"),
      createMockTool(3, "server-2"),
    ];

    server.use(http.get("/tools", () => HttpResponse.json(mockTools)));

    renderWithRouter(<Tools />);

    await waitFor(() => {
      expect(screen.getByText("Tools")).toBeInTheDocument();
    });

    // Check that tool groups are rendered
    expect(screen.getByText("server-1")).toBeInTheDocument();
    expect(screen.getByText("server-2")).toBeInTheDocument();

    // Check tool count
    expect(screen.getByText("2 tools")).toBeInTheDocument();
    expect(screen.getByText("1 tool")).toBeInTheDocument();

    // Check individual tools
    expect(screen.getByText("Tool 1")).toBeInTheDocument();
    expect(screen.getByText("Tool 2")).toBeInTheDocument();
    expect(screen.getByText("Tool 3")).toBeInTheDocument();
  });

  it("requests the tool list with include_inactive=true so deactivated tools stay listed", async () => {
    let requestUrl: URL | null = null;
    server.use(
      http.get("/tools", ({ request }) => {
        requestUrl = new URL(request.url);
        return HttpResponse.json([]);
      }),
    );

    renderWithRouter(<Tools />);

    await waitFor(() => {
      expect(requestUrl).not.toBeNull();
    });

    expect(requestUrl!.searchParams.get("include_inactive")).toBe("true");
    expect(requestUrl!.searchParams.get("limit")).toBe("0");
  });

  it("lists inactive tools and shows their 'Inactive' status in the details panel", async () => {
    // A gateway whose only tool is deactivated — it must still appear so it can be re-activated.
    const mockTools: Tool[] = [createMockTool(1, "inactive-gateway", false, true)];
    server.use(http.get("/tools", () => HttpResponse.json(mockTools)));

    const user = userEvent.setup();
    renderWithRouter(<Tools />);

    await waitFor(() => {
      expect(screen.getByText("inactive-gateway")).toBeInTheDocument();
    });

    await user.click(screen.getByLabelText("More options for inactive-gateway"));
    await user.click(await screen.findByText("View Details"));

    await waitFor(() => {
      expect(
        screen.getByRole("region", { name: /Tools for inactive-gateway/i }),
      ).toBeInTheDocument();
    });

    // The deactivated tool's status row reads "Inactive"
    expect(screen.getByText("Inactive")).toBeInTheDocument();
  });

  it("renders Add tools card", async () => {
    server.use(http.get("/tools", () => HttpResponse.json([])));

    renderWithRouter(<Tools />);

    await waitFor(() => {
      expect(screen.getByText("Add tools")).toBeInTheDocument();
    });

    expect(
      screen.getByText(/Tools will appear automatically when you connect a MCP server/i),
    ).toBeInTheDocument();
  });

  it("handles Add tools card click", async () => {
    const user = userEvent.setup();
    server.use(http.get("/tools", () => HttpResponse.json([])));

    renderWithRouter(<Tools />);

    await waitFor(() => {
      expect(screen.getByText("Add tools")).toBeInTheDocument();
    });

    const addToolsCard = screen.getByText("Add tools").closest('[data-slot="card"]');
    expect(addToolsCard).toBeInTheDocument();

    // Click should not throw error (onAddServer is empty function in component)
    if (addToolsCard) {
      await user.click(addToolsCard);
    }
  });

  it("handles Add tools card keyboard activation", async () => {
    const user = userEvent.setup();
    server.use(http.get("/tools", () => HttpResponse.json([])));

    renderWithRouter(<Tools />);

    await waitFor(() => {
      expect(screen.getByText("Add tools")).toBeInTheDocument();
    });

    const addToolsCard = screen.getByRole("button");
    expect(addToolsCard).toHaveAttribute("tabindex", "0");

    // Enter key should activate the card without throwing
    addToolsCard.focus();
    await user.keyboard("{Enter}");
    // Space key should also activate the card without throwing
    await user.keyboard(" ");
  });

  it("clicking Add tools card opens the ToolForm", async () => {
    const user = userEvent.setup();
    server.use(http.get("/tools", () => HttpResponse.json([])));

    renderWithRouter(<Tools />);

    await waitFor(() => {
      expect(screen.getByText("Add tools")).toBeInTheDocument();
    });

    const addToolsCard = screen.getByText("Add tools").closest('[data-slot="card"]');
    expect(addToolsCard).toBeInTheDocument();
    await user.click(addToolsCard!);

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Add tool" })).toBeInTheDocument();
    });
    expect(screen.queryByText("Add tools")).not.toBeInTheDocument();
  });

  it("ToolForm Cancel button closes the form and shows the tools list again", async () => {
    const user = userEvent.setup();
    server.use(http.get("/tools", () => HttpResponse.json([])));

    renderWithRouter(<Tools />);

    await waitFor(() => {
      expect(screen.getByText("Add tools")).toBeInTheDocument();
    });

    await user.click(screen.getByText("Add tools").closest('[data-slot="card"]')!);

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Add tool" })).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /Cancel/i }));

    await waitFor(() => {
      expect(screen.getByText("Add tools")).toBeInTheDocument();
    });
    expect(screen.queryByRole("heading", { name: "Add tool" })).not.toBeInTheDocument();
  });

  it("displays error message when API call fails", async () => {
    server.use(
      http.get("/tools", () => {
        return HttpResponse.json({ detail: "Failed to fetch tools" }, { status: 500 });
      }),
    );

    renderWithRouter(<Tools />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });

    expect(screen.getByText("Error loading tools")).toBeInTheDocument();
  });

  it("groups tools by gateway slug correctly", async () => {
    const mockTools: Tool[] = [
      createMockTool(1, "gateway-a"),
      createMockTool(2, "gateway-a"),
      createMockTool(3, "gateway-a"),
      createMockTool(4, "gateway-b"),
      createMockTool(5, "gateway-b"),
    ];

    server.use(http.get("/tools", () => HttpResponse.json(mockTools)));

    renderWithRouter(<Tools />);

    await waitFor(() => {
      expect(screen.getByText("gateway-a")).toBeInTheDocument();
    });

    expect(screen.getByText("gateway-b")).toBeInTheDocument();
    expect(screen.getByText("3 tools")).toBeInTheDocument();
    expect(screen.getByText("2 tools")).toBeInTheDocument();
  });

  it("shows active status indicator for enabled and reachable tools", async () => {
    const mockTools: Tool[] = [
      createMockTool(1, "active-gateway", true, true),
      createMockTool(2, "inactive-gateway", false, false),
    ];

    server.use(http.get("/tools", () => HttpResponse.json(mockTools)));

    renderWithRouter(<Tools />);

    await waitFor(() => {
      expect(screen.getByText("active-gateway")).toBeInTheDocument();
    });

    // Check that both groups are rendered
    expect(screen.getByText("inactive-gateway")).toBeInTheDocument();

    // Active status is indicated by the colored dot (tested via style)
    const cards = screen
      .getAllByRole("generic")
      .filter((el) => el.getAttribute("data-slot") === "card");
    expect(cards.length).toBeGreaterThan(0);
  });

  it("displays tool descriptions as tooltips", async () => {
    const mockTools: Tool[] = [createMockTool(1, "server-1")];

    server.use(http.get("/tools", () => HttpResponse.json(mockTools)));

    renderWithRouter(<Tools />);

    await waitFor(() => {
      expect(screen.getByText("Tool 1")).toBeInTheDocument();
    });

    const trigger = screen.getByText("Tool 1").closest("button");
    expect(trigger).not.toBeNull();
    // Radix opens the tooltip on focus, giving keyboard users the description.
    fireEvent.focus(trigger as HTMLElement);
    expect(await screen.findByRole("tooltip")).toHaveTextContent("Description for tool 1");
  });

  it("renders more options button for each tool group", async () => {
    const mockTools: Tool[] = [createMockTool(1, "server-1"), createMockTool(2, "server-2")];

    server.use(http.get("/tools", () => HttpResponse.json(mockTools)));

    renderWithRouter(<Tools />);

    await waitFor(() => {
      expect(screen.getByText("server-1")).toBeInTheDocument();
    });

    const moreOptionsButtons = screen.getAllByLabelText(/More options for/i);
    expect(moreOptionsButtons).toHaveLength(2);
    expect(screen.getByLabelText("More options for server-1")).toBeInTheDocument();
    expect(screen.getByLabelText("More options for server-2")).toBeInTheDocument();
  });

  it("handles empty tools list", async () => {
    server.use(http.get("/tools", () => HttpResponse.json([])));

    renderWithRouter(<Tools />);

    await waitFor(() => {
      expect(screen.getByText("Add tools")).toBeInTheDocument();
    });

    // Only Add tools card should be visible (AddToolsCard has role="button")
    const cards = document.querySelectorAll('[data-slot="card"]');
    expect(cards).toHaveLength(1);
  });

  it("uses correct grid layout classes", async () => {
    server.use(http.get("/tools", () => HttpResponse.json([])));

    renderWithRouter(<Tools />);

    await waitFor(() => {
      expect(screen.getByText("Add tools")).toBeInTheDocument();
    });

    // Find the grid container by looking for the parent with all grid classes
    const gridContainer = screen
      .getByText("Add tools")
      .closest('[data-slot="card"]')?.parentElement;

    expect(gridContainer).toBeInTheDocument();
    expect(gridContainer).toHaveClass("grid");
    expect(gridContainer).toHaveClass("grid-cols-1");
    expect(gridContainer).toHaveClass("lg:grid-cols-2");
    expect(gridContainer).toHaveClass("xl:grid-cols-2");
    expect(gridContainer).toHaveClass("2xl:grid-cols-3");
  });

  it("groups tools without a gateway slug under 'REST tools'", async () => {
    const mockTools: Tool[] = [
      {
        ...createMockTool(1, ""),
        gatewaySlug: "",
      },
    ];

    server.use(http.get("/tools", () => HttpResponse.json(mockTools)));

    renderWithRouter(<Tools />);

    await waitFor(() => {
      expect(screen.getByText("REST tools")).toBeInTheDocument();
    });

    expect(screen.getByText("1 tool")).toBeInTheDocument();
  });

  it("correctly pluralizes tool count", async () => {
    const mockTools: Tool[] = [
      createMockTool(1, "single-tool-gateway"),
      createMockTool(2, "multi-tool-gateway"),
      createMockTool(3, "multi-tool-gateway"),
    ];

    server.use(http.get("/tools", () => HttpResponse.json(mockTools)));

    renderWithRouter(<Tools />);

    await waitFor(() => {
      expect(screen.getByText("1 tool")).toBeInTheDocument();
    });

    expect(screen.getByText("2 tools")).toBeInTheDocument();
  });

  it("renders multiple tool groups with correct tool counts", async () => {
    const mockTools: Tool[] = [
      createMockTool(1, "gateway-1"),
      createMockTool(2, "gateway-1"),
      createMockTool(3, "gateway-1"),
      createMockTool(4, "gateway-1"),
      createMockTool(5, "gateway-2"),
      createMockTool(6, "gateway-3"),
      createMockTool(7, "gateway-3"),
    ];

    server.use(http.get("/tools", () => HttpResponse.json(mockTools)));

    renderWithRouter(<Tools />);

    await waitFor(() => {
      expect(screen.getByText("gateway-1")).toBeInTheDocument();
    });

    expect(screen.getByText("4 tools")).toBeInTheDocument();
    expect(screen.getByText("1 tool")).toBeInTheDocument();
    expect(screen.getByText("2 tools")).toBeInTheDocument();
  });

  it("shows inactive status for tools that are disabled or unreachable", async () => {
    const mockTools: Tool[] = [
      createMockTool(1, "mixed-gateway", true, true), // Active
      createMockTool(2, "mixed-gateway", false, true), // Inactive (disabled)
      createMockTool(3, "mixed-gateway", true, false), // Inactive (unreachable)
    ];

    server.use(http.get("/tools", () => HttpResponse.json(mockTools)));

    renderWithRouter(<Tools />);

    await waitFor(() => {
      expect(screen.getByText("mixed-gateway")).toBeInTheDocument();
    });

    // Group should be active because at least one tool is enabled and reachable
    expect(screen.getByText("3 tools")).toBeInTheDocument();
  });

  it("handles network errors gracefully", async () => {
    server.use(
      http.get("/tools", () => {
        return HttpResponse.error();
      }),
    );

    renderWithRouter(<Tools />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });

    expect(screen.getByText("Error loading tools")).toBeInTheDocument();
  });

  it("displays up to 8 tools and shows +N tag for remaining tools", async () => {
    // Create 12 tools for a single gateway
    const mockTools: Tool[] = Array.from({ length: 12 }, (_, i) =>
      createMockTool(i + 1, "gateway-with-many-tools"),
    );

    server.use(http.get("/tools", () => HttpResponse.json(mockTools)));

    renderWithRouter(<Tools />);

    await waitFor(() => {
      expect(screen.getByText("gateway-with-many-tools")).toBeInTheDocument();
    });

    // Should show first 8 tools
    expect(screen.getByText("Tool 1")).toBeInTheDocument();
    expect(screen.getByText("Tool 2")).toBeInTheDocument();
    expect(screen.getByText("Tool 3")).toBeInTheDocument();
    expect(screen.getByText("Tool 4")).toBeInTheDocument();
    expect(screen.getByText("Tool 5")).toBeInTheDocument();
    expect(screen.getByText("Tool 6")).toBeInTheDocument();
    expect(screen.getByText("Tool 7")).toBeInTheDocument();
    expect(screen.getByText("Tool 8")).toBeInTheDocument();

    // Should NOT show tools 9-12
    expect(screen.queryByText("Tool 9")).not.toBeInTheDocument();
    expect(screen.queryByText("Tool 10")).not.toBeInTheDocument();
    expect(screen.queryByText("Tool 11")).not.toBeInTheDocument();
    expect(screen.queryByText("Tool 12")).not.toBeInTheDocument();

    // Should show +4 tag, with the remaining count exposed as an accessible tooltip
    const overflow = screen.getByText("+4");
    expect(overflow).toBeInTheDocument();
    fireEvent.focus(overflow.closest("button") as HTMLElement);
    expect(await screen.findByRole("tooltip")).toHaveTextContent("4 more tools");
  });

  it("displays all tools when count is 8 or less without +N tag", async () => {
    const mockTools: Tool[] = Array.from({ length: 8 }, (_, i) =>
      createMockTool(i + 1, "gateway-with-eight-tools"),
    );

    server.use(http.get("/tools", () => HttpResponse.json(mockTools)));

    renderWithRouter(<Tools />);

    await waitFor(() => {
      expect(screen.getByText("gateway-with-eight-tools")).toBeInTheDocument();
    });

    // Should show all 8 tools
    expect(screen.getByText("Tool 1")).toBeInTheDocument();
    expect(screen.getByText("Tool 8")).toBeInTheDocument();

    // Should NOT show +N tag
    expect(screen.queryByText(/^\+\d+$/)).not.toBeInTheDocument();
  });

  it("shows +1 tag with singular 'tool' in title for 9 tools", async () => {
    const mockTools: Tool[] = Array.from({ length: 9 }, (_, i) =>
      createMockTool(i + 1, "gateway-with-nine-tools"),
    );

    server.use(http.get("/tools", () => HttpResponse.json(mockTools)));

    renderWithRouter(<Tools />);

    await waitFor(() => {
      expect(screen.getByText("gateway-with-nine-tools")).toBeInTheDocument();
    });

    // Should show +1 tag, with the singular "tool" wording in the tooltip
    const overflow = screen.getByText("+1");
    expect(overflow).toBeInTheDocument();
    fireEvent.focus(overflow.closest("button") as HTMLElement);
    expect(await screen.findByRole("tooltip")).toHaveTextContent("1 more tool");
  });

  it("handles multiple gateways with different tool counts correctly", async () => {
    const mockTools: Tool[] = [
      // Gateway with 5 tools (all visible, no +N tag)
      ...Array.from({ length: 5 }, (_, i) => createMockTool(i + 1, "gateway-small")),
      // Gateway with 10 tools (8 visible + +2 tag)
      ...Array.from({ length: 10 }, (_, i) => createMockTool(i + 6, "gateway-medium")),
      // Gateway with 20 tools (8 visible + +12 tag)
      ...Array.from({ length: 20 }, (_, i) => createMockTool(i + 16, "gateway-large")),
    ];

    server.use(http.get("/tools", () => HttpResponse.json(mockTools)));

    renderWithRouter(<Tools />);

    await waitFor(() => {
      expect(screen.getByText("gateway-small")).toBeInTheDocument();
    });

    // Gateway-small: all 5 tools visible, no +N tag
    expect(screen.getByText("5 tools")).toBeInTheDocument();
    expect(screen.getByText("Tool 1")).toBeInTheDocument();
    expect(screen.getByText("Tool 5")).toBeInTheDocument();

    // Gateway-medium: 8 visible + +2 tag
    expect(screen.getByText("10 tools")).toBeInTheDocument();
    expect(screen.getByText("Tool 6")).toBeInTheDocument();
    expect(screen.getByText("Tool 13")).toBeInTheDocument();
    expect(screen.queryByText("Tool 14")).not.toBeInTheDocument();
    expect(screen.getByText("+2")).toBeInTheDocument();

    // Gateway-large: 8 visible + +12 tag
    expect(screen.getByText("20 tools")).toBeInTheDocument();
    expect(screen.getByText("Tool 16")).toBeInTheDocument();
    expect(screen.getByText("Tool 23")).toBeInTheDocument();
    expect(screen.queryByText("Tool 24")).not.toBeInTheDocument();
    expect(screen.getByText("+12")).toBeInTheDocument();
  });

  describe("Dropdown Menu and Details Panel", () => {
    it("opens dropdown menu when clicking more options button", async () => {
      const user = userEvent.setup();
      const mockTools: Tool[] = [createMockTool(1, "test-gateway")];

      server.use(http.get("/tools", () => HttpResponse.json(mockTools)));

      renderWithRouter(<Tools />);

      await waitFor(() => {
        expect(screen.getByText("test-gateway")).toBeInTheDocument();
      });

      const moreOptionsButton = screen.getByLabelText("More options for test-gateway");
      await user.click(moreOptionsButton);

      // Dropdown menu should be visible
      await waitFor(() => {
        expect(screen.getByText("View Details")).toBeInTheDocument();
      });
    });

    it("opens details panel when clicking View Details menu item", async () => {
      const user = userEvent.setup();
      const mockTools: Tool[] = [
        createMockTool(1, "test-gateway"),
        createMockTool(2, "test-gateway"),
      ];

      server.use(http.get("/tools", () => HttpResponse.json(mockTools)));

      renderWithRouter(<Tools />);

      await waitFor(() => {
        expect(screen.getByText("test-gateway")).toBeInTheDocument();
      });

      // Open dropdown menu
      const moreOptionsButton = screen.getByLabelText("More options for test-gateway");
      await user.click(moreOptionsButton);

      // Click View Details
      const viewDetailsItem = await screen.findByText("View Details");
      await user.click(viewDetailsItem);

      // Details panel should be visible
      await waitFor(() => {
        expect(screen.getByRole("region", { name: /Tools for test-gateway/i })).toBeInTheDocument();
      });

      // Panel shows the gateway name — it also appears in the card, so multiple matches expected
      expect(screen.getAllByText("test-gateway").length).toBeGreaterThan(0);
    });

    it("closes details panel when clicking close button", async () => {
      const user = userEvent.setup();
      const mockTools: Tool[] = [createMockTool(1, "test-gateway")];

      server.use(http.get("/tools", () => HttpResponse.json(mockTools)));

      renderWithRouter(<Tools />);

      await waitFor(() => {
        expect(screen.getByText("test-gateway")).toBeInTheDocument();
      });

      // Open details panel
      const moreOptionsButton = screen.getByLabelText("More options for test-gateway");
      await user.click(moreOptionsButton);
      const viewDetailsItem = await screen.findByText("View Details");
      await user.click(viewDetailsItem);

      // Wait for panel to open
      await waitFor(() => {
        expect(screen.getByRole("region", { name: /Tools for test-gateway/i })).toBeInTheDocument();
      });

      // Close the panel
      const closeButton = screen.getByLabelText("Close tool details");
      await user.click(closeButton);

      // Panel should be hidden
      await waitFor(() => {
        expect(
          screen.queryByRole("region", { name: /Tools for test-gateway/i }),
        ).not.toBeInTheDocument();
      });
    });

    it("closes details panel when pressing Escape key", async () => {
      const user = userEvent.setup();
      const mockTools: Tool[] = [createMockTool(1, "test-gateway")];

      server.use(http.get("/tools", () => HttpResponse.json(mockTools)));

      renderWithRouter(<Tools />);

      await waitFor(() => {
        expect(screen.getByText("test-gateway")).toBeInTheDocument();
      });

      // Open details panel
      const moreOptionsButton = screen.getByLabelText("More options for test-gateway");
      await user.click(moreOptionsButton);
      const viewDetailsItem = await screen.findByText("View Details");
      await user.click(viewDetailsItem);

      // Wait for panel to open
      await waitFor(() => {
        expect(screen.getByRole("region", { name: /Tools for test-gateway/i })).toBeInTheDocument();
      });

      // Press Escape
      await user.keyboard("{Escape}");

      // Panel should be hidden
      await waitFor(() => {
        expect(
          screen.queryByRole("region", { name: /Tools for test-gateway/i }),
        ).not.toBeInTheDocument();
      });
    });

    it("displays all tools from selected group in details panel", async () => {
      const user = userEvent.setup();
      const mockTools: Tool[] = [
        createMockTool(1, "multi-tool-gateway"),
        createMockTool(2, "multi-tool-gateway"),
        createMockTool(3, "multi-tool-gateway"),
      ];

      server.use(http.get("/tools", () => HttpResponse.json(mockTools)));

      renderWithRouter(<Tools />);

      await waitFor(() => {
        expect(screen.getByText("multi-tool-gateway")).toBeInTheDocument();
      });

      // Open details panel
      const moreOptionsButton = screen.getByLabelText("More options for multi-tool-gateway");
      await user.click(moreOptionsButton);
      const viewDetailsItem = await screen.findByText("View Details");
      await user.click(viewDetailsItem);

      // Wait for panel to open
      await waitFor(() => {
        expect(
          screen.getByRole("region", { name: /Tools for multi-tool-gateway/i }),
        ).toBeInTheDocument();
      });

      // All tools should be visible in the table (Name column shows customName || originalName)
      const panel = screen.getByRole("region", { name: /Tools for multi-tool-gateway/i });
      expect(within(panel).getAllByText("Tool 1").length).toBeGreaterThan(0);
      expect(within(panel).getAllByText("Tool 2").length).toBeGreaterThan(0);
      expect(within(panel).getAllByText("Tool 3").length).toBeGreaterThan(0);
    });

    it("shows correct integration type in details panel", async () => {
      const user = userEvent.setup();
      const mockTools: Tool[] = [
        {
          ...createMockTool(1, "mcp-gateway"),
          integrationType: "MCP",
        },
      ];

      server.use(http.get("/tools", () => HttpResponse.json(mockTools)));

      renderWithRouter(<Tools />);

      await waitFor(() => {
        expect(screen.getByText("mcp-gateway")).toBeInTheDocument();
      });

      // Open details panel
      const moreOptionsButton = screen.getByLabelText("More options for mcp-gateway");
      await user.click(moreOptionsButton);
      const viewDetailsItem = await screen.findByText("View Details");
      await user.click(viewDetailsItem);

      // "MCP Server" appears in both the panel subtitle and Component details Type row
      await waitFor(() => {
        expect(screen.getAllByText("MCP Server").length).toBeGreaterThan(0);
      });
    });

    it("handles opening details panel for different tool groups", async () => {
      const user = userEvent.setup();
      const mockTools: Tool[] = [createMockTool(1, "gateway-a"), createMockTool(2, "gateway-b")];

      server.use(http.get("/tools", () => HttpResponse.json(mockTools)));

      renderWithRouter(<Tools />);

      await waitFor(() => {
        expect(screen.getByText("gateway-a")).toBeInTheDocument();
      });

      // Open details for gateway-a
      const moreOptionsButtonA = screen.getByLabelText("More options for gateway-a");
      await user.click(moreOptionsButtonA);
      let viewDetailsItem = await screen.findByText("View Details");
      await user.click(viewDetailsItem);

      await waitFor(() => {
        expect(screen.getByRole("region", { name: /Tools for gateway-a/i })).toBeInTheDocument();
      });

      // Close panel
      const closeButton = screen.getByLabelText("Close tool details");
      await user.click(closeButton);

      await waitFor(() => {
        expect(
          screen.queryByRole("region", { name: /Tools for gateway-a/i }),
        ).not.toBeInTheDocument();
      });

      // Open details for gateway-b
      const moreOptionsButtonB = screen.getByLabelText("More options for gateway-b");
      await user.click(moreOptionsButtonB);
      viewDetailsItem = await screen.findByText("View Details");
      await user.click(viewDetailsItem);

      await waitFor(() => {
        expect(screen.getByRole("region", { name: /Tools for gateway-b/i })).toBeInTheDocument();
      });
    });
  });

  describe("Edit Tool", () => {
    // Helper: load tools, open the details panel, and return userEvent
    async function openDetailsPanel(gatewaySlug: string) {
      const user = userEvent.setup();
      await user.click(screen.getByLabelText(`More options for ${gatewaySlug}`));
      await user.click(await screen.findByText("View Details"));
      await waitFor(() => {
        expect(
          screen.getByRole("region", { name: new RegExp(`Tools for ${gatewaySlug}`, "i") }),
        ).toBeInTheDocument();
      });
      return user;
    }

    it("shows Edit option in the tool row dropdown when panel is open", async () => {
      const mockTools: Tool[] = [createMockTool(1, "test-gateway", true, true)];
      server.use(
        http.get("/tools", () => HttpResponse.json(mockTools)),
        http.get("/tools/tool-1", () => HttpResponse.json(mockTools[0])),
      );
      renderWithRouter(<Tools />);
      await waitFor(() => expect(screen.getByText("test-gateway")).toBeInTheDocument());

      const user = await openDetailsPanel("test-gateway");
      await user.click(screen.getByLabelText("More options"));

      expect(await screen.findByText("Edit")).toBeInTheDocument();
    });

    it("opens the edit form when Edit is clicked", async () => {
      const mockTools: Tool[] = [createMockTool(1, "test-gateway")];
      server.use(
        http.get("/tools", () => HttpResponse.json(mockTools)),
        http.get("/tools/tool-1", () => HttpResponse.json(mockTools[0])),
      );
      renderWithRouter(<Tools />);
      await waitFor(() => expect(screen.getByText("test-gateway")).toBeInTheDocument());

      const user = await openDetailsPanel("test-gateway");
      await user.click(screen.getByLabelText("More options"));
      await user.click(await screen.findByText("Edit"));

      await waitFor(() => {
        expect(screen.getByRole("heading", { name: "Edit tool" })).toBeInTheDocument();
      });
    });

    it("pre-populates the form with the tool's URL", async () => {
      const mockTool = createMockTool(1, "test-gateway");
      server.use(
        http.get("/tools", () => HttpResponse.json([mockTool])),
        http.get("/tools/tool-1", () => HttpResponse.json(mockTool)),
      );
      renderWithRouter(<Tools />);
      await waitFor(() => expect(screen.getByText("test-gateway")).toBeInTheDocument());

      const user = await openDetailsPanel("test-gateway");
      await user.click(screen.getByLabelText("More options"));
      await user.click(await screen.findByText("Edit"));

      await waitFor(() => {
        expect(screen.getByRole("heading", { name: "Edit tool" })).toBeInTheDocument();
      });

      expect(screen.getByLabelText(/URL/)).toHaveValue(mockTool.url);
    });

    it("sends PUT request with updated data, closes the form, and shows refreshed list", async () => {
      const originalTool: Tool = {
        ...createMockTool(1, "test-gateway"),
        integrationType: "REST",
        requestType: "POST",
        url: "https://api.example.com/v1",
        name: "tool-original",
      };
      const updatedTool: Tool = { ...originalTool, name: "tool-updated" };

      let putCalled = false;
      server.use(
        http.get("/tools", () => HttpResponse.json([putCalled ? updatedTool : originalTool])),
        http.get("/tools/tool-1", () => HttpResponse.json(originalTool)),
        http.put("/tools/tool-1", () => {
          putCalled = true;
          return HttpResponse.json(updatedTool);
        }),
      );

      renderWithRouter(<Tools />);
      await waitFor(() => expect(screen.getByText("test-gateway")).toBeInTheDocument());

      const user = await openDetailsPanel("test-gateway");
      await user.click(screen.getByLabelText("More options"));
      await user.click(await screen.findByText("Edit"));

      await waitFor(() => {
        expect(screen.getByRole("heading", { name: "Edit tool" })).toBeInTheDocument();
      });

      // Update the URL field so the form is dirty and valid
      const urlInput = screen.getByLabelText(/URL/);
      await user.clear(urlInput);
      await user.type(urlInput, "https://api.example.com/v2");

      await user.click(screen.getByRole("button", { name: "Update tool" }));

      // Form closes
      await waitFor(() => {
        expect(screen.queryByRole("heading", { name: "Edit tool" })).not.toBeInTheDocument();
      });

      // List refreshes — updated tool name is now shown in the card badge
      await waitFor(() => {
        expect(screen.getByText("tool-updated")).toBeInTheDocument();
      });
      expect(screen.queryByText("tool-original")).not.toBeInTheDocument();
    });

    it("shows Edit above Delete in the dropdown when both are available", async () => {
      const mockTools: Tool[] = [createMockTool(1, "test-gateway")];
      server.use(
        http.get("/tools", () => HttpResponse.json(mockTools)),
        http.get("/tools/tool-1", () => HttpResponse.json(mockTools[0])),
      );
      renderWithRouter(<Tools />);
      await waitFor(() => expect(screen.getByText("test-gateway")).toBeInTheDocument());

      const user = await openDetailsPanel("test-gateway");
      await user.click(screen.getByLabelText("More options"));

      const items = await screen.findAllByRole("menuitem");
      const labels = items.map((el) => el.textContent);
      expect(labels.indexOf("Edit")).toBeLessThan(labels.indexOf("Delete"));
    });
  });

  describe("Delete Tool", () => {
    // Helper: load tools, open the details panel for a given gateway, and return userEvent
    async function openDetailsPanel(gatewaySlug: string) {
      const user = userEvent.setup();
      const moreOptionsButton = screen.getByLabelText(`More options for ${gatewaySlug}`);
      await user.click(moreOptionsButton);
      const viewDetailsItem = await screen.findByText("View Details");
      await user.click(viewDetailsItem);
      await waitFor(() => {
        expect(
          screen.getByRole("region", { name: new RegExp(`Tools for ${gatewaySlug}`, "i") }),
        ).toBeInTheDocument();
      });
      return user;
    }

    beforeEach(() => {
      vi.mocked(toast.success).mockClear();
      vi.mocked(toast.error).mockClear();
    });

    it("shows Delete option in the tool row dropdown when panel is open", async () => {
      const mockTools: Tool[] = [createMockTool(1, "test-gateway")];
      server.use(http.get("/tools", () => HttpResponse.json(mockTools)));
      renderWithRouter(<Tools />);
      await waitFor(() => expect(screen.getByText("test-gateway")).toBeInTheDocument());

      const user = await openDetailsPanel("test-gateway");

      // "More options" button inside the table row (not the card-level one)
      const tableMoreOptions = screen.getByLabelText("More options");
      await user.click(tableMoreOptions);

      expect(await screen.findByText("Delete")).toBeInTheDocument();
    });

    it("opens a confirm dialog with the tool name when Delete is clicked", async () => {
      const mockTools: Tool[] = [createMockTool(1, "test-gateway")];
      server.use(http.get("/tools", () => HttpResponse.json(mockTools)));
      renderWithRouter(<Tools />);
      await waitFor(() => expect(screen.getByText("test-gateway")).toBeInTheDocument());

      const user = await openDetailsPanel("test-gateway");

      await user.click(screen.getByLabelText("More options"));
      await user.click(await screen.findByText("Delete"));

      await waitFor(() => {
        expect(screen.getByRole("dialog")).toBeInTheDocument();
      });
      const dialog = screen.getByRole("dialog");
      expect(within(dialog).getByText("Delete tool")).toBeInTheDocument();
      // Dialog description includes the tool name (createMockTool has no displayName, falls back to name)
      expect(
        within(dialog).getByText(/Are you sure you want to delete "Tool 1"/),
      ).toBeInTheDocument();
    });

    it("does not call the API when the confirm dialog is cancelled", async () => {
      const mockTools: Tool[] = [createMockTool(1, "test-gateway")];
      server.use(http.get("/tools", () => HttpResponse.json(mockTools)));
      const deleteSpy = vi.fn(() => HttpResponse.json(null, { status: 204 }));
      server.use(http.delete("/tools/:id", deleteSpy));

      renderWithRouter(<Tools />);
      await waitFor(() => expect(screen.getByText("test-gateway")).toBeInTheDocument());

      const user = await openDetailsPanel("test-gateway");
      await user.click(screen.getByLabelText("More options"));
      await user.click(await screen.findByText("Delete"));

      await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());

      await user.click(screen.getByRole("button", { name: /cancel/i }));

      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(deleteSpy).not.toHaveBeenCalled();
      expect(toast.error).not.toHaveBeenCalled();
    });

    it("calls the delete API, shows success toast, and closes the panel on confirm", async () => {
      const mockTools: Tool[] = [createMockTool(1, "test-gateway")];
      server.use(
        http.get("/tools", () => HttpResponse.json(mockTools)),
        http.delete("/tools/tool-1", () => new HttpResponse(null, { status: 204 })),
      );

      renderWithRouter(<Tools />);
      await waitFor(() => expect(screen.getByText("test-gateway")).toBeInTheDocument());

      const user = await openDetailsPanel("test-gateway");
      await user.click(screen.getByLabelText("More options"));
      await user.click(await screen.findByText("Delete"));

      await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
      await user.click(screen.getByRole("button", { name: /^delete$/i }));

      await waitFor(() => {
        expect(toast.success).toHaveBeenCalledWith(expect.stringContaining("Tool 1"));
      });

      // Details panel should close
      await waitFor(() => {
        expect(
          screen.queryByRole("region", { name: /Tools for test-gateway/i }),
        ).not.toBeInTheDocument();
      });
    });

    it("shows an error toast when the delete API returns a string detail", async () => {
      const mockTools: Tool[] = [createMockTool(1, "test-gateway")];
      server.use(
        http.get("/tools", () => HttpResponse.json(mockTools)),
        http.delete("/tools/tool-1", () =>
          HttpResponse.json({ detail: "Cannot delete: tool is in use" }, { status: 409 }),
        ),
      );

      renderWithRouter(<Tools />);
      await waitFor(() => expect(screen.getByText("test-gateway")).toBeInTheDocument());

      const user = await openDetailsPanel("test-gateway");
      await user.click(screen.getByLabelText("More options"));
      await user.click(await screen.findByText("Delete"));

      await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
      await user.click(screen.getByRole("button", { name: /^delete$/i }));

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith("Cannot delete: tool is in use");
      });
    });

    it("shows a generic error toast when the delete API returns no detail", async () => {
      const mockTools: Tool[] = [createMockTool(1, "test-gateway")];
      server.use(
        http.get("/tools", () => HttpResponse.json(mockTools)),
        http.delete("/tools/tool-1", () =>
          HttpResponse.json({ message: "Something went wrong" }, { status: 500 }),
        ),
      );

      renderWithRouter(<Tools />);
      await waitFor(() => expect(screen.getByText("test-gateway")).toBeInTheDocument());

      const user = await openDetailsPanel("test-gateway");
      await user.click(screen.getByLabelText("More options"));
      await user.click(await screen.findByText("Delete"));

      await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
      await user.click(screen.getByRole("button", { name: /^delete$/i }));

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("Failed to delete tool"));
      });
    });

    it("uses displayName in the dialog description when available", async () => {
      const mockTools: Tool[] = [
        { ...createMockTool(1, "test-gateway"), displayName: "My Custom Tool" },
      ];
      server.use(http.get("/tools", () => HttpResponse.json(mockTools)));

      renderWithRouter(<Tools />);
      await waitFor(() => expect(screen.getByText("test-gateway")).toBeInTheDocument());

      const user = await openDetailsPanel("test-gateway");
      await user.click(screen.getByLabelText("More options"));
      await user.click(await screen.findByText("Delete"));

      await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
      expect(within(screen.getByRole("dialog")).getByText(/My Custom Tool/)).toBeInTheDocument();
    });

    it("falls back to name in the dialog description when displayName is absent", async () => {
      const mockTools: Tool[] = [{ ...createMockTool(1, "test-gateway"), displayName: undefined }];
      server.use(http.get("/tools", () => HttpResponse.json(mockTools)));

      renderWithRouter(<Tools />);
      await waitFor(() => expect(screen.getByText("test-gateway")).toBeInTheDocument());

      const user = await openDetailsPanel("test-gateway");
      await user.click(screen.getByLabelText("More options"));
      await user.click(await screen.findByText("Delete"));

      await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
      expect(
        within(screen.getByRole("dialog")).getByText(/Are you sure you want to delete "Tool 1"/),
      ).toBeInTheDocument();
    });
  });

  describe("Toggle Tool (Activate/Deactivate)", () => {
    // Helper: load tools, open the details panel for a given gateway, and return userEvent
    async function openDetailsPanel(gatewaySlug: string) {
      const user = userEvent.setup();
      await user.click(screen.getByLabelText(`More options for ${gatewaySlug}`));
      await user.click(await screen.findByText("View Details"));
      await waitFor(() => {
        expect(
          screen.getByRole("region", { name: new RegExp(`Tools for ${gatewaySlug}`, "i") }),
        ).toBeInTheDocument();
      });
      return user;
    }

    beforeEach(() => {
      vi.mocked(toast.success).mockClear();
      vi.mocked(toast.error).mockClear();
    });

    it("shows Deactivate for an enabled tool and Edit, Deactivate, Delete in order", async () => {
      const mockTools: Tool[] = [createMockTool(1, "test-gateway", true, true)];
      server.use(http.get("/tools", () => HttpResponse.json(mockTools)));
      renderWithRouter(<Tools />);
      await waitFor(() => expect(screen.getByText("test-gateway")).toBeInTheDocument());

      const user = await openDetailsPanel("test-gateway");
      await user.click(screen.getByLabelText("More options"));

      const items = await screen.findAllByRole("menuitem");
      expect(items.map((el) => el.textContent)).toEqual(["Edit", "Deactivate", "Delete"]);
    });

    it("deactivates an active tool, patches the single tool, and shows a success toast", async () => {
      const activeTool = createMockTool(1, "test-gateway", true, true);
      const inactiveTool = { ...activeTool, enabled: false };

      let listFetches = 0;
      server.use(
        // The list is fetched once on mount; the toggle must NOT trigger another list fetch.
        http.get("/tools", () => {
          listFetches += 1;
          return HttpResponse.json([activeTool]);
        }),
        http.post("/tools/tool-1/state", ({ request }) => {
          expect(new URL(request.url).searchParams.get("activate")).toBe("false");
          return HttpResponse.json({ status: "success", tool: inactiveTool });
        }),
        // Only the affected tool is re-fetched and patched into the list.
        http.get("/tools/tool-1", () => HttpResponse.json(inactiveTool)),
      );

      renderWithRouter(<Tools />);
      await waitFor(() => expect(screen.getByText("test-gateway")).toBeInTheDocument());

      const user = await openDetailsPanel("test-gateway");
      // Status starts as Active
      expect(screen.getByText("Active")).toBeInTheDocument();

      await user.click(screen.getByLabelText("More options"));
      await user.click(await screen.findByText("Deactivate"));

      await waitFor(() => {
        expect(toast.success).toHaveBeenCalledWith(expect.stringContaining("Tool 1"));
      });

      // Status row reflects the patched single tool
      await waitFor(() => {
        expect(screen.getByText("Inactive")).toBeInTheDocument();
      });

      // The whole list was fetched only once (on mount), not again after the toggle
      expect(listFetches).toBe(1);
    });

    it("activates an inactive tool and shows a success toast", async () => {
      const inactiveTool = createMockTool(1, "test-gateway", false, true);
      const activeTool = { ...inactiveTool, enabled: true };

      server.use(
        http.get("/tools", () => HttpResponse.json([inactiveTool])),
        http.post("/tools/tool-1/state", ({ request }) => {
          expect(new URL(request.url).searchParams.get("activate")).toBe("true");
          return HttpResponse.json({ status: "success", tool: activeTool });
        }),
        http.get("/tools/tool-1", () => HttpResponse.json(activeTool)),
      );

      renderWithRouter(<Tools />);
      await waitFor(() => expect(screen.getByText("test-gateway")).toBeInTheDocument());

      const user = await openDetailsPanel("test-gateway");
      expect(screen.getByText("Inactive")).toBeInTheDocument();

      await user.click(screen.getByLabelText("More options"));
      await user.click(await screen.findByText("Activate"));

      await waitFor(() => {
        expect(toast.success).toHaveBeenCalledWith(expect.stringContaining("Tool 1"));
      });

      await waitFor(() => {
        expect(screen.getByText("Active")).toBeInTheDocument();
      });
    });

    it("shows an error toast and leaves status unchanged when the request fails", async () => {
      const activeTool = createMockTool(1, "test-gateway", true, true);
      server.use(
        http.get("/tools", () => HttpResponse.json([activeTool])),
        http.post("/tools/tool-1/state", () =>
          HttpResponse.json({ detail: "Permission denied" }, { status: 403 }),
        ),
      );

      renderWithRouter(<Tools />);
      await waitFor(() => expect(screen.getByText("test-gateway")).toBeInTheDocument());

      const user = await openDetailsPanel("test-gateway");
      await user.click(screen.getByLabelText("More options"));
      await user.click(await screen.findByText("Deactivate"));

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith("Permission denied");
      });

      // Status is unchanged
      expect(screen.getByText("Active")).toBeInTheDocument();
      expect(toast.success).not.toHaveBeenCalled();
    });
  });

  describe("Tool Interface Extended Fields", () => {
    it("handles tools with displayName field", async () => {
      const mockTools: Tool[] = [
        {
          ...createMockTool(1, "test-gateway"),
          displayName: "Custom Display Name",
        },
      ];

      server.use(http.get("/tools", () => HttpResponse.json(mockTools)));

      renderWithRouter(<Tools />);

      await waitFor(() => {
        expect(screen.getByText("test-gateway")).toBeInTheDocument();
      });

      // displayName is used in the details panel table, not in the card view
      expect(screen.getByText("Tool 1")).toBeInTheDocument();
    });

    it("handles tools with url field", async () => {
      const user = userEvent.setup();
      const mockTools: Tool[] = [
        {
          ...createMockTool(1, "test-gateway"),
          // URL must be ≤24 chars (truncateMiddle default) to avoid truncation in the assertion
          url: "https://api.example.com",
        },
      ];

      server.use(http.get("/tools", () => HttpResponse.json(mockTools)));

      renderWithRouter(<Tools />);

      await waitFor(() => {
        expect(screen.getByText("test-gateway")).toBeInTheDocument();
      });

      // Open details panel to see URL
      const moreOptionsButton = screen.getByLabelText("More options for test-gateway");
      await user.click(moreOptionsButton);
      const viewDetailsItem = await screen.findByText("View Details");
      await user.click(viewDetailsItem);

      await waitFor(() => {
        expect(screen.getByText("https://api.example.com")).toBeInTheDocument();
      });
    });

    it("handles tools with visibility field", async () => {
      const user = userEvent.setup();
      const mockTools: Tool[] = [
        {
          ...createMockTool(1, "test-gateway"),
          visibility: "team",
        },
      ];

      server.use(http.get("/tools", () => HttpResponse.json(mockTools)));

      renderWithRouter(<Tools />);

      await waitFor(() => {
        expect(screen.getByText("test-gateway")).toBeInTheDocument();
      });

      // Open details panel to see visibility
      const moreOptionsButton = screen.getByLabelText("More options for test-gateway");
      await user.click(moreOptionsButton);
      const viewDetailsItem = await screen.findByText("View Details");
      await user.click(viewDetailsItem);

      await waitFor(() => {
        expect(screen.getByText("Team")).toBeInTheDocument();
      });
    });

    it("handles tools with version field", async () => {
      const user = userEvent.setup();
      const mockTools: Tool[] = [
        {
          ...createMockTool(1, "test-gateway"),
          version: 2,
        },
      ];

      server.use(http.get("/tools", () => HttpResponse.json(mockTools)));

      renderWithRouter(<Tools />);

      await waitFor(() => {
        expect(screen.getByText("test-gateway")).toBeInTheDocument();
      });

      // Open details panel to see version
      const moreOptionsButton = screen.getByLabelText("More options for test-gateway");
      await user.click(moreOptionsButton);
      const viewDetailsItem = await screen.findByText("View Details");
      await user.click(viewDetailsItem);

      await waitFor(() => {
        // Version is displayed in the details panel
        const versionElements = screen.getAllByText("2");
        expect(versionElements.length).toBeGreaterThan(0);
      });
    });

    it("handles tools with audit fields", async () => {
      const mockTools: Tool[] = [
        {
          ...createMockTool(1, "test-gateway"),
          createdBy: "user@example.com",
          createdVia: "api",
          createdFromIp: "192.168.1.1",
          modifiedBy: "admin@example.com",
          modifiedVia: "ui",
        },
      ];

      server.use(http.get("/tools", () => HttpResponse.json(mockTools)));

      renderWithRouter(<Tools />);

      await waitFor(() => {
        expect(screen.getByText("test-gateway")).toBeInTheDocument();
      });

      // Audit fields are stored but not necessarily displayed in the UI
      // This test ensures they don't break the component
      expect(screen.getByText("Tool 1")).toBeInTheDocument();
    });

    it("handles tools with team and owner fields", async () => {
      const mockTools: Tool[] = [
        {
          ...createMockTool(1, "test-gateway"),
          team: "Engineering",
          teamId: "team-123",
          ownerEmail: "owner@example.com",
        },
      ];

      server.use(http.get("/tools", () => HttpResponse.json(mockTools)));

      renderWithRouter(<Tools />);

      await waitFor(() => {
        expect(screen.getByText("test-gateway")).toBeInTheDocument();
      });

      // Team and owner fields are stored but not necessarily displayed in the card view
      expect(screen.getByText("Tool 1")).toBeInTheDocument();
    });

    it("handles tools with inputSchema and outputSchema", async () => {
      const mockTools: Tool[] = [
        {
          ...createMockTool(1, "test-gateway"),
          inputSchema: {
            type: "object",
            properties: {
              query: { type: "string" },
            },
          },
          outputSchema: {
            type: "object",
            properties: {
              result: { type: "string" },
            },
          },
        },
      ];

      server.use(http.get("/tools", () => HttpResponse.json(mockTools)));

      renderWithRouter(<Tools />);

      await waitFor(() => {
        expect(screen.getByText("test-gateway")).toBeInTheDocument();
      });

      // Schemas are stored but not displayed in the card view
      expect(screen.getByText("Tool 1")).toBeInTheDocument();
    });
  });

  // Optimistic delete

  describe("Optimistic delete", () => {
    async function setup(mockTools: Tool[], gatewaySlug: string) {
      server.use(http.get("/tools", () => HttpResponse.json(mockTools)));
      renderWithRouter(<Tools />);
      await waitFor(() => expect(screen.getByText(gatewaySlug)).toBeInTheDocument());

      const user = userEvent.setup();
      await user.click(screen.getByLabelText(`More options for ${gatewaySlug}`));
      await user.click(await screen.findByText("View Details"));
      await waitFor(() =>
        expect(
          screen.getByRole("region", { name: new RegExp(`Tools for ${gatewaySlug}`, "i") }),
        ).toBeInTheDocument(),
      );
      return { user };
    }

    beforeEach(() => {
      vi.mocked(toast.success).mockClear();
      vi.mocked(toast.error).mockClear();
      server.resetHandlers();
    });

    it("removes the tool badge from the card grid immediately on confirm (before API responds)", async () => {
      const mockTools = [createMockTool(1, "opt-gateway")];

      let resolveDelete!: () => void;
      server.use(
        http.get("/tools", () => HttpResponse.json(mockTools)),
        http.delete(
          "/tools/tool-1",
          () =>
            new Promise<Response>((resolve) => {
              resolveDelete = () => resolve(new Response(null, { status: 204 }));
            }),
        ),
      );

      renderWithRouter(<Tools />);
      await waitFor(() => expect(screen.getByText("opt-gateway")).toBeInTheDocument());

      expect(screen.getByText("Tool 1")).toBeInTheDocument();

      const user = userEvent.setup();
      await user.click(screen.getByLabelText("More options for opt-gateway"));
      await user.click(await screen.findByText("View Details"));
      await waitFor(() =>
        expect(screen.getByRole("region", { name: /Tools for opt-gateway/i })).toBeInTheDocument(),
      );

      await user.click(screen.getByLabelText("More options"));
      await user.click(await screen.findByText("Delete"));
      await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
      await user.click(screen.getByRole("button", { name: /^delete$/i }));

      await waitFor(() => {
        expect(screen.queryByText("Tool 1")).not.toBeInTheDocument();
      });

      resolveDelete();
      await waitFor(() => {
        expect(toast.success).toHaveBeenCalledWith(expect.stringContaining("Tool 1"));
      });
    });

    it("rolls back: tool badge reappears in card grid when delete API fails", async () => {
      const mockTools = [createMockTool(1, "rollback-gateway")];
      server.use(
        http.get("/tools", () => HttpResponse.json(mockTools)),
        http.delete("/tools/tool-1", () =>
          HttpResponse.json({ detail: "Server error" }, { status: 500 }),
        ),
      );

      renderWithRouter(<Tools />);
      await waitFor(() => expect(screen.getByText("rollback-gateway")).toBeInTheDocument());

      const user = userEvent.setup();
      await user.click(screen.getByLabelText("More options for rollback-gateway"));
      await user.click(await screen.findByText("View Details"));
      await waitFor(() =>
        expect(
          screen.getByRole("region", { name: /Tools for rollback-gateway/i }),
        ).toBeInTheDocument(),
      );

      await user.click(screen.getByLabelText("More options"));
      await user.click(await screen.findByText("Delete"));
      await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
      await user.click(screen.getByRole("button", { name: /^delete$/i }));

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith("Server error");
      });

      await waitFor(() => {
        expect(screen.getByText("1 tool")).toBeInTheDocument();
      });
    });

    it("details panel closes immediately when the only tool in a group is deleted", async () => {
      const mockTools = [createMockTool(1, "solo-gateway")];
      server.use(
        http.get("/tools", () => HttpResponse.json(mockTools)),
        http.delete("/tools/tool-1", () => new HttpResponse(null, { status: 204 })),
      );

      const { user } = await setup(mockTools, "solo-gateway");

      await user.click(screen.getByLabelText("More options"));
      await user.click(await screen.findByText("Delete"));
      await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
      await user.click(screen.getByRole("button", { name: /^delete$/i }));

      await waitFor(() => {
        expect(
          screen.queryByRole("region", { name: /Tools for solo-gateway/i }),
        ).not.toBeInTheDocument();
      });
    });

    it("details panel stays open when one tool is deleted from a multi-tool group", async () => {
      const mockTools = [createMockTool(1, "multi-gateway"), createMockTool(2, "multi-gateway")];
      server.use(
        http.get("/tools", () => HttpResponse.json(mockTools)),
        http.delete("/tools/tool-1", () => new HttpResponse(null, { status: 204 })),
      );

      const { user } = await setup(mockTools, "multi-gateway");

      const moreOptionsButtons = screen.getAllByLabelText("More options");
      await user.click(moreOptionsButtons[0]);
      await user.click(await screen.findByText("Delete"));
      await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
      await user.click(screen.getByRole("button", { name: /^delete$/i }));

      await waitFor(() => {
        expect(
          screen.getByRole("region", { name: /Tools for multi-gateway/i }),
        ).toBeInTheDocument();
      });

      await waitFor(() => {
        expect(toast.success).toHaveBeenCalledWith(expect.stringContaining("Tool 1"));
      });
    });

    it("deleted tool row is removed from panel immediately while remaining tool stays visible", async () => {
      const mockTools = [createMockTool(1, "panel-gateway"), createMockTool(2, "panel-gateway")];

      let resolveDelete!: () => void;
      server.use(
        http.get("/tools", () => HttpResponse.json(mockTools)),
        http.delete(
          "/tools/tool-1",
          () =>
            new Promise<Response>((resolve) => {
              resolveDelete = () => resolve(new Response(null, { status: 204 }));
            }),
        ),
      );

      const { user } = await setup(mockTools, "panel-gateway");

      const panel = screen.getByRole("region", { name: /Tools for panel-gateway/i });

      expect(within(panel).getAllByText("Tool 1").length).toBeGreaterThan(0);
      expect(within(panel).getAllByText("Tool 2").length).toBeGreaterThan(0);

      const moreOptionsButtons = screen.getAllByLabelText("More options");
      await user.click(moreOptionsButtons[0]);
      await user.click(await screen.findByText("Delete"));
      await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
      await user.click(screen.getByRole("button", { name: /^delete$/i }));

      await waitFor(() => {
        expect(within(panel).queryByText("Tool 1")).not.toBeInTheDocument();
      });
      expect(within(panel).getAllByText("Tool 2").length).toBeGreaterThan(0);

      resolveDelete();
      await waitFor(() => {
        expect(toast.success).toHaveBeenCalledWith(expect.stringContaining("Tool 1"));
      });
    });

    it("details panel re-opens after rollback when group had multiple tools", async () => {
      const mockTools = [createMockTool(1, "reopen-gateway"), createMockTool(2, "reopen-gateway")];
      server.use(
        http.get("/tools", () => HttpResponse.json(mockTools)),
        http.delete("/tools/tool-1", () =>
          HttpResponse.json({ detail: "Forbidden" }, { status: 403 }),
        ),
      );

      const { user } = await setup(mockTools, "reopen-gateway");

      const moreOptionsButtons = screen.getAllByLabelText("More options");
      await user.click(moreOptionsButtons[0]);
      await user.click(await screen.findByText("Delete"));
      await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
      await user.click(screen.getByRole("button", { name: /^delete$/i }));

      await waitFor(() => {
        expect(
          screen.getByRole("region", { name: /Tools for reopen-gateway/i }),
        ).toBeInTheDocument();
      });

      const panel = screen.getByRole("region", { name: /Tools for reopen-gateway/i });
      expect(within(panel).getAllByText("Tool 1").length).toBeGreaterThan(0);
      expect(within(panel).getAllByText("Tool 2").length).toBeGreaterThan(0);

      expect(toast.error).toHaveBeenCalledWith("Forbidden");
    });

    it("shows generic error toast when delete returns no detail field", async () => {
      const mockTools = [createMockTool(1, "err-gateway")];
      server.use(
        http.get("/tools", () => HttpResponse.json(mockTools)),
        http.delete("/tools/tool-1", () =>
          HttpResponse.json({ message: "Unexpected error" }, { status: 500 }),
        ),
      );

      const { user } = await setup(mockTools, "err-gateway");

      await user.click(screen.getByLabelText("More options"));
      await user.click(await screen.findByText("Delete"));
      await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
      await user.click(screen.getByRole("button", { name: /^delete$/i }));

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("Failed to delete tool"));
      });
    });

    it("rollback restores the exact pre-delete tool list captured via the updater", async () => {
      const mockTools = [
        createMockTool(1, "snapshot-gateway"),
        createMockTool(2, "snapshot-gateway"),
        createMockTool(3, "snapshot-gateway"),
      ];
      server.use(
        http.get("/tools", () => HttpResponse.json(mockTools)),
        http.delete("/tools/tool-1", () =>
          HttpResponse.json({ detail: "Conflict" }, { status: 409 }),
        ),
      );

      const { user } = await setup(mockTools, "snapshot-gateway");

      const moreOptionsButtons = screen.getAllByLabelText("More options");
      await user.click(moreOptionsButtons[0]);
      await user.click(await screen.findByText("Delete"));
      await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
      await user.click(screen.getByRole("button", { name: /^delete$/i }));

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith("Conflict");
      });

      await waitFor(() => {
        expect(screen.getByText("3 tools")).toBeInTheDocument();
      });

      const panel = screen.getByRole("region", { name: /Tools for snapshot-gateway/i });
      expect(within(panel).getAllByText("Tool 1").length).toBeGreaterThan(0);
      expect(within(panel).getAllByText("Tool 2").length).toBeGreaterThan(0);
      expect(within(panel).getAllByText("Tool 3").length).toBeGreaterThan(0);
    });

    it("optimistic removal happens before API resolves even when delete is delayed", async () => {
      const mockTools = [
        createMockTool(10, "delayed-gateway"),
        createMockTool(11, "delayed-gateway"),
      ];

      let resolveDelete!: () => void;
      server.use(
        http.get("/tools", () => HttpResponse.json(mockTools)),
        http.delete(
          "/tools/tool-10",
          () =>
            new Promise<Response>((resolve) => {
              resolveDelete = () => resolve(new Response(null, { status: 204 }));
            }),
        ),
      );

      const { user } = await setup(mockTools, "delayed-gateway");

      const panel = screen.getByRole("region", { name: /Tools for delayed-gateway/i });
      expect(within(panel).getAllByText("Tool 10").length).toBeGreaterThan(0);
      expect(within(panel).getAllByText("Tool 11").length).toBeGreaterThan(0);

      const moreOptionsButtons = screen.getAllByLabelText("More options");
      await user.click(moreOptionsButtons[0]);
      await user.click(await screen.findByText("Delete"));
      await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
      await user.click(screen.getByRole("button", { name: /^delete$/i }));

      await waitFor(() => {
        expect(within(panel).queryByText("Tool 10")).not.toBeInTheDocument();
      });
      expect(within(panel).getAllByText("Tool 11").length).toBeGreaterThan(0);

      expect(toast.success).not.toHaveBeenCalled();

      resolveDelete();
      await waitFor(() => {
        expect(toast.success).toHaveBeenCalledWith(expect.stringContaining("Tool 10"));
      });
    });
  });

  describe("inline tag add", () => {
    it("shows a newly added tag in the details drawer (patches cache, no full refetch)", async () => {
      const user = userEvent.setup();
      const tool: Tool = { ...createMockTool(1, "test-gateway"), tags: ["tag1"] };

      let toolsListCalls = 0;
      server.use(
        http.get("/tools", () => {
          toolsListCalls += 1;
          return HttpResponse.json([tool]);
        }),
        http.put("/tools/:id", () => HttpResponse.json({ ...tool, tags: ["tag1", "alerts"] })),
      );

      renderWithRouter(<Tools />);

      await waitFor(() => expect(screen.getByText("test-gateway")).toBeInTheDocument());
      const listCallsAfterLoad = toolsListCalls;

      await user.click(screen.getByLabelText("More options for test-gateway"));
      await user.click(await screen.findByText("View Details"));

      const drawer = await screen.findByRole("region", { name: /Tools for test-gateway/i });
      expect(within(drawer).queryByText("alerts")).not.toBeInTheDocument();

      await user.click(within(drawer).getByRole("button", { name: "Add tags" }));
      await user.type(
        within(drawer).getByPlaceholderText("Add tags separated with commas"),
        "alerts",
      );
      await user.click(within(drawer).getByRole("button", { name: "Add" }));

      expect(await within(drawer).findByText("alerts")).toBeInTheDocument();
      expect(toolsListCalls).toBe(listCallsAfterLoad);
    });
  });
});
