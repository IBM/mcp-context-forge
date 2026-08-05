import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";

import { renderWithProviders } from "@/test/test-utils";

import { MiniCardStatusIndicator } from "./MiniCardStatusIndicator";

describe("MiniCardStatusIndicator", () => {
  it("renders the green Online label", () => {
    renderWithProviders(
      <MiniCardStatusIndicator
        status={{ kind: "dot", tone: "success", labelId: "dashboard.home.status.online" }}
      />,
    );
    expect(screen.getByText("Online")).toBeInTheDocument();
  });

  it("renders the grey Offline label for the muted tone", () => {
    renderWithProviders(
      <MiniCardStatusIndicator
        status={{ kind: "dot", tone: "muted", labelId: "dashboard.home.status.offline" }}
      />,
    );
    expect(screen.getByText("Offline")).toBeInTheDocument();
  });

  it("renders activity error and warning counts", () => {
    renderWithProviders(
      <MiniCardStatusIndicator status={{ kind: "activity", errors: 0, warnings: 0 }} />,
    );
    expect(screen.getByText("0 errors · 0 warnings")).toBeInTheDocument();
  });
});
