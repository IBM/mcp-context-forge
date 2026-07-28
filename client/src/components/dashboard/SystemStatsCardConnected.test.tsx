import { describe, expect, it, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";

import { useQuery } from "@/hooks/useQuery";
import { renderWithProviders } from "@/test/test-utils";

import { SystemStatsCardConnected } from "./SystemStatsCardConnected";

vi.mock("@/hooks/useQuery", () => ({ useQuery: vi.fn() }));

const mockUseQuery = vi.mocked(useQuery);

function entity(total: number, avg: number | null, min: number | null, max: number | null) {
  return {
    totalExecutions: total,
    successfulExecutions: total,
    failedExecutions: 0,
    failureRate: 0,
    minResponseTime: min,
    maxResponseTime: max,
    avgResponseTime: avg,
  };
}

function queryResult(data: unknown, isLoading = false) {
  return {
    data,
    error: null,
    isLoading,
    execute: vi.fn(),
    refetch: vi.fn(),
    setData: vi.fn(),
  } as unknown as ReturnType<typeof useQuery>;
}

describe("SystemStatsCardConnected", () => {
  beforeEach(() => mockUseQuery.mockReset());

  it("fetches /metrics and renders the combined executions total", () => {
    mockUseQuery.mockReturnValue(
      queryResult({
        tools: entity(30, 0.4, 0.1, 0.8),
        resources: entity(0, null, null, null),
        servers: entity(7, 0.04, 0.02, 0.06),
        prompts: entity(0, null, null, null),
      }),
    );

    renderWithProviders(<SystemStatsCardConnected />);

    expect(mockUseQuery).toHaveBeenCalledWith("/metrics");
    expect(screen.getByText("37")).toBeInTheDocument();
    expect(screen.getByText("0.800ms")).toBeInTheDocument();
  });

  it("shows skeletons while metrics load", () => {
    mockUseQuery.mockReturnValue(queryResult(undefined, true));
    const { container } = renderWithProviders(<SystemStatsCardConnected />);
    expect(container.querySelectorAll('[data-slot="skeleton"]').length).toBeGreaterThan(0);
  });
});
