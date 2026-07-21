import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server as mswServer } from "@/test/mocks/server";
import { renderWithProviders as render } from "@/test/test-utils";
import { VirtualServerDetailsPanel } from "./VirtualServerDetailsPanel";
import type { VirtualServer } from "@/types/server";
import { copyToClipboard } from "@/lib/clipboard";

vi.mock("@/lib/clipboard", () => ({ copyToClipboard: vi.fn() }));

function makeServer(overrides: Partial<VirtualServer> = {}): VirtualServer {
  return {
    id: "gateway-1",
    name: "GH repo tasks",
    description: "Test server",
    icon: "",
    createdAt: "2026-04-16T13:23:12Z",
    updatedAt: "2026-04-16T13:23:12Z",
    enabled: true,
    associatedTools: [],
    associatedToolIds: [],
    associatedResources: [],
    associatedPrompts: [],
    associatedA2aAgents: [],
    metrics: null,
    tags: [],
    createdBy: "admin@example.com",
    createdFromIp: "127.0.0.1",
    createdVia: "ui",
    createdUserAgent: "Mozilla/5.0",
    modifiedBy: null,
    modifiedFromIp: null,
    modifiedVia: null,
    modifiedUserAgent: null,
    importBatchId: null,
    federationSource: null,
    version: 1,
    teamId: "team-1",
    team: "Test Team",
    ownerEmail: "admin@example.com",
    visibility: "team",
    oauthEnabled: false,
    oauthConfig: null,
    ...overrides,
  };
}

