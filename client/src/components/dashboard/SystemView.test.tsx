import { describe, expect, it, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";

import { useQuery } from "@/hooks/useQuery";
import { renderWithProviders } from "@/test/test-utils";

import { SystemView } from "./SystemView";

vi.mock("@/hooks/useQuery", () => ({ useQuery: vi.fn() }));

const mockUseQuery = vi.mocked(useQuery);

function result<T>(
  data: T | undefined,
  isLoading = false,
  error: { message: string } | null = null,
) {
  return {
    data,
    error,
    isLoading,
    execute: vi.fn(),
    refetch: vi.fn(),
    setData: vi.fn(),
  } as unknown as ReturnType<typeof useQuery>;
}

const METRICS = {
  tools: {
    totalExecutions: 30,
    successfulExecutions: 30,
    failedExecutions: 0,
    failureRate: 0,
    minResponseTime: 0.1,
    maxResponseTime: 0.8,
    avgResponseTime: 0.4,
  },
  resources: {
    totalExecutions: 0,
    successfulExecutions: 0,
    failedExecutions: 0,
    failureRate: 0,
    minResponseTime: null,
    maxResponseTime: null,
    avgResponseTime: null,
  },
  servers: {
    totalExecutions: 7,
    successfulExecutions: 7,
    failedExecutions: 0,
    failureRate: 0.0003,
    minResponseTime: 0.02,
    maxResponseTime: 0.06,
    avgResponseTime: 0.04,
  },
  prompts: {
    totalExecutions: 0,
    successfulExecutions: 0,
    failedExecutions: 0,
    failureRate: 0,
    minResponseTime: null,
    maxResponseTime: null,
    avgResponseTime: null,
  },
};

function mockByPath(overrides: Record<string, unknown> = {}) {
  const byPath: Record<string, unknown> = {
    "/metrics": METRICS,
    "/servers?limit=0&include_inactive=true": [{ enabled: true }, { enabled: false }],
    "/gateways?limit=0&include_inactive=true": [
      { enabled: true },
      { enabled: true },
      { enabled: true, reachable: false },
    ],
    "/a2a?limit=0&include_inactive=true": [{ enabled: true }, { enabled: true }],
    "/tools?limit=0&include_inactive=true": Array.from({ length: 17 }, () => ({})),
    "/resources?limit=0&include_inactive=true": [],
    "/prompts?limit=0&include_inactive=true": [{}, {}],
    ...overrides,
  };
  mockUseQuery.mockImplementation((path: string | null) => result(path ? byPath[path] : undefined));
}

describe("SystemView", () => {
  beforeEach(() => {
    mockUseQuery.mockReset();
  });

  it("renders the combined all-time system stats", () => {
    mockByPath();
    renderWithProviders(<SystemView />);

    // Executions = 30 (tools) + 7 (servers) = 37
    expect(screen.getByText("37")).toBeInTheDocument();
    // Max = 0.8, weighted avg over 37 execs = (0.4*30 + 0.04*7)/37, min = 0.02
    expect(screen.getByText("0.800ms")).toBeInTheDocument();
    expect(screen.getByText("0.020ms")).toBeInTheDocument();
  });

  it("renders virtual server active/total, success rate, and latency", () => {
    mockByPath();
    renderWithProviders(<SystemView />);

    expect(screen.getByText("1 of 2")).toBeInTheDocument();
    expect(screen.getByText("99.97%")).toBeInTheDocument();
    expect(screen.getByText("0.040ms")).toBeInTheDocument();
  });

  it("renders the components inventory with honest zeros and plugin placeholder", () => {
    mockByPath();
    renderWithProviders(<SystemView />);

    expect(screen.getByText("2 of 3 active")).toBeInTheDocument(); // MCP servers
    expect(screen.getByText("2 of 2 active")).toBeInTheDocument(); // A2A
    expect(screen.getByText("17")).toBeInTheDocument(); // Tools
    // REST + gRPC are honest zeros; Resources is a real zero -> three "0" values.
    expect(screen.getAllByText("0").length).toBeGreaterThanOrEqual(3);
    // Plugins unavailable until #5667.
    expect(screen.getByText("Plugins").closest("div")).toHaveTextContent("—");
  });

  it("degrades to placeholders when metrics are unavailable", () => {
    mockByPath({ "/metrics": undefined });
    renderWithProviders(<SystemView />);

    // Success rate + latency fall back to the unavailable placeholder.
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    // Counts still render from their own endpoints.
    expect(screen.getByText("1 of 2")).toBeInTheDocument();
  });

  it("shows A2A as unavailable when the feature is disabled (query errors)", () => {
    mockByPath();
    mockUseQuery.mockImplementation((path: string | null) => {
      if (path === "/a2a?limit=0&include_inactive=true")
        return result(undefined, false, { message: "disabled" });
      const byPath: Record<string, unknown> = {
        "/metrics": METRICS,
        "/servers?limit=0&include_inactive=true": [{ enabled: true }, { enabled: false }],
        "/gateways?limit=0&include_inactive=true": [
          { enabled: true },
          { enabled: true },
          { enabled: true, reachable: false },
        ],
        "/tools?limit=0&include_inactive=true": Array.from({ length: 17 }, () => ({})),
        "/resources?limit=0&include_inactive=true": [],
        "/prompts?limit=0&include_inactive=true": [{}, {}],
      };
      return result(path ? byPath[path] : undefined);
    });
    renderWithProviders(<SystemView />);

    // A2A row shows the placeholder rather than a misleading "0 of 0 active".
    expect(screen.getByText("A2A").closest("div")).toHaveTextContent("—");
  });
});
