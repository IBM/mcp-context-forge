import { describe, it, expect, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders as render } from "@/test/test-utils";
import { ToolDetailsPanel } from "./ToolDetailsPanel";
import type { Tool } from "@/types/tool";

// Helper to create mock tools
function createMockTool(id: number, overrides?: Partial<Tool>): Tool {
  return {
    id: `tool-${id}`,
    name: `Tool ${id}`,
    originalName: `tool_${id}`,
    description: `Description for tool ${id}`,
    originalDescription: `Original description for tool ${id}`,
    title: `Tool ${id} Title`,
    displayName: `Display Name ${id}`,
    gatewayId: `gateway-id`,
    gatewaySlug: "test-gateway",
    customName: "",
    customNameSlug: `tool-${id}`,
    enabled: true,
    reachable: true,
    deprecated: false,
    executionCount: 0,
    tags: [{ label: "tag1" }, { label: "tag2" }],
    integrationType: "MCP",
    requestType: "http",
    url: `https://example.com/tool-${id}`,
    headers: {},
    annotations: {},
    jsonpathFilter: null,
    auth: null,
    version: 1,
    visibility: "team",
    team: "Engineering",
    teamId: "team-123",
    ownerEmail: "owner@example.com",
    createdAt: "2024-01-01T00:00:00",
    updatedAt: "2024-01-02T00:00:00",
    createdBy: "user@example.com",
    createdVia: "api",
    createdFromIp: "192.168.1.1",
    createdUserAgent: "Mozilla/5.0",
    modifiedBy: "admin@example.com",
    modifiedFromIp: "192.168.1.2",
    modifiedVia: "ui",
    modifiedUserAgent: "Mozilla/5.0",
    inputSchema: { type: "object" },
    outputSchema: { type: "object" },
    ...overrides,
  };
}