describe("VirtualServerDetailsPanel inline tag add", () => {
  it("calls onAddTag with the merged, de-duplicated tag list", async () => {
    const user = userEvent.setup();
    const onAddTag = vi.fn().mockResolvedValue(undefined);

    render(
      <VirtualServerDetailsPanel
        server={makeServer({ id: "gw-1", tags: ["prod"] })}
        error={null}
        open
        onClose={vi.fn()}
        onAddSources={vi.fn()}
        onAddTag={onAddTag}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Add tags" }));
    await user.type(screen.getByPlaceholderText("Add tags separated with commas"), "staging, prod");
    await user.click(screen.getByRole("button", { name: "Add" }));

    // "prod" already exists and is dropped; "staging" is appended.
    expect(onAddTag).toHaveBeenCalledWith("gw-1", ["prod", "staging"]);
  });

  it("disables the add-tag trigger when onAddTag is omitted", () => {
    render(
      <VirtualServerDetailsPanel
        server={makeServer({ tags: [] })}
        error={null}
        open
        onClose={vi.fn()}
        onAddSources={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Add tags" })).toBeDisabled();
  });
});

describe("VirtualServerDetailsPanel components list", () => {
  beforeEach(() => {
    // The panel fetches tools/resources/prompts when open; return empty so it
    // falls back to the server's associated* arrays for rendering.
    mswServer.use(
      http.get("*/servers/:id/tools", () => HttpResponse.json({ tools: [] })),
      http.get("*/servers/:id/resources", () => HttpResponse.json({ resources: [] })),
      http.get("*/servers/:id/prompts", () => HttpResponse.json({ prompts: [] })),
    );
    vi.mocked(copyToClipboard).mockClear();
  });

  function renderWithComponents() {
    return render(
      <VirtualServerDetailsPanel
        server={makeServer({
          id: "gw-components",
          // index 0: id differs from name -> gets a title; index 1: id equals name -> no title.
          associatedTools: ["Titled Tool", "Plain Tool"],
          associatedToolIds: ["titled-tool-id", "Plain Tool"],
          associatedResources: ["res://example/thing"],
          associatedPrompts: ["greeting-prompt"],
        })}
        error={null}
        open
        onClose={vi.fn()}
        onAddSources={vi.fn()}
      />,
    );
  }

  it("renders titled and untitled component rows with badges", async () => {
    renderWithComponents();

    // Titled tool row shows the display title and the id as the identifier.
    expect(await screen.findByText("Titled Tool")).toBeInTheDocument();
    expect(screen.getByText("titled-tool-id")).toBeInTheDocument();
    // Untitled rows render the identifier directly.
    expect(screen.getByText("Plain Tool")).toBeInTheDocument();
    expect(screen.getByText("res://example/thing")).toBeInTheDocument();
    expect(screen.getByText("greeting-prompt")).toBeInTheDocument();

    // Type badges for each component kind.
    expect(screen.getAllByText("tool")).toHaveLength(2);
    expect(screen.getByText("resource")).toBeInTheDocument();
    expect(screen.getByText("prompt")).toBeInTheDocument();
  });

  it("copies the identifier when a row's copy button is clicked", async () => {
    const user = userEvent.setup();
    renderWithComponents();

    await screen.findByText("Titled Tool");

    await user.click(screen.getByRole("button", { name: "Copy Titled Tool" }));
    expect(copyToClipboard).toHaveBeenCalledWith("titled-tool-id");

    await user.click(screen.getByRole("button", { name: "Copy Plain Tool" }));
    expect(copyToClipboard).toHaveBeenCalledWith("Plain Tool");
  });

  it("filters visible components with the search box", async () => {
    const user = userEvent.setup();
    renderWithComponents();

    await screen.findByText("Titled Tool");

    // Focus via the search affordance, then type a query.
    await user.click(screen.getByRole("button", { name: "Search components" }));
    const searchBox = screen.getByRole("searchbox");
    await user.type(searchBox, "Titled");

    await waitFor(() => {
      expect(screen.queryByText("Plain Tool")).not.toBeInTheDocument();
    });
    expect(screen.getByText("Titled Tool")).toBeInTheDocument();

    // Blur keeps the box expanded while a query is present.
    await user.tab();
    expect(searchBox).toHaveValue("Titled");
  });

  it("renders source tabs and filters components by source", async () => {
    const user = userEvent.setup();
    // Fetched components carry a gateway_id, which drives the source tabs.
    mswServer.use(
      http.get("*/servers/:id/tools", () =>
        HttpResponse.json({
          tools: [
            { id: "t1", name: "Tool One", originalName: "tool_one", gateway_id: "gwA" },
            { id: "t2", name: "Tool Two", originalName: "tool_two", gateway_id: "gwB" },
          ],
        }),
      ),
      http.get("*/gateways", () =>
        HttpResponse.json({
          gateways: [
            { id: "gwA", name: "Gateway A" },
            { id: "gwB", name: "Gateway B" },
          ],
        }),
      ),
    );

    render(
      <VirtualServerDetailsPanel
        server={makeServer({ id: "gw-sources" })}
        error={null}
        open
        onClose={vi.fn()}
        onAddSources={vi.fn()}
      />,
    );

    // Source tabs resolve from the gateways response.
    expect(await screen.findByRole("tab", { name: "Gateway A" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Gateway B" })).toBeInTheDocument();
    expect(screen.getByText("tool_one")).toBeInTheDocument();
    expect(screen.getByText("tool_two")).toBeInTheDocument();

    // Selecting a source filters the component list to that gateway.
    await user.click(screen.getByRole("tab", { name: "Gateway A" }));
    await waitFor(() => {
      expect(screen.queryByText("tool_two")).not.toBeInTheDocument();
    });
    expect(screen.getByText("tool_one")).toBeInTheDocument();

    // Arrow keys move focus across the source tablist.
    const allSources = screen.getByRole("tab", { name: "All sources" });
    allSources.focus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Gateway A" })).toHaveFocus();
  });

  it("moves the active tab with arrow keys", async () => {
    const user = userEvent.setup();
    renderWithComponents();

    await screen.findByText("Titled Tool");

    const allTab = screen.getByRole("tab", { name: "All" });
    expect(allTab).toHaveAttribute("aria-selected", "true");

    allTab.focus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Tools" })).toHaveAttribute("aria-selected", "true");

    await user.keyboard("{ArrowLeft}");
    expect(screen.getByRole("tab", { name: "All" })).toHaveAttribute("aria-selected", "true");

    // ArrowLeft from the first tab wraps around to the last.
    await user.keyboard("{ArrowLeft}");
    expect(screen.getByRole("tab", { name: "Prompts" })).toHaveAttribute("aria-selected", "true");

    // Clicking a tab selects it directly.
    await user.click(screen.getByRole("tab", { name: "Resources" }));
    expect(screen.getByRole("tab", { name: "Resources" })).toHaveAttribute("aria-selected", "true");
  });
});

describe("VirtualServerDetailsPanel render variants", () => {
  beforeEach(() => {
    mswServer.use(
      http.get("*/servers/:id/tools", () => HttpResponse.json({ tools: [] })),
      http.get("*/servers/:id/resources", () => HttpResponse.json({ resources: [] })),
      http.get("*/servers/:id/prompts", () => HttpResponse.json({ prompts: [] })),
    );
  });

  it("shows the public visibility label", async () => {
    render(
      <VirtualServerDetailsPanel
        server={makeServer({ visibility: "public" })}
        error={null}
        open
        onClose={vi.fn()}
        onAddSources={vi.fn()}
      />,
    );
    expect(await screen.findByText("Public")).toBeInTheDocument();
  });

  it("shows the private visibility label", async () => {
    render(
      <VirtualServerDetailsPanel
        server={makeServer({ visibility: "private" })}
        error={null}
        open
        onClose={vi.fn()}
        onAddSources={vi.fn()}
      />,
    );
    expect(await screen.findByText("Private")).toBeInTheDocument();
  });

  it("shows a placeholder when the server has no description", async () => {
    render(
      <VirtualServerDetailsPanel
        server={makeServer({ description: "" })}
        error={null}
        open
        onClose={vi.fn()}
        onAddSources={vi.fn()}
      />,
    );
    expect(await screen.findByText("No description provided.")).toBeInTheDocument();
  });

  it("shows N/A when the server has no version", async () => {
    render(
      <VirtualServerDetailsPanel
        server={makeServer({ version: undefined })}
        error={null}
        open
        onClose={vi.fn()}
        onAddSources={vi.fn()}
      />,
    );
    expect(await screen.findByText("N/A")).toBeInTheDocument();
  });

  it("shows the inactive status for a disabled server", async () => {
    render(
      <VirtualServerDetailsPanel
        server={makeServer({ enabled: false })}
        error={null}
        open
        onClose={vi.fn()}
        onAddSources={vi.fn()}
      />,
    );
    expect(await screen.findByText("Inactive")).toBeInTheDocument();
  });

  it("shows an empty state when the server has no components", async () => {
    render(
      <VirtualServerDetailsPanel
        server={makeServer({ id: "empty-server" })}
        error={null}
        open
        onClose={vi.fn()}
        onAddSources={vi.fn()}
      />,
    );
    expect(await screen.findByText(/No components found/i)).toBeInTheDocument();
  });

  it("closes when Escape is pressed", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <VirtualServerDetailsPanel
        server={makeServer()}
        error={null}
        open
        onClose={onClose}
        onAddSources={vi.fn()}
      />,
    );
    await screen.findByRole("tab", { name: "All" });

    await user.keyboard("{Escape}");

    expect(onClose).toHaveBeenCalled();
  });

  it("handles component responses returned as bare arrays", async () => {
    mswServer.use(
      http.get("*/servers/:id/tools", () =>
        HttpResponse.json([{ id: "t1", name: "arr_tool", originalName: "arr_tool" }]),
      ),
      http.get("*/servers/:id/resources", () => HttpResponse.json([])),
      http.get("*/servers/:id/prompts", () => HttpResponse.json([])),
    );
    render(
      <VirtualServerDetailsPanel
        server={makeServer({ id: "arr-server" })}
        error={null}
        open
        onClose={vi.fn()}
        onAddSources={vi.fn()}
      />,
    );

    expect(await screen.findByText("arr_tool")).toBeInTheDocument();
  });

  it("ignores non-arrow keys on the component tabs", async () => {
    const user = userEvent.setup();
    render(
      <VirtualServerDetailsPanel
        server={makeServer()}
        error={null}
        open
        onClose={vi.fn()}
        onAddSources={vi.fn()}
      />,
    );
    const allTab = await screen.findByRole("tab", { name: "All" });
    allTab.focus();
    await user.keyboard("{Enter}");
    // A non-navigation key leaves the active tab unchanged.
    expect(allTab).toHaveAttribute("aria-selected", "true");
  });
});
