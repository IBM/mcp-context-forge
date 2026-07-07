import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { IntlProvider } from "react-intl";
import { ChartCard } from "./ChartCard";

const messages = {
  "dashboard.charts.empty.message": "No data in this window",
  "dashboard.charts.empty.hint":
    "Charts show MCP/A2A gateway traffic (/mcp, /rpc, /sse). Admin UI requests are not traced. If you expect data, confirm OBSERVABILITY_ENABLED=true and restart the gateway.",
  "dashboard.charts.error": "Failed to load metrics",
  "dashboard.charts.retry": "Retry",
};

function renderCard(props: Partial<React.ComponentProps<typeof ChartCard>> = {}) {
  const defaultProps = {
    title: "Test card",
    isLoading: false,
    error: null,
    isEmpty: false,
    onRetry: vi.fn(),
    children: <div data-testid="chart-body" />,
    ...props,
  };
  return render(
    <IntlProvider locale="en" messages={messages}>
      <ChartCard {...defaultProps} />
    </IntlProvider>,
  );
}

describe("ChartCard", () => {
  it("renders children when not loading, errored, or empty", () => {
    renderCard();
    expect(screen.getByTestId("chart-body")).toBeInTheDocument();
  });

  it("renders a skeleton when loading", () => {
    const { container } = renderCard({ isLoading: true });
    expect(container.querySelector('[data-slot="skeleton"]')).toBeInTheDocument();
    expect(screen.queryByTestId("chart-body")).not.toBeInTheDocument();
  });

  it("renders the error state with a retry button that fires onRetry", async () => {
    const onRetry = vi.fn();
    renderCard({ error: new Error("nope"), onRetry });

    expect(screen.getByText("Failed to load metrics")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("renders the empty state with both message and hint", () => {
    renderCard({ isEmpty: true });
    expect(screen.getByText("No data in this window")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Charts show MCP/A2A gateway traffic (/mcp, /rpc, /sse). Admin UI requests are not traced. If you expect data, confirm OBSERVABILITY_ENABLED=true and restart the gateway.",
      ),
    ).toBeInTheDocument();
  });

  it("prefers loading over error and empty states", () => {
    renderCard({ isLoading: true, error: new Error("x"), isEmpty: true });
    expect(screen.queryByText("Failed to load metrics")).not.toBeInTheDocument();
    expect(screen.queryByText("No data in this window")).not.toBeInTheDocument();
  });

  it("prefers error over empty when not loading", () => {
    renderCard({ error: new Error("x"), isEmpty: true });
    expect(screen.getByText("Failed to load metrics")).toBeInTheDocument();
    expect(screen.queryByText("No data in this window")).not.toBeInTheDocument();
  });
});
