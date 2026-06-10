import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { useUsersList } from "./useUsersList";

vi.mock("@/hooks/useQuery", () => ({
  useQuery: vi.fn(() => ({
    data: undefined,
    error: null,
    isLoading: false,
    execute: vi.fn(),
    refetch: vi.fn(),
  })),
}));

import { useQuery } from "@/hooks/useQuery";

describe("useUsersList", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("default params → include_pagination=true only", () => {
    renderHook(() => useUsersList());
    expect(vi.mocked(useQuery)).toHaveBeenCalledWith(
      "/auth/email/admin/users?include_pagination=true",
      expect.objectContaining({ enabled: true, immediate: true }),
    );
  });

  it("cursor param appended", () => {
    renderHook(() => useUsersList({ cursor: "test-cursor" }));
    expect(vi.mocked(useQuery)).toHaveBeenCalledWith(
      "/auth/email/admin/users?cursor=test-cursor&include_pagination=true",
      expect.anything(),
    );
  });

  it("limit param appended", () => {
    renderHook(() => useUsersList({ limit: 50 }));
    expect(vi.mocked(useQuery)).toHaveBeenCalledWith(
      "/auth/email/admin/users?limit=50&include_pagination=true",
      expect.anything(),
    );
  });

  it("limit clamped to max 100", () => {
    renderHook(() => useUsersList({ limit: 200 }));
    expect(vi.mocked(useQuery)).toHaveBeenCalledWith(
      "/auth/email/admin/users?limit=100&include_pagination=true",
      expect.anything(),
    );
  });

  it("limit clamped to min 1", () => {
    renderHook(() => useUsersList({ limit: 0 }));
    expect(vi.mocked(useQuery)).toHaveBeenCalledWith(
      "/auth/email/admin/users?limit=1&include_pagination=true",
      expect.anything(),
    );
  });

  it("enabled=false + immediate=false forwarded to useQuery", () => {
    renderHook(() => useUsersList({ enabled: false, immediate: false }));
    expect(vi.mocked(useQuery)).toHaveBeenCalledWith(
      "/auth/email/admin/users?include_pagination=true",
      expect.objectContaining({ enabled: false, immediate: false }),
    );
  });
});
