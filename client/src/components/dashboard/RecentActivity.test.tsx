import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, fireEvent } from "@testing-library/react";

import { renderWithProviders } from "@/test/test-utils";
import { useRecentActivity } from "@/hooks/useRecentActivity";
import type { ActivityItem } from "@/types/activity";
import { RecentActivity } from "./RecentActivity";

vi.mock("@/hooks/useRecentActivity", () => ({ useRecentActivity: vi.fn() }));

const mockUseRecentActivity = vi.mocked(useRecentActivity);

const ITEMS: ActivityItem[] = [
  {
    id: "audit:1",
    timestamp: "2026-06-08T17:53:24Z",
    source: "audit",
    title: "MCP server registered",
    description: "github-tools was registered by alice.",
    status: "success",
    resource_type: "gateway",
    resource_name: "github-tools",
    actor: "alice@acme.io",
    correlation_id: "c1",
  },
  {
    id: "security:2",
    timestamp: "2026-06-08T16:00:00Z",
    source: "security",
    title: "Auth failure",
    description: "Invalid token rejected.",
    status: "error",
    resource_type: "auth",
    resource_name: "login",
    actor: "bob@acme.io",
    correlation_id: "c2",
  },
  {
    id: "audit:3",
    timestamp: "2026-06-08T15:00:00Z",
    source: "audit",
    title: "Plugin warning",
    description: "Rate limit approaching.",
    status: "warning",
    resource_type: "plugin",
    resource_name: "pii-redactor",
    actor: "system",
    correlation_id: "c3",
  },
];

function mockActivity(over: Partial<ReturnType<typeof useRecentActivity>> = {}) {
  mockUseRecentActivity.mockReturnValue({
    items: ITEMS,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    ...over,
  });
}

describe("RecentActivity", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders all items by default", () => {
    mockActivity();
    renderWithProviders(<RecentActivity />);

    expect(screen.getByText("MCP server registered")).toBeInTheDocument();
    expect(screen.getByText("Auth failure")).toBeInTheDocument();
    expect(screen.getByText("Plugin warning")).toBeInTheDocument();
  });

  it("shows live error and warning counts on the filter chips", () => {
    mockActivity();
    renderWithProviders(<RecentActivity />);

    expect(screen.getByRole("button", { name: /Errors/ })).toHaveTextContent("1");
    expect(screen.getByRole("button", { name: /Warnings/ })).toHaveTextContent("1");
  });

  it("filters to errors, and All activity returns to the full list", () => {
    mockActivity();
    renderWithProviders(<RecentActivity />);

    fireEvent.click(screen.getByRole("button", { name: /Errors/ }));

    expect(screen.getByText("Auth failure")).toBeInTheDocument();
    expect(screen.queryByText("MCP server registered")).not.toBeInTheDocument();
    expect(screen.queryByText("Plugin warning")).not.toBeInTheDocument();

    // "All activity" is the single-select default and the way back after filtering.
    fireEvent.click(screen.getByRole("button", { name: /All activity/ }));
    expect(screen.getByText("MCP server registered")).toBeInTheDocument();
    expect(screen.getByText("Plugin warning")).toBeInTheDocument();
  });

  it("toggles the Warnings filter to show only warnings", () => {
    mockActivity();
    renderWithProviders(<RecentActivity />);

    fireEvent.click(screen.getByRole("button", { name: /Warnings/ }));

    expect(screen.getByText("Plugin warning")).toBeInTheDocument();
    expect(screen.queryByText("Auth failure")).not.toBeInTheDocument();
  });

  it("filters by search after opening the search input", () => {
    mockActivity();
    renderWithProviders(<RecentActivity />);

    fireEvent.click(screen.getByRole("button", { name: "Search activity" }));
    fireEvent.change(screen.getByRole("searchbox", { name: "Search activity" }), {
      target: { value: "github" },
    });

    expect(screen.getByText("MCP server registered")).toBeInTheDocument();
    expect(screen.queryByText("Auth failure")).not.toBeInTheDocument();
  });

  it("shows the empty state when there is no activity", () => {
    mockActivity({ items: [] });
    renderWithProviders(<RecentActivity />);

    expect(screen.getByText("No activity to show.")).toBeInTheDocument();
  });

  it("shows an error with a retry that refetches", () => {
    const refetch = vi.fn();
    mockActivity({ items: [], error: { message: "boom" }, refetch });
    renderWithProviders(<RecentActivity />);

    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't load recent activity.");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(refetch).toHaveBeenCalledOnce();
  });

  it("hides the filter/search toolbar in the error state", () => {
    mockActivity({ items: [], error: { message: "boom" } });
    renderWithProviders(<RecentActivity />);

    expect(screen.queryByRole("button", { name: /All activity/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Search activity" })).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("shows skeletons while loading", () => {
    mockActivity({ items: [], isLoading: true });
    renderWithProviders(<RecentActivity />);

    expect(screen.getAllByTestId("activity-skeleton").length).toBeGreaterThan(0);
  });
});
