import { describe, it, expect } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/test-utils";
import { VisibilityHelp } from "./visibility-help";

describe("VisibilityHelp", () => {
  it("renders an accessible help trigger", () => {
    renderWithProviders(<VisibilityHelp />);
    expect(screen.getByRole("button", { name: "Visibility levels" })).toBeInTheDocument();
  });

  it("explains all three visibility levels when open", () => {
    renderWithProviders(<VisibilityHelp defaultOpen />);
    expect(screen.getAllByText("Private").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Team").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Internal").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Not on the public internet/).length).toBeGreaterThan(0);
  });
});
