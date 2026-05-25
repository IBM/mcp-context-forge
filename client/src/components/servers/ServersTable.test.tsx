import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ServersTable } from "./ServersTable";
import { I18nProvider } from "@/i18n";
import type { MCPServer } from "../../types/server";
import type { ReactElement } from "react";

function renderTable(ui: ReactElement) {
  return render(<I18nProvider>{ui}</I18nProvider>);
}

// Minimal server factory
function makeServer(overrides: Partial<MCPServer> = {}): MCPServer {
  return {
    id: "server-uuid-1",
    name: "Test Server",
    url: "http://localhost:9000",
    transport: "SSE",
    enabled: true,
    reachable: true,
    visibility: "public",
    tool_count: 0,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    ...overrides,
  };
}

const noop = vi.fn();

describe("ServersTable", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Loading state ────────────────────────────────────────────────────────────

  it("renders a loading indicator when isLoading is true", () => {
    renderTable(
      <ServersTable servers={[]} isLoading onEdit={noop} onDelete={noop} onTest={noop} />,
    );
    // The Loading component should be present; the table must not
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  // ── Column headers ──────────────────────────────────────────────────────────

  it("renders all expected column headers", () => {
    renderTable(
      <ServersTable
        servers={[makeServer()]}
        isLoading={false}
        onEdit={noop}
        onDelete={noop}
        onTest={noop}
      />,
    );
    expect(screen.getByText("Name")).toBeInTheDocument();
    expect(screen.getByText("Components")).toBeInTheDocument();
    expect(screen.getByText("Last response")).toBeInTheDocument();
    expect(screen.getByText("UUID")).toBeInTheDocument();
    expect(screen.getByText("Visibility")).toBeInTheDocument();
    expect(screen.getByText("Status")).toBeInTheDocument();
    expect(screen.getByText("Actions")).toBeInTheDocument();
  });

  // ── Components cell ─────────────────────────────────────────────────────────

  it("shows tool_count when toolCount is absent", () => {
    renderTable(
      <ServersTable
        servers={[makeServer({ tool_count: 7 })]}
        isLoading={false}
        onEdit={noop}
        onDelete={noop}
        onTest={noop}
      />,
    );
    expect(screen.getByText("7 tools")).toBeInTheDocument();
  });

  it("prefers toolCount over tool_count", () => {
    renderTable(
      <ServersTable
        servers={[makeServer({ tool_count: 1, toolCount: 9 })]}
        isLoading={false}
        onEdit={noop}
        onDelete={noop}
        onTest={noop}
      />,
    );
    expect(screen.getByText("9 tools")).toBeInTheDocument();
    expect(screen.queryByText("1 tools")).not.toBeInTheDocument();
  });

  it("shows 0 tools when no count is provided", () => {
    renderTable(
      <ServersTable
        servers={[makeServer({ tool_count: 0 })]}
        isLoading={false}
        onEdit={noop}
        onDelete={noop}
        onTest={noop}
      />,
    );
    expect(screen.getByText("0 tools")).toBeInTheDocument();
  });

  it("shows capability counts from capabilities.resources and capabilities.prompts using count field", () => {
    const server = makeServer({
      capabilities: {
        resources: { count: 3 },
        prompts: { count: 2 },
      },
    });
    renderTable(
      <ServersTable
        servers={[server]}
        isLoading={false}
        onEdit={noop}
        onDelete={noop}
        onTest={noop}
      />,
    );
    expect(screen.getByText("3 resources")).toBeInTheDocument();
    expect(screen.getByText("2 prompts")).toBeInTheDocument();
  });

  it("falls back to key count for capabilities without a count field (backward compat)", () => {
    const server = makeServer({
      capabilities: {
        resources: { resource_a: {}, resource_b: {} },
        prompts: { prompt_a: {} },
      },
    });
    renderTable(
      <ServersTable
        servers={[server]}
        isLoading={false}
        onEdit={noop}
        onDelete={noop}
        onTest={noop}
      />,
    );
    expect(screen.getByText("2 resources")).toBeInTheDocument();
    expect(screen.getByText("1 prompts")).toBeInTheDocument();
  });

  it("shows 0 resources and 0 prompts when capabilities is undefined", () => {
    renderTable(
      <ServersTable
        servers={[makeServer({ capabilities: undefined })]}
        isLoading={false}
        onEdit={noop}
        onDelete={noop}
        onTest={noop}
      />,
    );
    expect(screen.getByText("0 resources")).toBeInTheDocument();
    expect(screen.getByText("0 prompts")).toBeInTheDocument();
  });

  // ── Last seen cell ──────────────────────────────────────────────────────────

  it("shows 'Never used' when last_seen and lastSeen are both absent", () => {
    renderTable(
      <ServersTable
        servers={[makeServer({ last_seen: undefined, lastSeen: undefined })]}
        isLoading={false}
        onEdit={noop}
        onDelete={noop}
        onTest={noop}
      />,
    );
    expect(screen.getByText("Never used")).toBeInTheDocument();
  });

  it("shows 'Never used' for an invalid date string", () => {
    renderTable(
      <ServersTable
        servers={[makeServer({ last_seen: "not-a-date" })]}
        isLoading={false}
        onEdit={noop}
        onDelete={noop}
        onTest={noop}
      />,
    );
    expect(screen.getByText("Never used")).toBeInTheDocument();
  });

  it("formats a valid last_seen date in ISO-like sv-SE format", () => {
    const server = makeServer({ last_seen: "2024-06-15T14:05:30Z" });
    renderTable(
      <ServersTable
        servers={[server]}
        isLoading={false}
        onEdit={noop}
        onDelete={noop}
        onTest={noop}
      />,
    );
    // sv-SE locale produces "YYYY-MM-DD HH:MM:SS" which is then converted to "YYYY-MM-DDTHH:MM:SS"
    expect(screen.getByText(/2024-06-15T/)).toBeInTheDocument();
  });

  it("prefers lastSeen over last_seen", () => {
    const server = makeServer({
      last_seen: "2023-01-01T00:00:00Z",
      lastSeen: "2025-03-20T08:00:00Z",
    });
    renderTable(
      <ServersTable
        servers={[server]}
        isLoading={false}
        onEdit={noop}
        onDelete={noop}
        onTest={noop}
      />,
    );
    expect(screen.getByText(/2025-03-20T/)).toBeInTheDocument();
    expect(screen.queryByText(/2023-01-01T/)).not.toBeInTheDocument();
  });

  // ── UUID copy cell ──────────────────────────────────────────────────────────

  it("renders the server UUID in the UUID cell", () => {
    const server = makeServer({ id: "abc-123-xyz" });
    renderTable(
      <ServersTable
        servers={[server]}
        isLoading={false}
        onEdit={noop}
        onDelete={noop}
        onTest={noop}
      />,
    );
    expect(screen.getByText("abc-123-xyz")).toBeInTheDocument();
  });

  it("copies UUID to clipboard on button click", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      writable: true,
      configurable: true,
    });

    const server = makeServer({ id: "copy-me-uuid" });
    renderTable(
      <ServersTable
        servers={[server]}
        isLoading={false}
        onEdit={noop}
        onDelete={noop}
        onTest={noop}
      />,
    );

    const copyBtn = screen.getByRole("button", { name: /copy uuid for test server/i });
    await user.click(copyBtn);

    expect(writeText).toHaveBeenCalledWith("copy-me-uuid");
  });

  // ── Visibility cell ─────────────────────────────────────────────────────────

  it.each([
    ["public" as const, "Public"],
    ["team" as const, "Team"],
    ["private" as const, "Private"],
  ])("shows '%s' visibility label for visibility='%s'", (visibility, label) => {
    renderTable(
      <ServersTable
        servers={[makeServer({ visibility })]}
        isLoading={false}
        onEdit={noop}
        onDelete={noop}
        onTest={noop}
      />,
    );
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  // ── Status cell ─────────────────────────────────────────────────────────────

  it("shows 'Draft' when server is disabled", () => {
    renderTable(
      <ServersTable
        servers={[makeServer({ enabled: false })]}
        isLoading={false}
        onEdit={noop}
        onDelete={noop}
        onTest={noop}
      />,
    );
    expect(screen.getByText("Draft")).toBeInTheDocument();
  });

  it("shows 'Offline' when enabled, not reachable, and never seen", () => {
    renderTable(
      <ServersTable
        servers={[
          makeServer({
            enabled: true,
            reachable: false,
            last_seen: undefined,
            lastSeen: undefined,
          }),
        ]}
        isLoading={false}
        onEdit={noop}
        onDelete={noop}
        onTest={noop}
      />,
    );
    expect(screen.getByText("Offline")).toBeInTheDocument();
  });

  it("shows 'Warning' when enabled, not reachable, but was seen before", () => {
    renderTable(
      <ServersTable
        servers={[
          makeServer({ enabled: true, reachable: false, lastSeen: "2024-01-01T00:00:00Z" }),
        ]}
        isLoading={false}
        onEdit={noop}
        onDelete={noop}
        onTest={noop}
      />,
    );
    expect(screen.getByText("Warning")).toBeInTheDocument();
  });

  it("shows 'Active' when enabled and reachable", () => {
    renderTable(
      <ServersTable
        servers={[makeServer({ enabled: true, reachable: true })]}
        isLoading={false}
        onEdit={noop}
        onDelete={noop}
        onTest={noop}
      />,
    );
    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  // ── Multiple rows ───────────────────────────────────────────────────────────

  it("renders one row per server", () => {
    const servers = [
      makeServer({ id: "s1", name: "Alpha" }),
      makeServer({ id: "s2", name: "Beta" }),
      makeServer({ id: "s3", name: "Gamma" }),
    ];
    renderTable(
      <ServersTable
        servers={servers}
        isLoading={false}
        onEdit={noop}
        onDelete={noop}
        onTest={noop}
      />,
    );
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("Beta")).toBeInTheDocument();
    expect(screen.getByText("Gamma")).toBeInTheDocument();
  });
});
