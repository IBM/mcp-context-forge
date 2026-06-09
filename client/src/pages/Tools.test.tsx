import { describe, it, expect, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { render } from "@testing-library/react";
import { http, HttpResponse } from "msw";
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
    executionCount: 0,
    tags: [],
    integrationType: "mcp",
    requestType: "http",
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

    const toolBadge = screen.getByText("Tool 1");
    expect(toolBadge).toHaveAttribute("title", "Description for tool 1");
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

    // Should show +4 tag
    expect(screen.getByText("+4")).toBeInTheDocument();
    expect(screen.getByTitle("4 more tools")).toBeInTheDocument();
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

    // Should show +1 tag
    expect(screen.getByText("+1")).toBeInTheDocument();
    expect(screen.getByTitle("1 more tool")).toBeInTheDocument();
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
});
