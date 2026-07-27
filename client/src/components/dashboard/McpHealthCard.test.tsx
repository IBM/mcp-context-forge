import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";

import { renderWithProviders } from "@/test/test-utils";
import { useSystemHealth, type VersionInfo } from "@/hooks/useSystemHealth";
import { McpHealthCard } from "./McpHealthCard";

vi.mock("@/hooks/useSystemHealth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/useSystemHealth")>();
  return { ...actual, useSystemHealth: vi.fn() };
});

const mockUseSystemHealth = vi.mocked(useSystemHealth);

function makeResult(over: {
  data?: VersionInfo;
  error?: { message: string; status?: number } | null;
  isLoading?: boolean;
}) {
  return {
    data: over.data,
    error: over.error ?? null,
    isLoading: over.isLoading ?? false,
    execute: vi.fn(),
    refetch: vi.fn(),
    setData: vi.fn(),
  } as unknown as ReturnType<typeof useSystemHealth>;
}

const healthyInfo: VersionInfo = {
  database: { dialect: "postgresql", reachable: true, server_version: "16" },
  redis: { available: true, reachable: true, server_version: "7" },
  settings: { cache_type: "redis" },
};

describe("McpHealthCard", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows Healthy with Postgres and Redis chips when reachable", () => {
    mockUseSystemHealth.mockReturnValue(makeResult({ data: healthyInfo }));
    renderWithProviders(<McpHealthCard />);

    expect(screen.getByText("Healthy")).toBeInTheDocument();
    expect(screen.getByText("PostgreSQL")).toBeInTheDocument();
    expect(screen.getByText("Redis")).toBeInTheDocument();
  });

  it("shows Unhealthy when the database is unreachable", () => {
    mockUseSystemHealth.mockReturnValue(
      makeResult({
        data: { ...healthyInfo, database: { ...healthyInfo.database, reachable: false } },
      }),
    );
    renderWithProviders(<McpHealthCard />);

    expect(screen.getByText("Unhealthy")).toBeInTheDocument();
  });

  it("marks Redis Not configured when it is not the cache backend", () => {
    mockUseSystemHealth.mockReturnValue(
      makeResult({
        data: {
          ...healthyInfo,
          // Library installed (available) but Redis is NOT the backend and not
          // reachable -- the real default config. Must read Not configured, not red.
          redis: { available: true, reachable: false, server_version: null },
          settings: { cache_type: "database" },
        },
      }),
    );
    renderWithProviders(<McpHealthCard />);

    // Redis absent is not a health failure when it is not the configured cache.
    expect(screen.getByText("Healthy")).toBeInTheDocument();
    expect(screen.getByText(/Not configured/)).toBeInTheDocument();
  });

  it("renders PermissionDenied on a 403", () => {
    mockUseSystemHealth.mockReturnValue(
      makeResult({ error: { message: "HTTP 403", status: 403 } }),
    );
    renderWithProviders(<McpHealthCard />);

    expect(screen.getByText("You do not have permission to view this.")).toBeInTheDocument();
  });

  it("renders a generic error on other failures", () => {
    mockUseSystemHealth.mockReturnValue(
      makeResult({ error: { message: "HTTP 500", status: 500 } }),
    );
    renderWithProviders(<McpHealthCard />);

    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't load system health.");
  });
});
