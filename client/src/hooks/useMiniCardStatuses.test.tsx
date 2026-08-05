import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook } from "@testing-library/react";

import { useAuth } from "@/auth/useAuth";
import { useQuery } from "@/hooks/useQuery";
import { useRecentActivity } from "@/hooks/useRecentActivity";
import { useSystemHealth, type VersionInfo } from "@/hooks/useSystemHealth";

import { useMiniCardStatuses } from "./useMiniCardStatuses";

vi.mock("@/auth/useAuth", () => ({ useAuth: vi.fn() }));
// Preserve deriveMcpHealthy (used by the hook) while stubbing useSystemHealth.
vi.mock("@/hooks/useSystemHealth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/useSystemHealth")>();
  return { ...actual, useSystemHealth: vi.fn() };
});
vi.mock("@/hooks/useQuery", () => ({ useQuery: vi.fn() }));
vi.mock("@/hooks/useRecentActivity", () => ({ useRecentActivity: vi.fn() }));

const mockUseAuth = vi.mocked(useAuth);
const mockUseSystemHealth = vi.mocked(useSystemHealth);
const mockUseQuery = vi.mocked(useQuery);
const mockUseRecentActivity = vi.mocked(useRecentActivity);

const healthyInfo: VersionInfo = {
  database: { dialect: "postgresql", reachable: true, server_version: "16" },
  redis: { available: true, reachable: true, server_version: "7" },
  settings: { cache_type: "redis" },
};

function health(over: { data?: VersionInfo; error?: { message: string; status?: number } | null }) {
  return {
    data: over.data,
    error: over.error ?? null,
    isLoading: false,
    execute: vi.fn(),
    refetch: vi.fn(),
    setData: vi.fn(),
  } as unknown as ReturnType<typeof useSystemHealth>;
}

function admin(isAdmin = true) {
  mockUseAuth.mockReturnValue({
    hasPermission: (perm: string) => isAdmin && perm === "admin.system_config",
  } as unknown as ReturnType<typeof useAuth>);
}

beforeEach(() => {
  vi.clearAllMocks();
  admin(true);
  mockUseSystemHealth.mockReturnValue(health({ data: undefined }));
  mockUseQuery.mockReturnValue({
    data: undefined,
    error: null,
    isLoading: false,
    execute: vi.fn(),
    refetch: vi.fn(),
    setData: vi.fn(),
  } as unknown as ReturnType<typeof useQuery>);
  mockUseRecentActivity.mockReturnValue({
    items: [],
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  });
});

describe("useMiniCardStatuses — /version gating", () => {
  it("does not fetch /version for a non-admin caller", () => {
    admin(false);
    renderHook(() => useMiniCardStatuses());
    // enabled=false -> useSystemHealth makes no request (guaranteed 403 avoided).
    expect(mockUseSystemHealth).toHaveBeenCalledWith(undefined, false);
  });

  it("fetches /version for a caller who can view system config", () => {
    admin(true);
    renderHook(() => useMiniCardStatuses());
    expect(mockUseSystemHealth).toHaveBeenCalledWith(undefined, true);
  });
});

describe("useMiniCardStatuses — headline health axis", () => {
  it("stays optimistic (reachable undefined) while health is loading / for a non-admin", () => {
    admin(false); // no /version -> no data, no error
    const { result } = renderHook(() => useMiniCardStatuses());
    expect(result.current.headlineCondition.reachable).toBeUndefined();
  });

  it("treats a 403 as unknown, not unreachable (permission, not downtime)", () => {
    mockUseSystemHealth.mockReturnValue(health({ error: { message: "HTTP 403", status: 403 } }));
    const { result } = renderHook(() => useMiniCardStatuses());
    expect(result.current.headlineCondition.reachable).toBeUndefined();
  });

  it("reports unreachable on a definitive (non-403) error with no data", () => {
    mockUseSystemHealth.mockReturnValue(health({ error: { message: "HTTP 500", status: 500 } }));
    const { result } = renderHook(() => useMiniCardStatuses());
    expect(result.current.headlineCondition.reachable).toBe(false);
  });

  it("keeps reachable=true on a transient refetch error when last-known data is present", () => {
    // useQuery preserves data across a failed refetch; the headline must not flap.
    mockUseSystemHealth.mockReturnValue(
      health({ data: healthyInfo, error: { message: "HTTP 500", status: 500 } }),
    );
    const { result } = renderHook(() => useMiniCardStatuses());
    expect(result.current.headlineCondition.reachable).toBe(true);
    expect(result.current.headlineCondition.dependenciesHealthy).toBe(true);
  });
});
