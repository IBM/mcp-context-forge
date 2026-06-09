import { describe, it, expect } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { renderWithProviders } from "@/test/test-utils";
import { server } from "@/test/mocks/server";
import { RECENT_ACTIVITY_FIXTURE } from "@/test/mocks/fixtures/recentActivity";

import { RecentActivity } from "./RecentActivity";

describe("RecentActivity", () => {
  it("renders all 10 fixture items after loading", async () => {
    renderWithProviders(<RecentActivity />);

    await waitFor(() => expect(screen.queryAllByTestId("activity-skeleton")).toHaveLength(0));

    for (const item of RECENT_ACTIVITY_FIXTURE) {
      expect(screen.getByText(item.title)).toBeInTheDocument();
    }
  });

  it("filters to error + warning when the Alerts tab is selected", async () => {
    const user = userEvent.setup();
    renderWithProviders(<RecentActivity />);

    await waitFor(() => expect(screen.queryAllByTestId("activity-skeleton")).toHaveLength(0));

    await user.click(screen.getByRole("tab", { name: /alerts/i }));

    const alertOnly = RECENT_ACTIVITY_FIXTURE.filter(
      (item) => item.status === "error" || item.status === "warning",
    );
    expect(alertOnly.length).toBeGreaterThan(0);

    for (const item of alertOnly) {
      expect(screen.getByText(item.title)).toBeInTheDocument();
    }

    const nonAlert = RECENT_ACTIVITY_FIXTURE.find(
      (item) => item.status === "success" || item.status === "info",
    );
    expect(nonAlert).toBeDefined();
    expect(screen.queryByText(nonAlert!.title)).not.toBeInTheDocument();
  });

  it("narrows the list by case-insensitive search", async () => {
    const user = userEvent.setup();
    renderWithProviders(<RecentActivity />);

    await waitFor(() => expect(screen.queryAllByTestId("activity-skeleton")).toHaveLength(0));

    const search = screen.getByRole("searchbox", { name: /search activity/i });
    await user.type(search, "GITHUB");

    expect(screen.getByText("MCP server registered")).toBeInTheDocument();
    expect(screen.queryByText("Virtual server published")).not.toBeInTheDocument();
  });

  it("shows an empty-state message when filters match nothing", async () => {
    const user = userEvent.setup();
    renderWithProviders(<RecentActivity />);

    await waitFor(() => expect(screen.queryAllByTestId("activity-skeleton")).toHaveLength(0));

    const search = screen.getByRole("searchbox", { name: /search activity/i });
    await user.type(search, "this-will-never-match-anything-xyz123");

    expect(screen.getByText(/no activity to show/i)).toBeInTheDocument();
  });

  it("renders the error state and recovers via retry", async () => {
    let callCount = 0;
    server.use(
      http.get("*/api/logs/activity", () => {
        callCount += 1;
        if (callCount === 1) {
          return HttpResponse.json({ detail: "boom" }, { status: 500 });
        }
        return HttpResponse.json({ items: RECENT_ACTIVITY_FIXTURE.slice(0, 3) });
      }),
    );

    const user = userEvent.setup();
    renderWithProviders(<RecentActivity />);

    const errorRegion = await screen.findByRole("alert");
    expect(within(errorRegion).getByText(/couldn't load recent activity/i)).toBeInTheDocument();

    await user.click(within(errorRegion).getByRole("button", { name: /retry/i }));

    await waitFor(() =>
      expect(screen.queryByText(/couldn't load recent activity/i)).not.toBeInTheDocument(),
    );
    expect(screen.getByText(RECENT_ACTIVITY_FIXTURE[0].title)).toBeInTheDocument();
  });

  it("only shows 'View more' when the filtered list exceeds the initial window", async () => {
    server.use(
      http.get("*/api/logs/activity", () =>
        HttpResponse.json({ items: RECENT_ACTIVITY_FIXTURE.slice(0, 3) }),
      ),
    );

    renderWithProviders(<RecentActivity />);

    await waitFor(() => expect(screen.queryAllByTestId("activity-skeleton")).toHaveLength(0));

    expect(screen.queryByRole("button", { name: /view more/i })).not.toBeInTheDocument();
  });
});
