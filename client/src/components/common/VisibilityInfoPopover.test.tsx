import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { VisibilityInfoPopover } from "./VisibilityInfoPopover";
import { renderWithProviders, screen } from "@/test/test-utils";

describe("VisibilityInfoPopover", () => {
  it("renders a focusable info trigger", () => {
    renderWithProviders(<VisibilityInfoPopover />);

    expect(screen.getByRole("button", { name: "About visibility levels" })).toBeInTheDocument();
  });

  it("explains all three visibility levels when opened", async () => {
    const user = userEvent.setup();
    renderWithProviders(<VisibilityInfoPopover />);

    await user.click(screen.getByRole("button", { name: "About visibility levels" }));

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText(/^Private:/)).toBeInTheDocument();
    expect(screen.getByText(/^Team:/)).toBeInTheDocument();
    expect(
      screen.getByText(/^Internal: Visible to everyone signed into this platform/),
    ).toBeInTheDocument();
  });

  it("dismisses on Escape", async () => {
    const user = userEvent.setup();
    renderWithProviders(<VisibilityInfoPopover />);

    await user.click(screen.getByRole("button", { name: "About visibility levels" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();

    await user.keyboard("{Escape}");

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
