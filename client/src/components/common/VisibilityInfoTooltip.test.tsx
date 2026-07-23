import { act } from "react";
import { describe, expect, it } from "vitest";

import { VisibilityInfoTooltip } from "./VisibilityInfoTooltip";
import { renderWithProviders, screen } from "@/test/test-utils";

describe("VisibilityInfoTooltip", () => {
  it("renders a focusable info trigger", () => {
    renderWithProviders(<VisibilityInfoTooltip />);

    const trigger = screen.getByRole("button", { name: "About visibility levels" });
    expect(trigger).toBeInTheDocument();
  });

  it("explains all three visibility levels when focused", async () => {
    renderWithProviders(<VisibilityInfoTooltip />);

    const trigger = screen.getByRole("button", { name: "About visibility levels" });
    act(() => {
      trigger.focus();
    });

    expect((await screen.findAllByText(/^Private:/)).length).toBeGreaterThan(0);
    expect((await screen.findAllByText(/^Team:/)).length).toBeGreaterThan(0);
    expect(
      (await screen.findAllByText(/^Internal: Visible to everyone signed into this platform/))
        .length,
    ).toBeGreaterThan(0);
  });
});
