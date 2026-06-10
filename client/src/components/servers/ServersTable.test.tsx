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
    createdAt: "2024-01-01T00:00:00Z",
    updatedAt: "2024-01-01T00:00:00Z",
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
  it("renders loading state", () => {
    renderWithProviders(<ServersTable servers={[]} isLoading={true} {...mockHandlers} />);
    expect(screen.getAllByRole("status")[0]).toBeInTheDocument();
  });

  it("renders table with servers", () => {
    renderWithProviders(
      <ServersTable servers={[mockServer]} isLoading={false} {...mockHandlers} />,
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
  it("renders table headers", () => {
    renderWithProviders(<ServersTable servers={[]} isLoading={false} {...mockHandlers} />);
    expect(screen.getByText("Name")).toBeInTheDocument();
    expect(screen.getByText("Components")).toBeInTheDocument();
    expect(screen.getByText("Last response")).toBeInTheDocument();
    expect(screen.getByText("UUID")).toBeInTheDocument();
    expect(screen.getByText("Visibility")).toBeInTheDocument();
    expect(screen.getByText("Status")).toBeInTheDocument();
    expect(screen.getByText("Actions")).toBeInTheDocument();
  });

  // ── Components cell ─────────────────────────────────────────────────────────

  it("shows toolCount from server data", () => {
    renderTable(
      <ServersTable
        servers={[makeServer({ toolCount: 7 })]}
        isLoading={false}
        onEdit={noop}
        onDelete={noop}
        onTest={noop}
      />,
    );
    expect(screen.getByText("7 tools")).toBeInTheDocument();
  });

  it("shows 0 tools when toolCount is absent", () => {
    renderTable(
      <ServersTable
        servers={[makeServer({})]}
        isLoading={false}
        onEdit={noop}
        onDelete={noop}
        onTest={noop}
      />,
  it("renders empty table without servers", () => {
    renderWithProviders(<ServersTable servers={[]} isLoading={false} {...mockHandlers} />);
    expect(document.body).toBeTruthy();
  });

  it("shows Just now for recent last_seen", () => {
    const recentServer = {
      ...mockServer,
      last_seen: new Date(Date.now() - 10000).toISOString(),
    };
    renderWithProviders(
      <ServersTable servers={[recentServer]} isLoading={false} {...mockHandlers} />,
    );
    expect(screen.getByText("0 tools")).toBeInTheDocument();
  });

  it("shows resourceCount and promptCount", () => {
    const server = makeServer({
      resourceCount: 3,
      promptCount: 2,
    });
    renderTable(
      <ServersTable
        servers={[server]}
        isLoading={false}
        onEdit={noop}
        onDelete={noop}
        onTest={noop}
      />,
  it("shows min ago for last_seen within an hour", () => {
    const recentServer = {
      ...mockServer,
      last_seen: new Date(Date.now() - 5 * 60000).toISOString(),
    };
    renderWithProviders(
      <ServersTable servers={[recentServer]} isLoading={false} {...mockHandlers} />,
    );
    expect(screen.getByText("3 resources")).toBeInTheDocument();
    expect(screen.getByText("2 prompts")).toBeInTheDocument();
  });

  it("shows 0 resources and 0 prompts when count fields are absent", () => {
    renderTable(
      <ServersTable
        servers={[makeServer({})]}
        isLoading={false}
        onEdit={noop}
        onDelete={noop}
        onTest={noop}
      />,
  it("shows hours ago for last_seen within a day", () => {
    const recentServer = {
      ...mockServer,
      last_seen: new Date(Date.now() - 3 * 3600000).toISOString(),
    };
    renderWithProviders(
      <ServersTable servers={[recentServer]} isLoading={false} {...mockHandlers} />,
    );
    expect(screen.getByText("0 resources")).toBeInTheDocument();
    expect(screen.getByText("0 prompts")).toBeInTheDocument();
  });

  // ── Last seen cell ──────────────────────────────────────────────────────────

  it("shows 'Never used' when lastSeen is absent", () => {
    renderTable(
      <ServersTable
        servers={[makeServer({ lastSeen: undefined })]}
        isLoading={false}
        onEdit={noop}
        onDelete={noop}
        onTest={noop}
      />,
  it("shows 1 hour ago for last_seen exactly 1 hour ago", () => {
    const recentServer = {
      ...mockServer,
      last_seen: new Date(Date.now() - 65 * 60000).toISOString(),
    };
    renderWithProviders(
      <ServersTable servers={[recentServer]} isLoading={false} {...mockHandlers} />,
    );
    expect(screen.getByText("1 hour ago")).toBeInTheDocument();
  });

  it("shows local date string for last_seen older than 24 hours", () => {
    const oldDate = new Date("2026-01-01T10:00:00Z");
    const oldServer = {
      ...mockServer,
      last_seen: oldDate.toISOString(),
    };
    renderWithProviders(<ServersTable servers={[oldServer]} isLoading={false} {...mockHandlers} />);
    // Since local date formatting varies, we can just assert that it is rendered in the cell
    const expected = oldDate.toLocaleDateString("en-US", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
    expect(screen.getByText(expected)).toBeInTheDocument();
  });

  it("shows Never used when last_seen is undefined", () => {
    const recentServer = { ...mockServer, last_seen: undefined };
    renderWithProviders(
      <ServersTable servers={[recentServer]} isLoading={false} {...mockHandlers} />,
    );
    expect(screen.getByText("Never used")).toBeInTheDocument();
  });

  it("shows 'Never used' for an invalid date string", () => {
    renderTable(
      <ServersTable
        servers={[makeServer({ lastSeen: "not-a-date" })]}
        isLoading={false}
        onEdit={noop}
        onDelete={noop}
        onTest={noop}
      />,
  it("renders multiple servers", () => {
    const server2 = { ...mockServer, id: "2", name: "Server Two" };
    renderWithProviders(
      <ServersTable servers={[mockServer, server2]} isLoading={false} {...mockHandlers} />,
    );
    expect(screen.getByText("Never used")).toBeInTheDocument();
  });

  it("formats a valid lastSeen date in ISO-like sv-SE format", () => {
    const server = makeServer({ lastSeen: "2024-06-15T14:05:30Z" });
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

  // ── onViewDetails wiring ────────────────────────────────────────────────────

  it("shows View Details menu item when onViewDetails is provided", async () => {
    const user = userEvent.setup();
    renderTable(
      <ServersTable
        servers={[makeServer()]}
        isLoading={false}
        onEdit={noop}
        onDelete={noop}
        onTest={noop}
        onViewDetails={noop}
      />,
    );
    await user.click(screen.getByRole("button", { name: /actions for/i }));
    expect(await screen.findByRole("menuitem", { name: /view details/i })).toBeInTheDocument();
  });

  it("hides View Details menu item when onViewDetails is not provided", async () => {
    const user = userEvent.setup();
    renderTable(
      <ServersTable
        servers={[makeServer()]}
        isLoading={false}
        onEdit={noop}
        onDelete={noop}
        onTest={noop}
      />,
    );
    await user.click(screen.getByRole("button", { name: /actions for/i }));
    await screen.findByRole("menuitem", { name: /edit/i });
    expect(screen.queryByRole("menuitem", { name: /view details/i })).not.toBeInTheDocument();
  });

  it("calls onViewDetails with the server id when View Details is clicked", async () => {
    const user = userEvent.setup();
    const onViewDetails = vi.fn();
    renderTable(
      <ServersTable
        servers={[makeServer({ id: "srv-42" })]}
        isLoading={false}
        onEdit={noop}
        onDelete={noop}
        onTest={noop}
        onViewDetails={onViewDetails}
      />,
    );
    await user.click(screen.getByRole("button", { name: /actions for/i }));
    await user.click(await screen.findByRole("menuitem", { name: /view details/i }));
    expect(onViewDetails).toHaveBeenCalledWith("srv-42");
    expect(onViewDetails).toHaveBeenCalledTimes(1);
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


