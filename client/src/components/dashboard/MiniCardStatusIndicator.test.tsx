import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";

import { renderWithProviders } from "@/test/test-utils";

import { MiniCardStatusIndicator } from "./MiniCardStatusIndicator";

describe("MiniCardStatusIndicator", () => {
  it("renders nothing for a null status", () => {
    const { container } = renderWithProviders(<MiniCardStatusIndicator status={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders a dot status label", () => {
    renderWithProviders(
      <MiniCardStatusIndicator
        status={{ kind: "dot", tone: "success", labelId: "dashboard.home.status.healthy" }}
      />,
    );
    expect(screen.getByText("Healthy")).toBeInTheDocument();
  });

  it("renders the not-configured label for the muted tone", () => {
    renderWithProviders(
      <MiniCardStatusIndicator
        status={{ kind: "dot", tone: "muted", labelId: "dashboard.home.status.notConfigured" }}
      />,
    );
    expect(screen.getByText("Not configured")).toBeInTheDocument();
  });

  it("renders activity error and warning counts", () => {
    renderWithProviders(
      <MiniCardStatusIndicator status={{ kind: "activity", errors: 0, warnings: 0 }} />,
    );
    expect(screen.getByText("0 errors · 0 warnings")).toBeInTheDocument();
  });
});
