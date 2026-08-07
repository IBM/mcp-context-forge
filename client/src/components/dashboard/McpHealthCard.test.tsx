import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";

import { renderWithProviders } from "@/test/test-utils";
import { useSystemHealth, type VersionInfo } from "@/hooks/useSystemHealth";
import { useMcpServers, type UseMcpServersResult } from "@/hooks/useMcpServers";
import { useElementWidth } from "@/hooks/useElementWidth";
import { useAuth } from "@/auth/useAuth";
import type { MCPServer } from "@/types/server";
import { McpHealthCard } from "./McpHealthCard";

vi.mock("@/hooks/useSystemHealth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/useSystemHealth")>();
  return { ...actual, useSystemHealth: vi.fn() };
});
vi.mock("@/hooks/useMcpServers", () => ({ useMcpServers: vi.fn() }));
vi.mock("@/hooks/useElementWidth", () => ({ useElementWidth: vi.fn() }));
vi.mock("@/auth/useAuth", () => ({ useAuth: vi.fn() }));

const mockUseSystemHealth = vi.mocked(useSystemHealth);
const mockUseMcpServers = vi.mocked(useMcpServers);
const mockUseElementWidth = vi.mocked(useElementWidth);
const mockUseAuth = vi.mocked(useAuth);

/** Drive the roster's wide/narrow branch by faking the measured card width. */
function mockRosterWidth(width: number) {
  mockUseElementWidth.mockReturnValue([{ current: null }, width] as unknown as ReturnType<
    typeof useElementWidth
  >);
}

function makeServer(over: Partial<MCPServer> = {}): MCPServer {
  return {
    id: over.id ?? "s1",
    name: over.name ?? "server-1",
    enabled: over.enabled ?? true,
    visibility: "private",
    url: "https://example.test/mcp",
    transport: "STREAMABLEHTTP",
    reachable: over.reachable ?? true,
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:00Z",
    ...over,
  };
}

function mockServers(over: Partial<UseMcpServersResult>) {
  mockUseMcpServers.mockReturnValue({
    servers: over.servers,
    error: over.error ?? null,
    isLoading: over.isLoading ?? false,
    lastUpdated: over.lastUpdated ?? null,
  });
}

const healthyInfo: VersionInfo = {
  database: { dialect: "postgresql", reachable: true, server_version: "16" },
  redis: { available: true, reachable: true, server_version: "7" },
  settings: { cache_type: "redis" },
};

function mockHealth(data?: VersionInfo, over: { isLoading?: boolean; error?: unknown } = {}) {
  mockUseSystemHealth.mockReturnValue({
    data,
    error: over.error ?? null,
    isLoading: over.isLoading ?? false,
    execute: vi.fn(),
    refetch: vi.fn(),
    setData: vi.fn(),
  } as unknown as ReturnType<typeof useSystemHealth>);
}

