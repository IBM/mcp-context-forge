import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";

import { renderWithProviders } from "@/test/test-utils";
import { useSystemHealth, type VersionInfo } from "@/hooks/useSystemHealth";
import { useMcpServers, type UseMcpServersResult } from "@/hooks/useMcpServers";
import { useAuth } from "@/auth/useAuth";
import type { MCPServer } from "@/types/server";
import { McpHealthCard } from "./McpHealthCard";

vi.mock("@/hooks/useSystemHealth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/useSystemHealth")>();
  return { ...actual, useSystemHealth: vi.fn() };
});
vi.mock("@/hooks/useMcpServers", () => ({ useMcpServers: vi.fn() }));
vi.mock("@/auth/useAuth", () => ({ useAuth: vi.fn() }));

const mockUseSystemHealth = vi.mocked(useSystemHealth);
const mockUseMcpServers = vi.mocked(useMcpServers);
const mockUseAuth = vi.mocked(useAuth);

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
});
