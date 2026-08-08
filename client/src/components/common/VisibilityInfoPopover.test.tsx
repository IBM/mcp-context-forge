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

  it("explains only the selected level when given a visibility value", async () => {
    const user = userEvent.setup();
    renderWithProviders(<VisibilityInfoPopover visibility="public" />);

    await user.click(screen.getByRole("button", { name: "About visibility levels" }));

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Visible to everyone signed into this platform. Not on the public internet.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Only you can see this/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Scoped to a team/)).not.toBeInTheDocument();
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
