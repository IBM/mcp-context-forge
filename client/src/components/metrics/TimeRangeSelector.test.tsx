import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { IntlProvider } from "react-intl";
import { TimeRangeSelector } from "./TimeRangeSelector";

const messages = {
  "dashboard.timeRange.label": "Time range",
  "dashboard.timeRange.hour": "Last hour",
  "dashboard.timeRange.day": "Last 24 hours",
  "dashboard.timeRange.week": "Last 7 days",
};

function renderSelector(value: "hour" | "day" | "week" = "day", onChange = vi.fn()) {
  render(
    <IntlProvider locale="en" messages={messages}>
      <TimeRangeSelector value={value} onChange={onChange} />
    </IntlProvider>,
  );
  return { onChange };
}

describe("TimeRangeSelector", () => {
  it("renders with the current selection shown", () => {
    renderSelector("day");
    expect(screen.getByRole("combobox", { name: "Time range" })).toHaveTextContent("Last 24 hours");
  });

  it("calls onChange with the new window when a different option is picked", async () => {
    const { onChange } = renderSelector("day");
    await userEvent.click(screen.getByRole("combobox", { name: "Time range" }));
    await userEvent.click(await screen.findByRole("option", { name: "Last hour" }));
    expect(onChange).toHaveBeenCalledWith("hour");
  });
});
