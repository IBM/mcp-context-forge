import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ToolsTable } from "./ToolsTable";
import * as gatewayUtils from "@/components/gateways/utils";
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
    executionCount: 0,
    tags: ["tag1", "tag2"],
    integrationType: "MCP",
    requestType: "http",
    url: `https://example.com/tool-${id}`,
    version: 1,
    visibility: "team",
    createdAt: "2024-01-01T00:00:00",
    updatedAt: "2024-01-02T00:00:00",
    ...overrides,
  };
}

describe("ToolsTable", () => {
  const mockOnSelectTool = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mockOnSelectTool.mockClear();
    vi.spyOn(gatewayUtils, "copyToClipboard").mockImplementation(() => {});
  });

  it("renders table with correct headers", () => {
    const tools = [createMockTool(1)];
    render(<ToolsTable tools={tools} onSelectTool={mockOnSelectTool} />);

    expect(screen.getByText("Tool")).toBeInTheDocument();
    expect(screen.getByText("Name")).toBeInTheDocument();
    expect(screen.getByText("Tool ID")).toBeInTheDocument();
    expect(screen.getByText("Schema")).toBeInTheDocument();
  });

  it("renders all tools in the table", () => {
    const tools = [createMockTool(1), createMockTool(2), createMockTool(3)];
    render(<ToolsTable tools={tools} onSelectTool={mockOnSelectTool} />);

    expect(screen.getByText("Display Name 1")).toBeInTheDocument();
    expect(screen.getByText("Display Name 2")).toBeInTheDocument();
    expect(screen.getByText("Display Name 3")).toBeInTheDocument();
  });

  it("displays displayName when available", () => {
    const tools = [createMockTool(1, { displayName: "Custom Display Name" })];
    render(<ToolsTable tools={tools} onSelectTool={mockOnSelectTool} />);

    expect(screen.getByText("Custom Display Name")).toBeInTheDocument();
  });

  it("falls back to title when displayName is not available", () => {
    const tools = [createMockTool(1, { displayName: undefined, title: "Tool Title" })];
    render(<ToolsTable tools={tools} onSelectTool={mockOnSelectTool} />);

    expect(screen.getByText("Tool Title")).toBeInTheDocument();
  });

  it("falls back to name when displayName and title are not available", () => {
    const tools = [
      createMockTool(1, { displayName: undefined, title: undefined, name: "Tool Name" }),
    ];
    render(<ToolsTable tools={tools} onSelectTool={mockOnSelectTool} />);

    expect(screen.getByText("Tool Name")).toBeInTheDocument();
  });

  it("displays original name for each tool", () => {
    const tools = [createMockTool(1), createMockTool(2)];
    render(<ToolsTable tools={tools} onSelectTool={mockOnSelectTool} />);

    expect(screen.getByText("tool_1")).toBeInTheDocument();
    expect(screen.getByText("tool_2")).toBeInTheDocument();
  });

  it("displays truncated tool IDs", () => {
    const tools = [
      createMockTool(1, { id: "very-long-tool-id-that-should-be-truncated-in-the-middle" }),
    ];
    render(<ToolsTable tools={tools} onSelectTool={mockOnSelectTool} />);

    // truncateMiddle("very-long-tool-id-...", 18) → edgeLength=7 → "very-lo...-middle"
    const idCell = screen.getByText("very-lo...-middle");
    expect(idCell).toBeInTheDocument();
  });

  it("calls onSelectTool when row is clicked", async () => {
    const user = userEvent.setup();
    const tools = [createMockTool(1)];
    render(<ToolsTable tools={tools} onSelectTool={mockOnSelectTool} />);

    const row = screen.getByText("Display Name 1").closest("tr");
    expect(row).toBeInTheDocument();

    if (row) {
      await user.click(row);
      expect(mockOnSelectTool).toHaveBeenCalledWith(tools[0]);
    }
  });

  it("highlights selected tool row", () => {
    const tools = [createMockTool(1), createMockTool(2)];
    render(<ToolsTable tools={tools} selectedToolId="tool-1" onSelectTool={mockOnSelectTool} />);

    const selectedRow = screen.getByText("Display Name 1").closest("tr");
    expect(selectedRow).toHaveAttribute("data-state", "selected");

    const unselectedRow = screen.getByText("Display Name 2").closest("tr");
    expect(unselectedRow).not.toHaveAttribute("data-state", "selected");
  });

  it("renders copy button for original name", () => {
    const tools = [createMockTool(1)];
    render(<ToolsTable tools={tools} onSelectTool={mockOnSelectTool} />);

    const copyButton = screen.getByLabelText("Copy tool_1");
    expect(copyButton).toBeInTheDocument();
  });

  it("copies original name to clipboard when copy button is clicked", async () => {
    const user = userEvent.setup();
    const tools = [createMockTool(1, { originalName: "my_custom_tool" })];
    render(<ToolsTable tools={tools} onSelectTool={mockOnSelectTool} />);

    const copyButton = screen.getByLabelText("Copy my_custom_tool");
    await user.click(copyButton);

    expect(gatewayUtils.copyToClipboard).toHaveBeenCalledWith("my_custom_tool");
  });

  it("does not trigger row selection when copy button is clicked", async () => {
    const user = userEvent.setup();
    const tools = [createMockTool(1)];
    render(<ToolsTable tools={tools} onSelectTool={mockOnSelectTool} />);

    const copyButton = screen.getByLabelText("Copy tool_1");
    await user.click(copyButton);

    expect(mockOnSelectTool).not.toHaveBeenCalled();
  });

  it("renders copy button for tool ID", () => {
    const tools = [createMockTool(1)];
    render(<ToolsTable tools={tools} onSelectTool={mockOnSelectTool} />);

    const copyButton = screen.getByLabelText("Copy tool ID");
    expect(copyButton).toBeInTheDocument();
  });

  it("copies tool ID to clipboard when copy button is clicked", async () => {
    const user = userEvent.setup();
    const tools = [createMockTool(1, { id: "tool-abc-123" })];
    render(<ToolsTable tools={tools} onSelectTool={mockOnSelectTool} />);

    const copyButtons = screen.getAllByLabelText("Copy tool ID");
    await user.click(copyButtons[0]);

    expect(gatewayUtils.copyToClipboard).toHaveBeenCalledWith("tool-abc-123");
  });

  it("renders schema view button", () => {
    const tools = [createMockTool(1)];
    render(<ToolsTable tools={tools} onSelectTool={mockOnSelectTool} />);

    const schemaButton = screen.getByLabelText("View schema");
    expect(schemaButton).toBeInTheDocument();
  });

  it("opens schema dialog when schema button is clicked", async () => {
    const user = userEvent.setup();
    const tools = [
      createMockTool(1, {
        inputSchema: { type: "object", properties: { query: { type: "string" } } },
        outputSchema: { type: "object", properties: { result: { type: "string" } } },
      }),
    ];
    render(<ToolsTable tools={tools} onSelectTool={mockOnSelectTool} />);

    const schemaButton = screen.getByLabelText("View schema");
    await user.click(schemaButton);

    // Dialog should be visible
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Tool schema")).toBeInTheDocument();
  });

  it("does not trigger row selection when schema button is clicked", async () => {
    const user = userEvent.setup();
    const tools = [createMockTool(1)];
    render(<ToolsTable tools={tools} onSelectTool={mockOnSelectTool} />);

    const schemaButton = screen.getByLabelText("View schema");
    await user.click(schemaButton);

    expect(mockOnSelectTool).not.toHaveBeenCalled();
  });

  it("closes schema dialog when Close button is clicked", async () => {
    const user = userEvent.setup();
    const tools = [createMockTool(1)];
    render(<ToolsTable tools={tools} onSelectTool={mockOnSelectTool} />);

    // Open dialog
    const schemaButton = screen.getByLabelText("View schema");
    await user.click(schemaButton);
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    // Close dialog — two buttons share the name "Close" (footer button + dialog's sr-only × button);
    // the footer button is first in DOM order since Radix appends × after children
    const [closeButton] = screen.getAllByRole("button", { name: /close/i });
    await user.click(closeButton);

    // Dialog should be closed
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders more options button", () => {
    const tools = [createMockTool(1)];
    render(<ToolsTable tools={tools} onSelectTool={mockOnSelectTool} />);

    const moreButton = screen.getByLabelText("More options");
    expect(moreButton).toBeInTheDocument();
  });

  it("does not trigger row selection when more options button is clicked", async () => {
    const user = userEvent.setup();
    const tools = [createMockTool(1)];
    render(<ToolsTable tools={tools} onSelectTool={mockOnSelectTool} />);

    const moreButton = screen.getByLabelText("More options");
    await user.click(moreButton);

    expect(mockOnSelectTool).not.toHaveBeenCalled();
  });

  it("renders empty table when no tools provided", () => {
    render(<ToolsTable tools={[]} onSelectTool={mockOnSelectTool} />);

    expect(screen.getByText("Tool")).toBeInTheDocument();
    expect(screen.getByText("Name")).toBeInTheDocument();
    expect(screen.getByText("Tool ID")).toBeInTheDocument();
    expect(screen.getByText("Schema")).toBeInTheDocument();

    // No rows should be present — thead is first rowgroup, tbody is second
    const [, tbody] = screen.getAllByRole("rowgroup");
    expect(tbody.children).toHaveLength(0);
  });

  it("handles multiple tools with same display name", () => {
    const tools = [
      createMockTool(1, { displayName: "Same Name", originalName: "tool_a" }),
      createMockTool(2, { displayName: "Same Name", originalName: "tool_b" }),
    ];
    render(<ToolsTable tools={tools} onSelectTool={mockOnSelectTool} />);

    const displayNames = screen.getAllByText("Same Name");
    expect(displayNames).toHaveLength(2);

    // Original names should be different
    expect(screen.getByText("tool_a")).toBeInTheDocument();
    expect(screen.getByText("tool_b")).toBeInTheDocument();
  });

  it("applies cursor-pointer class to rows", () => {
    const tools = [createMockTool(1)];
    render(<ToolsTable tools={tools} onSelectTool={mockOnSelectTool} />);

    const row = screen.getByText("Display Name 1").closest("tr");
    expect(row).toHaveClass("cursor-pointer");
  });

  it("renders table with proper ARIA structure", () => {
    const tools = [createMockTool(1)];
    render(<ToolsTable tools={tools} onSelectTool={mockOnSelectTool} />);

    const table = screen.getByRole("table");
    expect(table).toBeInTheDocument();

    const columnHeaders = screen.getAllByRole("columnheader");
    expect(columnHeaders).toHaveLength(5); // Tool, Name, Tool ID, Schema, More options

    const rows = screen.getAllByRole("row");
    expect(rows.length).toBeGreaterThan(1); // Header row + data rows
  });

  it("handles very long tool names with line-clamp", () => {
    const tools = [
      createMockTool(1, {
        displayName: "This is a very long tool name that should be clamped to one line",
      }),
    ];
    render(<ToolsTable tools={tools} onSelectTool={mockOnSelectTool} />);

    const displayName = screen.getByText(
      "This is a very long tool name that should be clamped to one line",
    );
    const span = displayName.closest("span");
    expect(span).toHaveClass("line-clamp-1");
  });

  describe("delete dropdown (onDeleteTool provided)", () => {
    it("renders a dropdown instead of a plain button when onDeleteTool is provided", async () => {
      const user = userEvent.setup();
      const mockOnDeleteTool = vi.fn();
      const tools = [createMockTool(1)];
      render(
        <ToolsTable
          tools={tools}
          onSelectTool={mockOnSelectTool}
          onDeleteTool={mockOnDeleteTool}
        />,
      );

      const moreButton = screen.getByLabelText("More options");
      await user.click(moreButton);

      expect(await screen.findByText("Delete")).toBeInTheDocument();
    });

    it("calls onDeleteTool with the tool id when Delete is clicked", async () => {
      const user = userEvent.setup();
      const mockOnDeleteTool = vi.fn();
      const tools = [createMockTool(1, { id: "tool-xyz" })];
      render(
        <ToolsTable
          tools={tools}
          onSelectTool={mockOnSelectTool}
          onDeleteTool={mockOnDeleteTool}
        />,
      );

      await user.click(screen.getByLabelText("More options"));
      await user.click(await screen.findByText("Delete"));

      expect(mockOnDeleteTool).toHaveBeenCalledOnce();
      expect(mockOnDeleteTool).toHaveBeenCalledWith("tool-xyz");
    });

    it("does not call onSelectTool when Delete is clicked", async () => {
      const user = userEvent.setup();
      const mockOnDeleteTool = vi.fn();
      const tools = [createMockTool(1)];
      render(
        <ToolsTable
          tools={tools}
          onSelectTool={mockOnSelectTool}
          onDeleteTool={mockOnDeleteTool}
        />,
      );

      await user.click(screen.getByLabelText("More options"));
      await user.click(await screen.findByText("Delete"));

      expect(mockOnSelectTool).not.toHaveBeenCalled();
    });

    it("does not show Delete item when onDeleteTool is not provided", async () => {
      const user = userEvent.setup();
      const tools = [createMockTool(1)];
      render(<ToolsTable tools={tools} onSelectTool={mockOnSelectTool} />);

      await user.click(screen.getByLabelText("More options"));

      expect(screen.queryByText("Delete")).not.toBeInTheDocument();
    });
  });

  describe("edit dropdown (onEditTool provided)", () => {
    it("shows Edit item in dropdown when onEditTool is provided", async () => {
      const user = userEvent.setup();
      const tools = [createMockTool(1)];
      render(<ToolsTable tools={tools} onSelectTool={mockOnSelectTool} onEditTool={vi.fn()} />);

      await user.click(screen.getByLabelText("More options"));

      expect(await screen.findByText("Edit")).toBeInTheDocument();
    });

    it("calls onEditTool with the full tool object when Edit is clicked", async () => {
      const user = userEvent.setup();
      const mockOnEditTool = vi.fn();
      const tool = createMockTool(1, { id: "tool-abc" });
      render(
        <ToolsTable tools={[tool]} onSelectTool={mockOnSelectTool} onEditTool={mockOnEditTool} />,
      );

      await user.click(screen.getByLabelText("More options"));
      await user.click(await screen.findByText("Edit"));

      expect(mockOnEditTool).toHaveBeenCalledOnce();
      expect(mockOnEditTool).toHaveBeenCalledWith(tool);
    });

    it("renders Edit above Delete when both callbacks are provided", async () => {
      const user = userEvent.setup();
      const tools = [createMockTool(1)];
      render(
        <ToolsTable
          tools={tools}
          onSelectTool={mockOnSelectTool}
          onEditTool={vi.fn()}
          onDeleteTool={vi.fn()}
        />,
      );

      await user.click(screen.getByLabelText("More options"));

      const items = await screen.findAllByRole("menuitem");
      const labels = items.map((el) => el.textContent);
      expect(labels.indexOf("Edit")).toBeLessThan(labels.indexOf("Delete"));
    });

    it("opens dropdown when only onEditTool is provided", async () => {
      const user = userEvent.setup();
      const tools = [createMockTool(1)];
      render(<ToolsTable tools={tools} onSelectTool={mockOnSelectTool} onEditTool={vi.fn()} />);

      await user.click(screen.getByLabelText("More options"));

      expect(await screen.findByText("Edit")).toBeInTheDocument();
      expect(screen.queryByText("Delete")).not.toBeInTheDocument();
    });

    it("does not call onSelectTool when Edit is clicked", async () => {
      const user = userEvent.setup();
      const tools = [createMockTool(1)];
      render(<ToolsTable tools={tools} onSelectTool={mockOnSelectTool} onEditTool={vi.fn()} />);

      await user.click(screen.getByLabelText("More options"));
      await user.click(await screen.findByText("Edit"));

      expect(mockOnSelectTool).not.toHaveBeenCalled();
    });
  });

  it("handles tools with special characters in names", () => {
    const tools = [
      createMockTool(1, {
        displayName: "Tool with @#$% special chars",
        originalName: "tool_with_special_chars",
      }),
    ];
    render(<ToolsTable tools={tools} onSelectTool={mockOnSelectTool} />);

    expect(screen.getByText("Tool with @#$% special chars")).toBeInTheDocument();
    expect(screen.getByText("tool_with_special_chars")).toBeInTheDocument();
  });

  it("maintains selection state across re-renders", () => {
    const tools = [createMockTool(1), createMockTool(2)];
    const { rerender } = render(
      <ToolsTable tools={tools} selectedToolId="tool-1" onSelectTool={mockOnSelectTool} />,
    );

    let selectedRow = screen.getByText("Display Name 1").closest("tr");
    expect(selectedRow).toHaveAttribute("data-state", "selected");

    // Re-render with same selection
    rerender(<ToolsTable tools={tools} selectedToolId="tool-1" onSelectTool={mockOnSelectTool} />);

    selectedRow = screen.getByText("Display Name 1").closest("tr");
    expect(selectedRow).toHaveAttribute("data-state", "selected");
  });

  it("updates selection when selectedToolId changes", () => {
    const tools = [createMockTool(1), createMockTool(2)];
    const { rerender } = render(
      <ToolsTable tools={tools} selectedToolId="tool-1" onSelectTool={mockOnSelectTool} />,
    );

    const selectedRow = screen.getByText("Display Name 1").closest("tr");
    expect(selectedRow).toHaveAttribute("data-state", "selected");

    // Change selection
    rerender(<ToolsTable tools={tools} selectedToolId="tool-2" onSelectTool={mockOnSelectTool} />);

    const previouslySelectedRow = screen.getByText("Display Name 1").closest("tr");
    expect(previouslySelectedRow).not.toHaveAttribute("data-state", "selected");

    const newSelectedRow = screen.getByText("Display Name 2").closest("tr");
    expect(newSelectedRow).toHaveAttribute("data-state", "selected");
  });

  it("handles null selectedToolId", () => {
    const tools = [createMockTool(1), createMockTool(2)];
    render(<ToolsTable tools={tools} selectedToolId={null} onSelectTool={mockOnSelectTool} />);

    const row1 = screen.getByText("Display Name 1").closest("tr");
    const row2 = screen.getByText("Display Name 2").closest("tr");

    expect(row1).not.toHaveAttribute("data-state", "selected");
    expect(row2).not.toHaveAttribute("data-state", "selected");
  });

  it("handles undefined selectedToolId", () => {
    const tools = [createMockTool(1), createMockTool(2)];
    render(<ToolsTable tools={tools} onSelectTool={mockOnSelectTool} />);

    const row1 = screen.getByText("Display Name 1").closest("tr");
    const row2 = screen.getByText("Display Name 2").closest("tr");

    expect(row1).not.toHaveAttribute("data-state", "selected");
    expect(row2).not.toHaveAttribute("data-state", "selected");
  });
});