describe("ToolDetailsPanel", () => {
  const mockOnClose = vi.fn();

  beforeEach(() => {
    mockOnClose.mockClear();
  });

  it("renders nothing when closed", () => {
    const tools = [createMockTool(1)];
    const { container } = render(
      <ToolDetailsPanel
        tools={tools}
        gatewaySlug="test-gateway"
        open={false}
        onClose={mockOnClose}
      />,
    );

    const aside = container.querySelector('aside[role="region"]');
    expect(aside).toHaveAttribute("data-state", "closed");
    expect(aside).toHaveAttribute("aria-hidden", "true");
  });

  it("renders panel when open", () => {
    const tools = [createMockTool(1)];
    const { container } = render(
      <ToolDetailsPanel
        tools={tools}
        gatewaySlug="test-gateway"
        open={true}
        onClose={mockOnClose}
      />,
    );

    const aside = container.querySelector('aside[role="region"]');
    expect(aside).toHaveAttribute("data-state", "open");
    expect(aside).toHaveAttribute("aria-hidden", "false");
  });

  it("displays gateway name and integration type", () => {
    const tools = [createMockTool(1, { integrationType: "MCP" })];
    render(
      <ToolDetailsPanel
        tools={tools}
        gatewaySlug="test-gateway"
        open={true}
        onClose={mockOnClose}
      />,
    );

    expect(screen.getAllByText("test-gateway").length).toBeGreaterThan(0);
    // "MCP Server" appears in the subtitle and in Component details Type row
    expect(screen.getAllByText("MCP Server").length).toBeGreaterThan(0);
  });

  it("displays all tools in table", () => {
    const tools = [createMockTool(1), createMockTool(2), createMockTool(3)];
    render(
      <ToolDetailsPanel
        tools={tools}
        gatewaySlug="test-gateway"
        open={true}
        onClose={mockOnClose}
      />,
    );

    expect(screen.getByText("tool_1")).toBeInTheDocument();
    expect(screen.getByText("tool_2")).toBeInTheDocument();
    expect(screen.getByText("tool_3")).toBeInTheDocument();
  });

  it("selects first tool by default when panel opens", async () => {
    const tools = [createMockTool(1), createMockTool(2)];
    render(
      <ToolDetailsPanel
        tools={tools}
        gatewaySlug="test-gateway"
        open={true}
        onClose={mockOnClose}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Component details")).toBeInTheDocument();
    });

    // First tool should be selected and its details shown
    expect(screen.getByText("Display Name 1")).toBeInTheDocument();
  });

  it("calls onClose when close button is clicked", async () => {
    const user = userEvent.setup();
    const tools = [createMockTool(1)];
    render(
      <ToolDetailsPanel
        tools={tools}
        gatewaySlug="test-gateway"
        open={true}
        onClose={mockOnClose}
      />,
    );

    const closeButton = screen.getByLabelText("Close tool details");
    await user.click(closeButton);

    expect(mockOnClose).toHaveBeenCalledTimes(1);
  });

  it("calls onClose when Escape key is pressed", async () => {
    const user = userEvent.setup();
    const tools = [createMockTool(1)];
    render(
      <ToolDetailsPanel
        tools={tools}
        gatewaySlug="test-gateway"
        open={true}
        onClose={mockOnClose}
      />,
    );

    await user.keyboard("{Escape}");

    expect(mockOnClose).toHaveBeenCalledTimes(1);
  });

  it("calls onClose when backdrop is clicked", async () => {
    const user = userEvent.setup();
    const tools = [createMockTool(1)];
    const { container } = render(
      <ToolDetailsPanel
        tools={tools}
        gatewaySlug="test-gateway"
        open={true}
        onClose={mockOnClose}
      />,
    );

    const backdrop = container.querySelector('[data-state="open"][aria-hidden="true"]');
    expect(backdrop).toBeInTheDocument();

    if (backdrop) {
      await user.click(backdrop);
      expect(mockOnClose).toHaveBeenCalledTimes(1);
    }
  });

  it("displays tool status correctly", async () => {
    const tools = [
      createMockTool(1, { enabled: true, reachable: true }),
      createMockTool(2, { enabled: false, reachable: false }),
    ];
    render(
      <ToolDetailsPanel
        tools={tools}
        gatewaySlug="test-gateway"
        open={true}
        onClose={mockOnClose}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Active")).toBeInTheDocument();
    });
  });

  it("displays visibility label correctly", async () => {
    const tools = [createMockTool(1, { visibility: "team" })];
    render(
      <ToolDetailsPanel
        tools={tools}
        gatewaySlug="test-gateway"
        open={true}
        onClose={mockOnClose}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Team")).toBeInTheDocument();
    });
  });

  it("displays public visibility correctly", async () => {
    const tools = [createMockTool(1, { visibility: "public" })];
    render(
      <ToolDetailsPanel
        tools={tools}
        gatewaySlug="test-gateway"
        open={true}
        onClose={mockOnClose}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Public")).toBeInTheDocument();
    });
  });

  it("displays private visibility correctly", async () => {
    const tools = [createMockTool(1, { visibility: "private" })];
    render(
      <ToolDetailsPanel
        tools={tools}
        gatewaySlug="test-gateway"
        open={true}
        onClose={mockOnClose}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Private")).toBeInTheDocument();
    });
  });

  it("displays integration type labels correctly", async () => {
    const testCases = [
      { type: "MCP", label: "MCP Server" },
      { type: "REST", label: "REST API tools" },
      { type: "GRPC", label: "gRPC Service" },
    ];

    for (const { type, label } of testCases) {
      const tools = [createMockTool(1, { integrationType: type })];
      const { unmount } = render(
        <ToolDetailsPanel
          tools={tools}
          gatewaySlug="test-gateway"
          open={true}
          onClose={mockOnClose}
        />,
      );

      await waitFor(() => {
        // label may appear in both the subtitle and the Component details Type row
        expect(screen.getAllByText(label).length).toBeGreaterThan(0);
      });

      unmount();
    }
  });

  it("displays tool version", async () => {
    const tools = [createMockTool(1, { version: 2 })];
    render(
      <ToolDetailsPanel
        tools={tools}
        gatewaySlug="test-gateway"
        open={true}
        onClose={mockOnClose}
      />,
    );

    await waitFor(() => {
      const versionElements = screen.getAllByText("2");
      expect(versionElements.length).toBeGreaterThan(0);
    });
  });

  it("displays tool URL with copy button", async () => {
    // URL must be ≤24 chars (truncateMiddle default) to avoid truncation in the assertion
    const tools = [createMockTool(1, { url: "https://api.example.com" })];
    render(
      <ToolDetailsPanel
        tools={tools}
        gatewaySlug="test-gateway"
        open={true}
        onClose={mockOnClose}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("https://api.example.com")).toBeInTheDocument();
    });

    expect(screen.getByLabelText("Copy URL")).toBeInTheDocument();
  });

  it("displays tool tags", async () => {
    const tools = [
      createMockTool(1, {
        tags: [{ label: "production" }, { label: "critical" }, { label: "v2" }],
      }),
    ];
    render(
      <ToolDetailsPanel
        tools={tools}
        gatewaySlug="test-gateway"
        open={true}
        onClose={mockOnClose}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("production")).toBeInTheDocument();
    });

    expect(screen.getByText("critical")).toBeInTheDocument();
    expect(screen.getByText("v2")).toBeInTheDocument();
  });

  it("displays add button when no tags", async () => {
    const tools = [createMockTool(1, { tags: [] })];
    render(
      <ToolDetailsPanel
        tools={tools}
        gatewaySlug="test-gateway"
        open={true}
        onClose={mockOnClose}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("add")).toBeInTheDocument();
    });
  });

  it("displays formatted creation date", async () => {
    const tools = [createMockTool(1, { createdAt: "2024-01-15T10:30:45.123Z" })];
    render(
      <ToolDetailsPanel
        tools={tools}
        gatewaySlug="test-gateway"
        open={true}
        onClose={mockOnClose}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("2024-01-15T10:30:45")).toBeInTheDocument();
    });
  });

  it("displays formatted update date", async () => {
    const tools = [createMockTool(1, { updatedAt: "2024-02-20T14:25:30.456Z" })];
    render(
      <ToolDetailsPanel
        tools={tools}
        gatewaySlug="test-gateway"
        open={true}
        onClose={mockOnClose}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("2024-02-20T14:25:30")).toBeInTheDocument();
    });
  });

  it("displays 'Not available' for missing dates", async () => {
    const tools = [createMockTool(1, { createdAt: "", updatedAt: "" })];
    render(
      <ToolDetailsPanel
        tools={tools}
        gatewaySlug="test-gateway"
        open={true}
        onClose={mockOnClose}
      />,
    );

    await waitFor(() => {
      const notAvailableElements = screen.getAllByText("Not available");
      expect(notAvailableElements.length).toBeGreaterThan(0);
    });
  });

  it("displays request type", async () => {
    const tools = [createMockTool(1, { requestType: "websocket" })];
    render(
      <ToolDetailsPanel
        tools={tools}
        gatewaySlug="test-gateway"
        open={true}
        onClose={mockOnClose}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("websocket")).toBeInTheDocument();
    });
  });

  it("handles tool selection from table", async () => {
    const user = userEvent.setup();
    const tools = [createMockTool(1), createMockTool(2)];
    render(
      <ToolDetailsPanel
        tools={tools}
        gatewaySlug="test-gateway"
        open={true}
        onClose={mockOnClose}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("tool_1")).toBeInTheDocument();
    });

    // Click on second tool
    const tool2Row = screen.getByText("tool_2").closest("tr");
    expect(tool2Row).toBeInTheDocument();

    if (tool2Row) {
      await user.click(tool2Row);

      // Second tool details should now be shown
      await waitFor(() => {
        expect(screen.getByText("Display Name 2")).toBeInTheDocument();
      });
    }
  });

  it("resets selected tool when panel closes", async () => {
    const tools = [createMockTool(1)];
    const { rerender } = render(
      <ToolDetailsPanel
        tools={tools}
        gatewaySlug="test-gateway"
        open={true}
        onClose={mockOnClose}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Display Name 1")).toBeInTheDocument();
    });

    // Close panel
    rerender(
      <ToolDetailsPanel
        tools={tools}
        gatewaySlug="test-gateway"
        open={false}
        onClose={mockOnClose}
      />,
    );

    // Reopen panel
    rerender(
      <ToolDetailsPanel
        tools={tools}
        gatewaySlug="test-gateway"
        open={true}
        onClose={mockOnClose}
      />,
    );

    // First tool should be selected again
    await waitFor(() => {
      expect(screen.getByText("Display Name 1")).toBeInTheDocument();
    });
  });

  it("focuses close button when panel opens", async () => {
    const tools = [createMockTool(1)];
    render(
      <ToolDetailsPanel
        tools={tools}
        gatewaySlug="test-gateway"
        open={true}
        onClose={mockOnClose}
      />,
    );

    await waitFor(() => {
      const closeButton = screen.getByLabelText("Close tool details");
      expect(closeButton).toHaveFocus();
    });
  });

  it("handles unreachable tool status", async () => {
    const tools = [createMockTool(1, { enabled: true, reachable: false })];
    render(
      <ToolDetailsPanel
        tools={tools}
        gatewaySlug="test-gateway"
        open={true}
        onClose={mockOnClose}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Unreachable")).toBeInTheDocument();
    });
  });

  it("handles inactive tool status", async () => {
    const tools = [createMockTool(1, { enabled: false, reachable: true })];
    render(
      <ToolDetailsPanel
        tools={tools}
        gatewaySlug="test-gateway"
        open={true}
        onClose={mockOnClose}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Inactive")).toBeInTheDocument();
    });
  });

  it("handles tools without URL", async () => {
    const tools = [createMockTool(1, { url: null })];
    render(
      <ToolDetailsPanel
        tools={tools}
        gatewaySlug="test-gateway"
        open={true}
        onClose={mockOnClose}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Component details")).toBeInTheDocument();
    });

    // URL row should not be present
    expect(screen.queryByLabelText("Copy URL")).not.toBeInTheDocument();
  });

  describe("onDeleteTool propagation", () => {
    it("passes onDeleteTool down to the table so the Delete item appears", async () => {
      const user = userEvent.setup();
      const mockOnDeleteTool = vi.fn();
      const tools = [createMockTool(1)];
      render(
        <ToolDetailsPanel
          tools={tools}
          gatewaySlug="test-gateway"
          open={true}
          onClose={mockOnClose}
          onDeleteTool={mockOnDeleteTool}
        />,
      );

      await user.click(screen.getByLabelText("More options"));
      expect(await screen.findByText("Delete")).toBeInTheDocument();
    });

    it("calls onDeleteTool with the correct tool id when Delete is clicked", async () => {
      const user = userEvent.setup();
      const mockOnDeleteTool = vi.fn();
      const tools = [createMockTool(1, { id: "tool-panel-xyz" })];
      render(
        <ToolDetailsPanel
          tools={tools}
          gatewaySlug="test-gateway"
          open={true}
          onClose={mockOnClose}
          onDeleteTool={mockOnDeleteTool}
        />,
      );

      await user.click(screen.getByLabelText("More options"));
      await user.click(await screen.findByText("Delete"));

      expect(mockOnDeleteTool).toHaveBeenCalledOnce();
      expect(mockOnDeleteTool).toHaveBeenCalledWith("tool-panel-xyz");
    });

    it("does not show Delete item when onDeleteTool is not provided", async () => {
      const user = userEvent.setup();
      const tools = [createMockTool(1)];
      render(
        <ToolDetailsPanel
          tools={tools}
          gatewaySlug="test-gateway"
          open={true}
          onClose={mockOnClose}
        />,
      );

      await user.click(screen.getByLabelText("More options"));

      expect(screen.queryByText("Delete")).not.toBeInTheDocument();
    });
  });

  it("generates unique heading ID based on gateway slug", () => {
    const tools = [createMockTool(1)];
    const { container } = render(
      <ToolDetailsPanel
        tools={tools}
        gatewaySlug="my-custom-gateway"
        open={true}
        onClose={mockOnClose}
      />,
    );

    const heading = container.querySelector("#tool-details-heading-my-custom-gateway");
    expect(heading).toBeInTheDocument();
  });

  describe("inline tag add", () => {
    it("calls onAddTag with the merged, de-duplicated tag list", async () => {
      const user = userEvent.setup();
      const onAddTag = vi.fn().mockResolvedValue(undefined);
      const tools = [createMockTool(1, { id: "tool-1", tags: ["tag1", "tag2"] })];

      render(
        <ToolDetailsPanel
          tools={tools}
          gatewaySlug="test-gateway"
          open
          selectedToolId="tool-1"
          onClose={mockOnClose}
          onAddTag={onAddTag}
        />,
      );

      await user.click(screen.getByRole("button", { name: "Add tags" }));
      await user.type(
        screen.getByPlaceholderText("Add tags separated with commas"),
        "alpha, tag1, beta",
      );
      await user.click(screen.getByRole("button", { name: "Add" }));

      // "tag1" already exists and is dropped; the new tags are appended.
      expect(onAddTag).toHaveBeenCalledWith("tool-1", ["tag1", "tag2", "alpha", "beta"]);
    });

    it("disables the add-tag trigger when onAddTag is omitted", () => {
      const tools = [createMockTool(1, { id: "tool-1", tags: ["tag1"] })];

      render(
        <ToolDetailsPanel
          tools={tools}
          gatewaySlug="test-gateway"
          open
          selectedToolId="tool-1"
          onClose={mockOnClose}
        />,
      );

      expect(screen.getByRole("button", { name: "Add tags" })).toBeDisabled();
    });
  });
});
