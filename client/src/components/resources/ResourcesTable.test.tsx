import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders as render } from "@/test/test-utils";
import { ResourcesTable } from "./ResourcesTable";
import * as clipboardUtils from "@/lib/clipboard";
import type { ResourceRead } from "@/generated/types";

type Resource = NonNullable<ResourceRead>;

// Helper to create mock resources
function createMockResource(id: number, overrides?: Partial<Resource>): Resource {
  return {
    id: `resource-${id}`,
    name: `Resource ${id}`,
    description: `Description for resource ${id}`,
    title: `Resource ${id} Title`,
    gatewayId: "gateway-id",
    enabled: true,
    uri: `resource://example/${id}`,
    uriTemplate: undefined,
    mimeType: "application/json",
    size: 0,
    version: 1,
    visibility: "public",
    tags: ["tag1", "tag2"],
    createdAt: "2024-01-01T00:00:00",
    updatedAt: "2024-01-02T00:00:00",
    ...overrides,
  };
}

describe("ResourcesTable", () => {
  const mockOnSelectResource = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mockOnSelectResource.mockClear();
    vi.spyOn(clipboardUtils, "copyToClipboard").mockImplementation(() => {});
  });

  it("renders table with correct headers", () => {
    const resources = [createMockResource(1)];
    render(<ResourcesTable resources={resources} onSelectResource={mockOnSelectResource} />);

    expect(screen.getByText("Resource")).toBeInTheDocument();
    expect(screen.getByText("URI")).toBeInTheDocument();
    expect(screen.getByText("Resource ID")).toBeInTheDocument();
  });

  it("renders all resources in the table", () => {
    const resources = [createMockResource(1), createMockResource(2), createMockResource(3)];
    render(<ResourcesTable resources={resources} onSelectResource={mockOnSelectResource} />);

    expect(screen.getByText("Resource 1 Title")).toBeInTheDocument();
    expect(screen.getByText("Resource 2 Title")).toBeInTheDocument();
    expect(screen.getByText("Resource 3 Title")).toBeInTheDocument();
  });

  it("displays title when available", () => {
    const resources = [createMockResource(1, { title: "Custom Title" })];
    render(<ResourcesTable resources={resources} onSelectResource={mockOnSelectResource} />);

    expect(screen.getByText("Custom Title")).toBeInTheDocument();
  });

  it("falls back to name when title is not available", () => {
    const resources = [createMockResource(1, { title: null, name: "Resource Name" })];
    render(<ResourcesTable resources={resources} onSelectResource={mockOnSelectResource} />);

    expect(screen.getByText("Resource Name")).toBeInTheDocument();
  });

  it("displays the resource URI for each row", () => {
    const resources = [
      createMockResource(1, { uri: "resource://a" }),
      createMockResource(2, { uri: "resource://b" }),
    ];
    render(<ResourcesTable resources={resources} onSelectResource={mockOnSelectResource} />);

    expect(screen.getByText("resource://a")).toBeInTheDocument();
    expect(screen.getByText("resource://b")).toBeInTheDocument();
  });

  it("prefers uriTemplate over uri when both are present", () => {
    const resources = [
      createMockResource(1, { uri: "resource://plain", uriTemplate: "resource://{id}" }),
    ];
    render(<ResourcesTable resources={resources} onSelectResource={mockOnSelectResource} />);

    expect(screen.getByText("resource://{id}")).toBeInTheDocument();
    expect(screen.queryByText("resource://plain")).not.toBeInTheDocument();
  });

  it("displays truncated resource IDs", () => {
    const resources = [
      createMockResource(1, {
        id: "very-long-resource-id-that-should-be-truncated-in-the-middle",
      }),
    ];
    render(<ResourcesTable resources={resources} onSelectResource={mockOnSelectResource} />);

    // truncateMiddle("very-long-resource-id-...", 18) → edgeLength=7 → "very-lo...-middle"
    expect(screen.getByText("very-lo...-middle")).toBeInTheDocument();
  });

  it("calls onSelectResource when row is clicked", async () => {
    const user = userEvent.setup();
    const resources = [createMockResource(1)];
    render(<ResourcesTable resources={resources} onSelectResource={mockOnSelectResource} />);

    const row = screen.getByText("Resource 1 Title").closest("tr");
    expect(row).toBeInTheDocument();

    if (row) {
      await user.click(row);
      expect(mockOnSelectResource).toHaveBeenCalledWith(resources[0]);
    }
  });

  it("highlights selected resource row", () => {
    const resources = [createMockResource(1), createMockResource(2)];
    render(
      <ResourcesTable
        resources={resources}
        selectedResourceId="resource-1"
        onSelectResource={mockOnSelectResource}
      />,
    );

    const selectedRow = screen.getByText("Resource 1 Title").closest("tr");
    expect(selectedRow).toHaveAttribute("data-state", "selected");

    const unselectedRow = screen.getByText("Resource 2 Title").closest("tr");
    expect(unselectedRow).not.toHaveAttribute("data-state", "selected");
  });

  it("copies URI to clipboard when copy button is clicked", async () => {
    const user = userEvent.setup();
    const resources = [createMockResource(1, { uri: "resource://my-uri" })];
    render(<ResourcesTable resources={resources} onSelectResource={mockOnSelectResource} />);

    const copyButton = screen.getByLabelText("Copy resource://my-uri");
    await user.click(copyButton);

    expect(clipboardUtils.copyToClipboard).toHaveBeenCalledWith("resource://my-uri");
  });

  it("does not trigger row selection when the URI copy button is clicked", async () => {
    const user = userEvent.setup();
    const resources = [createMockResource(1)];
    render(<ResourcesTable resources={resources} onSelectResource={mockOnSelectResource} />);

    const copyButton = screen.getByLabelText(/^Copy resource:\/\//);
    await user.click(copyButton);

    expect(mockOnSelectResource).not.toHaveBeenCalled();
  });

  it("copies resource ID to clipboard when copy button is clicked", async () => {
    const user = userEvent.setup();
    const resources = [createMockResource(1, { id: "resource-abc-123" })];
    render(<ResourcesTable resources={resources} onSelectResource={mockOnSelectResource} />);

    const copyButton = screen.getByLabelText("Copy resource ID");
    await user.click(copyButton);

    expect(clipboardUtils.copyToClipboard).toHaveBeenCalledWith("resource-abc-123");
  });

  it("renders empty table when no resources provided", () => {
    render(<ResourcesTable resources={[]} onSelectResource={mockOnSelectResource} />);

    expect(screen.getByText("Resource")).toBeInTheDocument();
    expect(screen.getByText("URI")).toBeInTheDocument();
    expect(screen.getByText("Resource ID")).toBeInTheDocument();

    const [, tbody] = screen.getAllByRole("rowgroup");
    expect(tbody.children).toHaveLength(0);
  });

  it("applies cursor-pointer class to rows", () => {
    const resources = [createMockResource(1)];
    render(<ResourcesTable resources={resources} onSelectResource={mockOnSelectResource} />);

    const row = screen.getByText("Resource 1 Title").closest("tr");
    expect(row).toHaveClass("cursor-pointer");
  });

  it("renders table with proper ARIA structure", () => {
    const resources = [createMockResource(1)];
    render(<ResourcesTable resources={resources} onSelectResource={mockOnSelectResource} />);

    const table = screen.getByRole("table");
    expect(table).toBeInTheDocument();

    const columnHeaders = screen.getAllByRole("columnheader");
    expect(columnHeaders).toHaveLength(4); // Resource, URI, Resource ID, More options

    const rows = screen.getAllByRole("row");
    expect(rows.length).toBeGreaterThan(1); // Header row + data rows
  });

  it("handles very long resource names with line-clamp", () => {
    const resources = [
      createMockResource(1, {
        title: "This is a very long resource title that should be clamped to one line",
      }),
    ];
    render(<ResourcesTable resources={resources} onSelectResource={mockOnSelectResource} />);

    const title = screen.getByText(
      "This is a very long resource title that should be clamped to one line",
    );
    const span = title.closest("span");
    expect(span).toHaveClass("line-clamp-1");
  });

  describe("delete dropdown (onDeleteResource provided)", () => {
    it("renders a dropdown instead of a plain button when onDeleteResource is provided", async () => {
      const user = userEvent.setup();
      const mockOnDeleteResource = vi.fn();
      const resources = [createMockResource(1)];
      render(
        <ResourcesTable
          resources={resources}
          onSelectResource={mockOnSelectResource}
          onDeleteResource={mockOnDeleteResource}
        />,
      );

      const moreButton = screen.getByLabelText("More options");
      await user.click(moreButton);

      expect(await screen.findByText("Delete")).toBeInTheDocument();
    });

    it("calls onDeleteResource with the resource id when Delete is clicked", async () => {
      const user = userEvent.setup();
      const mockOnDeleteResource = vi.fn();
      const resources = [createMockResource(1, { id: "resource-xyz" })];
      render(
        <ResourcesTable
          resources={resources}
          onSelectResource={mockOnSelectResource}
          onDeleteResource={mockOnDeleteResource}
        />,
      );

      await user.click(screen.getByLabelText("More options"));
      await user.click(await screen.findByText("Delete"));

      expect(mockOnDeleteResource).toHaveBeenCalledOnce();
      expect(mockOnDeleteResource).toHaveBeenCalledWith("resource-xyz");
    });

    it("does not call onSelectResource when Delete is clicked", async () => {
      const user = userEvent.setup();
      const mockOnDeleteResource = vi.fn();
      const resources = [createMockResource(1)];
      render(
        <ResourcesTable
          resources={resources}
          onSelectResource={mockOnSelectResource}
          onDeleteResource={mockOnDeleteResource}
        />,
      );

      await user.click(screen.getByLabelText("More options"));
      await user.click(await screen.findByText("Delete"));

      expect(mockOnSelectResource).not.toHaveBeenCalled();
    });

    it("does not show Delete item when onDeleteResource is not provided", async () => {
      const user = userEvent.setup();
      const resources = [createMockResource(1)];
      render(<ResourcesTable resources={resources} onSelectResource={mockOnSelectResource} />);

      await user.click(screen.getByLabelText("More options"));

      expect(screen.queryByText("Delete")).not.toBeInTheDocument();
    });
  });

  it("maintains selection state across re-renders", () => {
    const resources = [createMockResource(1), createMockResource(2)];
    const { rerender } = render(
      <ResourcesTable
        resources={resources}
        selectedResourceId="resource-1"
        onSelectResource={mockOnSelectResource}
      />,
    );

    let selectedRow = screen.getByText("Resource 1 Title").closest("tr");
    expect(selectedRow).toHaveAttribute("data-state", "selected");

    rerender(
      <ResourcesTable
        resources={resources}
        selectedResourceId="resource-1"
        onSelectResource={mockOnSelectResource}
      />,
    );

    selectedRow = screen.getByText("Resource 1 Title").closest("tr");
    expect(selectedRow).toHaveAttribute("data-state", "selected");
  });

  it("updates selection when selectedResourceId changes", () => {
    const resources = [createMockResource(1), createMockResource(2)];
    const { rerender } = render(
      <ResourcesTable
        resources={resources}
        selectedResourceId="resource-1"
        onSelectResource={mockOnSelectResource}
      />,
    );

    const selectedRow = screen.getByText("Resource 1 Title").closest("tr");
    expect(selectedRow).toHaveAttribute("data-state", "selected");

    rerender(
      <ResourcesTable
        resources={resources}
        selectedResourceId="resource-2"
        onSelectResource={mockOnSelectResource}
      />,
    );

    const previouslySelectedRow = screen.getByText("Resource 1 Title").closest("tr");
    expect(previouslySelectedRow).not.toHaveAttribute("data-state", "selected");

    const newSelectedRow = screen.getByText("Resource 2 Title").closest("tr");
    expect(newSelectedRow).toHaveAttribute("data-state", "selected");
  });

  it("handles null selectedResourceId", () => {
    const resources = [createMockResource(1), createMockResource(2)];
    render(
      <ResourcesTable
        resources={resources}
        selectedResourceId={null}
        onSelectResource={mockOnSelectResource}
      />,
    );

    const row1 = screen.getByText("Resource 1 Title").closest("tr");
    const row2 = screen.getByText("Resource 2 Title").closest("tr");

    expect(row1).not.toHaveAttribute("data-state", "selected");
    expect(row2).not.toHaveAttribute("data-state", "selected");
  });

  it("handles undefined selectedResourceId", () => {
    const resources = [createMockResource(1), createMockResource(2)];
    render(<ResourcesTable resources={resources} onSelectResource={mockOnSelectResource} />);

    const row1 = screen.getByText("Resource 1 Title").closest("tr");
    const row2 = screen.getByText("Resource 2 Title").closest("tr");

    expect(row1).not.toHaveAttribute("data-state", "selected");
    expect(row2).not.toHaveAttribute("data-state", "selected");
  });
});
