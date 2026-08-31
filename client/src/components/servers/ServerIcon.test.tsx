import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ServerIcon } from "./ServerIcon";

describe("ServerIcon", () => {
  it("sets aria-label from the server name", () => {
    render(<ServerIcon name="My Server" />);
    expect(screen.getByLabelText("My Server icon")).toBeInTheDocument();
  });

  it("renders MCPIcon SVG instead of the name initial", () => {
    const { container } = render(<ServerIcon name="Alpha" />);
    expect(container.querySelector("svg")).toBeInTheDocument();
    expect(screen.queryByText("A")).not.toBeInTheDocument();
  });
});
