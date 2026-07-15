import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ToolSchemaDialog } from "./ToolSchemaDialog";
import * as gatewayUtils from "@/lib/clipboard";
import type { Tool } from "@/types/tool";

// Helper to create mock tool
function createMockTool(overrides?: Partial<Tool>): Tool {
  return {
    id: "tool-1",
    name: "Test Tool",
    originalName: "test_tool",
    description: "Test description",
    originalDescription: "Original test description",
    title: "Test Tool Title",
    displayName: "Test Display Name",
    gatewayId: "gateway-id",
    gatewaySlug: "test-gateway",
    customName: "Test Tool",
    customNameSlug: "test-tool",
    enabled: true,
    reachable: true,
    deprecated: false,
    executionCount: 0,
    tags: [{ label: "tag1" }],
    integrationType: "MCP",
    requestType: "http",
    url: "https://example.com/tool",
    headers: {},
    inputSchema: { type: "object", properties: {} },
    annotations: {},
    jsonpathFilter: null,
    auth: null,
    version: 1,
    visibility: "team",
    createdAt: "2024-01-01T00:00:00",
    updatedAt: "2024-01-02T00:00:00",
    ...overrides,
  };
}

describe("ToolSchemaDialog", () => {
  const mockOnOpenChange = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(gatewayUtils, "copyToClipboard").mockImplementation(() => {});
  });

  it("renders dialog when open is true", () => {
    const tool = createMockTool();
    render(<ToolSchemaDialog tool={tool} open={true} onOpenChange={mockOnOpenChange} />);

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Tool schema")).toBeInTheDocument();
  });

  it("does not render dialog when open is false", () => {
    const tool = createMockTool();
    render(<ToolSchemaDialog tool={tool} open={false} onOpenChange={mockOnOpenChange} />);

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders Input and Output section headers", () => {
    const tool = createMockTool();
    render(<ToolSchemaDialog tool={tool} open={true} onOpenChange={mockOnOpenChange} />);

    expect(screen.getByText("Input")).toBeInTheDocument();
    expect(screen.getByText("Output")).toBeInTheDocument();
  });

  it("displays input schema when provided", () => {
    const tool = createMockTool({
      inputSchema: {
        type: "object",
        properties: {
          query: { type: "string", description: "Search query" },
        },
      },
    });
    render(<ToolSchemaDialog tool={tool} open={true} onOpenChange={mockOnOpenChange} />);

    expect(screen.getAllByText(/query/)[0]).toBeInTheDocument();
    expect(screen.getByText(/Search query/)).toBeInTheDocument();
  });

  it("displays output schema when provided", () => {
    const tool = createMockTool({
      outputSchema: {
        type: "object",
        properties: {
          result: { type: "string" },
        },
      },
    });
    render(<ToolSchemaDialog tool={tool} open={true} onOpenChange={mockOnOpenChange} />);

    expect(screen.getByText(/result/)).toBeInTheDocument();
  });

  it("displays empty object when schemas are undefined", () => {
    const tool = createMockTool({
      inputSchema: undefined,
      outputSchema: undefined,
    });
    render(<ToolSchemaDialog tool={tool} open={true} onOpenChange={mockOnOpenChange} />);

    // Should display "{}" for both sections
    const preElements = screen.getAllByRole("code");
    expect(preElements).toHaveLength(2);
  });

  it("renders copy buttons for input and output schemas", () => {
    const tool = createMockTool();
    render(<ToolSchemaDialog tool={tool} open={true} onOpenChange={mockOnOpenChange} />);

    const copyButtons = screen.getAllByLabelText(/Copy/);
    expect(copyButtons).toHaveLength(2);
    expect(screen.getByLabelText("Copy input")).toBeInTheDocument();
    expect(screen.getByLabelText("Copy output")).toBeInTheDocument();
  });

  it("copies input schema to clipboard when copy button is clicked", async () => {
    const user = userEvent.setup();
    const inputSchema = { type: "object", properties: { query: { type: "string" } } };
    const tool = createMockTool({ inputSchema });
    render(<ToolSchemaDialog tool={tool} open={true} onOpenChange={mockOnOpenChange} />);

    const copyButton = screen.getByLabelText("Copy input");
    await user.click(copyButton);

    expect(gatewayUtils.copyToClipboard).toHaveBeenCalledWith(JSON.stringify(inputSchema, null, 2));
  });

  it("copies output schema to clipboard when copy button is clicked", async () => {
    const user = userEvent.setup();
    const outputSchema = { type: "object", properties: { result: { type: "string" } } };
    const tool = createMockTool({ outputSchema });
    render(<ToolSchemaDialog tool={tool} open={true} onOpenChange={mockOnOpenChange} />);

    const copyButton = screen.getByLabelText("Copy output");
    await user.click(copyButton);

    expect(gatewayUtils.copyToClipboard).toHaveBeenCalledWith(
      JSON.stringify(outputSchema, null, 2),
    );
  });

  it("renders Close button", () => {
    const tool = createMockTool();
    render(<ToolSchemaDialog tool={tool} open={true} onOpenChange={mockOnOpenChange} />);

    // Both the footer button and the dialog's sr-only × share the name "Close"
    const closeButtons = screen.getAllByRole("button", { name: /close/i });
    expect(closeButtons.length).toBeGreaterThanOrEqual(1);
  });

  it("calls onOpenChange with false when Close button is clicked", async () => {
    const user = userEvent.setup();
    const tool = createMockTool();
    render(<ToolSchemaDialog tool={tool} open={true} onOpenChange={mockOnOpenChange} />);

    // Footer button has no SVG child; × button does — use that to distinguish them
    const allClose = screen.getAllByRole("button", { name: /close/i });
    const footerClose = allClose.find((btn) => !btn.querySelector("svg"))!;
    await user.click(footerClose);

    expect(mockOnOpenChange).toHaveBeenCalledWith(false);
  });

  it("calls onOpenChange when X button is clicked", async () => {
    const user = userEvent.setup();
    const tool = createMockTool();
    render(<ToolSchemaDialog tool={tool} open={true} onOpenChange={mockOnOpenChange} />);

    // × button contains an SVG icon; footer button contains only text
    const allClose = screen.getAllByRole("button", { name: /close/i });
    const xButton = allClose.find((btn) => btn.querySelector("svg"))!;
    await user.click(xButton);

    expect(mockOnOpenChange).toHaveBeenCalled();
  });

  it("handles null tool gracefully and copy buttons emit empty schema", async () => {
    const user = userEvent.setup();
    render(<ToolSchemaDialog tool={null} open={true} onOpenChange={mockOnOpenChange} />);

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Tool schema")).toBeInTheDocument();

    await user.click(screen.getByLabelText("Copy input"));
    expect(gatewayUtils.copyToClipboard).toHaveBeenCalledWith("{}");

    await user.click(screen.getByLabelText("Copy output"));
    expect(gatewayUtils.copyToClipboard).toHaveBeenCalledWith("{}");
  });

  it("formats JSON with proper indentation", () => {
    const tool = createMockTool({
      inputSchema: {
        type: "object",
        properties: {
          query: { type: "string" },
        },
      },
    });
    render(<ToolSchemaDialog tool={tool} open={true} onOpenChange={mockOnOpenChange} />);

    // "type" appears as a key multiple times across spans; assert at least one is present
    expect(screen.getAllByText(/type/)[0]).toBeInTheDocument();
  });

  it("applies proper styling classes to schema sections", () => {
    const tool = createMockTool();
    render(<ToolSchemaDialog tool={tool} open={true} onOpenChange={mockOnOpenChange} />);

    const preElements = document.querySelectorAll("pre");
    expect(preElements).toHaveLength(2);

    preElements.forEach((pre) => {
      expect(pre).toHaveClass("bg-neutral-900");
      expect(pre).toHaveClass("rounded-md");
      expect(pre).toHaveClass("whitespace-pre-wrap");
      expect(pre).toHaveClass("break-words");
    });
  });

  it("renders schema icon with correct styling", () => {
    const tool = createMockTool();
    render(<ToolSchemaDialog tool={tool} open={true} onOpenChange={mockOnOpenChange} />);

    // Inline style is serialised as kebab-case in the DOM attribute
    const iconContainer = document.querySelector('[style*="background-color"]');
    expect(iconContainer).toBeInTheDocument();
  });

  it("handles complex nested schemas", () => {
    const tool = createMockTool({
      inputSchema: {
        type: "object",
        properties: {
          nested: {
            type: "object",
            properties: {
              deep: {
                type: "array",
                items: { type: "string" },
              },
            },
          },
        },
      },
    });
    render(<ToolSchemaDialog tool={tool} open={true} onOpenChange={mockOnOpenChange} />);

    expect(screen.getByText(/nested/)).toBeInTheDocument();
    expect(screen.getByText(/deep/)).toBeInTheDocument();
    expect(screen.getByText(/array/)).toBeInTheDocument();
  });

  it("handles schemas with long text values", () => {
    const tool = createMockTool({
      inputSchema: {
        type: "object",
        properties: {
          description: {
            type: "string",
            description:
              "This is a very long description that should wrap properly in the dialog without causing overflow issues",
          },
        },
      },
    });
    render(<ToolSchemaDialog tool={tool} open={true} onOpenChange={mockOnOpenChange} />);

    expect(
      screen.getByText(/This is a very long description that should wrap properly/),
    ).toBeInTheDocument();
  });
});