describe("McpHealthCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Default: non-admin caller (no footer chips), no health payload.
    mockUseAuth.mockReturnValue({ hasPermission: () => false } as unknown as ReturnType<
      typeof useAuth
    >);
    mockHealth(undefined);
    // Default to the narrow (stacked list) shape; wide-branch tests opt in.
    mockRosterWidth(0);
  });

  it("shows the loading copy before the first load", () => {
    mockServers({ servers: undefined, isLoading: true });
    renderWithProviders(<McpHealthCard />);

    expect(screen.getByText("Checking server status…")).toBeInTheDocument();
  });

  it("renders PermissionDenied on a 403 from /gateways", () => {
    mockServers({ error: { message: "HTTP 403", status: 403 } });
    renderWithProviders(<McpHealthCard />);

    expect(screen.getByText("You do not have permission to view this.")).toBeInTheDocument();
  });

  it("renders a generic error on other failures", () => {
    mockServers({ error: { message: "HTTP 500", status: 500 } });
    renderWithProviders(<McpHealthCard />);

    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("keeps the last-known roster on a transient (non-403) refetch error", () => {
    // servers already loaded; a failed poll must not replace them with the error card.
    mockServers({
      servers: [makeServer({ id: "a", name: "alpha", reachable: true })],
      error: { message: "HTTP 500", status: 500 },
    });
    renderWithProviders(<McpHealthCard />);

    expect(screen.getByText("alpha")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows PermissionDenied on a 403 even when a roster was previously loaded", () => {
    // A lost permission is authoritative: do not keep showing data the caller
    // may no longer be entitled to.
    mockServers({
      servers: [makeServer({ id: "a", name: "alpha", reachable: true })],
      error: { message: "HTTP 403", status: 403 },
    });
    renderWithProviders(<McpHealthCard />);

    expect(screen.getByText("You do not have permission to view this.")).toBeInTheDocument();
    expect(screen.queryByText("alpha")).not.toBeInTheDocument();
  });

  it("shows the empty copy when the fleet is empty", () => {
    mockServers({ servers: [] });
    renderWithProviders(<McpHealthCard />);

    expect(screen.getByText("No MCP servers have been added yet")).toBeInTheDocument();
  });

  it("renders the roster header and a row per server", () => {
    mockServers({
      servers: [
        makeServer({ id: "a", name: "alpha", reachable: true, lastSeen: "2026-01-01T00:00:00Z" }),
        makeServer({ id: "b", name: "bravo", reachable: false, lastSeen: "2026-01-01T00:00:00Z" }),
      ],
    });
    renderWithProviders(<McpHealthCard />);

    // One reachable + one unreachable settled -> reduced coverage header.
    expect(screen.getByText("Reduced coverage")).toBeInTheDocument();
    expect(screen.getByText("alpha")).toBeInTheDocument();
    expect(screen.getByText("bravo")).toBeInTheDocument();
  });

  it("renders the narrow list (not a table) when the card is not wide", () => {
    mockRosterWidth(320);
    mockServers({ servers: [makeServer({ id: "a", name: "alpha", reachable: true })] });
    renderWithProviders(<McpHealthCard />);

    expect(screen.getByRole("list")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByText("alpha")).toBeInTheDocument();
  });

  it("renders an aligned table with column headers when the card is wide", () => {
    mockRosterWidth(900);
    mockServers({
      servers: [
        makeServer({ id: "a", name: "alpha", reachable: true, lastSeen: "2026-01-01T00:00:00Z" }),
      ],
    });
    renderWithProviders(<McpHealthCard />);

    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Server" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Last seen" })).toBeInTheDocument();
    expect(screen.getByText("alpha")).toBeInTheDocument();
  });

  it("shows 'Refreshed just now' at the moment of a successful poll (0 seconds ago)", () => {
    mockServers({ servers: [makeServer({ reachable: true })], lastUpdated: Date.now() });
    renderWithProviders(<McpHealthCard />);

    expect(screen.getByText("Refreshed just now")).toBeInTheDocument();
  });

  it("shows the relative seconds for a recent-but-not-instant refresh", () => {
    mockServers({
      servers: [makeServer({ reachable: true })],
      lastUpdated: Date.now() - 30_000,
    });
    renderWithProviders(<McpHealthCard />);

    expect(screen.getByText("Refreshed 30 seconds ago")).toBeInTheDocument();
    expect(screen.queryByText("Refreshed just now")).not.toBeInTheDocument();
  });

  it("shows the relative minutes when the last refresh is stale", () => {
    mockServers({
      servers: [makeServer({ reachable: true })],
      lastUpdated: Date.now() - 5 * 60_000,
    });
    renderWithProviders(<McpHealthCard />);

    expect(screen.getByText("Refreshed 5 minutes ago")).toBeInTheDocument();
    expect(screen.queryByText("Refreshed just now")).not.toBeInTheDocument();
  });

  it("omits the admin-only dependency chips for a non-admin caller", () => {
    mockServers({ servers: [makeServer({ reachable: true })] });
    mockHealth(healthyInfo); // even if health data were present, no admin => no chips
    renderWithProviders(<McpHealthCard />);

    expect(screen.queryByText("PostgreSQL")).not.toBeInTheDocument();
    expect(screen.queryByText("Redis")).not.toBeInTheDocument();
  });

  it("renders Postgres/Redis chips when the caller can view system config", () => {
    mockUseAuth.mockReturnValue({
      hasPermission: (perm: string) => perm === "admin.system_config",
    } as unknown as ReturnType<typeof useAuth>);
    mockServers({ servers: [makeServer({ reachable: true })] });
    mockHealth(healthyInfo);
    renderWithProviders(<McpHealthCard />);

    expect(screen.getByText("PostgreSQL")).toBeInTheDocument();
    expect(screen.getByText("Redis")).toBeInTheDocument();
  });

  it("shows a footer placeholder while /version is loading for an admin", () => {
    mockUseAuth.mockReturnValue({
      hasPermission: (perm: string) => perm === "admin.system_config",
    } as unknown as ReturnType<typeof useAuth>);
    mockServers({ servers: [makeServer({ reachable: true })] });
    mockHealth(undefined, { isLoading: true });
    const { container } = renderWithProviders(<McpHealthCard />);

    expect(container.querySelector('[data-slot="skeleton"]')).toBeInTheDocument();
    expect(screen.queryByText("PostgreSQL")).not.toBeInTheDocument();
  });

  it("shows no footer placeholder after a swallowed /version error", () => {
    mockUseAuth.mockReturnValue({
      hasPermission: (perm: string) => perm === "admin.system_config",
    } as unknown as ReturnType<typeof useAuth>);
    mockServers({ servers: [makeServer({ reachable: true })] });
    mockHealth(undefined, { error: { message: "HTTP 403", status: 403 } });
    const { container } = renderWithProviders(<McpHealthCard />);

    expect(container.querySelector('[data-slot="skeleton"]')).not.toBeInTheDocument();
    expect(screen.queryByText("PostgreSQL")).not.toBeInTheDocument();
  });

  it("reuses a passed-in /version result instead of polling again", () => {
    mockUseAuth.mockReturnValue({
      hasPermission: (perm: string) => perm === "admin.system_config",
    } as unknown as ReturnType<typeof useAuth>);
    mockServers({ servers: [makeServer({ reachable: true })] });
    // Own /version returns nothing; the shared prop supplies the health data.
    mockHealth(undefined);
    const shared = {
      data: healthyInfo,
      error: null,
      isLoading: false,
      execute: vi.fn(),
      refetch: vi.fn(),
      setData: vi.fn(),
    } as unknown as ReturnType<typeof useSystemHealth>;
    renderWithProviders(<McpHealthCard health={shared} />);

    // Footer chips render from the shared result...
    expect(screen.getByText("PostgreSQL")).toBeInTheDocument();
    expect(screen.getByText("Redis")).toBeInTheDocument();
    // ...and the card's own /version poll is disabled (enabled=false).
    expect(mockUseSystemHealth).toHaveBeenCalledWith(undefined, false);
  });
});
