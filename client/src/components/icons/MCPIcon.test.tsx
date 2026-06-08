import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { MCPIcon } from "./MCPIcon";

describe("MCPIcon", () => {
  it("renders SVG element", () => {
    const { container } = render(<MCPIcon />);
    expect(container.querySelector("svg")).toBeInTheDocument();
  });

  it("renders with correct viewBox", () => {
    const { container } = render(<MCPIcon />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("viewBox", "0 0 18 18");
  });

  it("renders with correct width and height", () => {
    const { container } = render(<MCPIcon />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("width", "18");
    expect(svg).toHaveAttribute("height", "18");
  });

  it("renders with fill none", () => {
    const { container } = render(<MCPIcon />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("fill", "none");
  });

  it("renders multiple path elements", () => {
    const { container } = render(<MCPIcon />);
    const paths = container.querySelectorAll("path");
    expect(paths.length).toBeGreaterThanOrEqual(2);
  });

  it("renders paths with fill currentColor", () => {
    const { container } = render(<MCPIcon />);
    const paths = container.querySelectorAll("path");
    paths.forEach((path) => {
      expect(path).toHaveAttribute("fill", "currentColor");
    });
  });

  it("applies custom className", () => {
    const { container } = render(<MCPIcon className="custom-class" />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveClass("custom-class");
  });

  it("applies multiple custom classes", () => {
    const { container } = render(<MCPIcon className="w-8 h-8 text-blue-500" />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveClass("w-8");
    expect(svg).toHaveClass("h-8");
    expect(svg).toHaveClass("text-blue-500");
  });

  it("renders without className when not provided", () => {
    const { container } = render(<MCPIcon />);
    const svg = container.querySelector("svg");
    expect(svg?.className.baseVal).toBe("");
  });

  it("renders with undefined className gracefully", () => {
    const { container } = render(<MCPIcon className={undefined} />);
    const svg = container.querySelector("svg");
    expect(svg).toBeInTheDocument();
  });

  it("renders with xmlns attribute", () => {
    const { container } = render(<MCPIcon />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("xmlns", "http://www.w3.org/2000/svg");
  });

  it("has consistent SVG properties across renders", () => {
    const { container: container1 } = render(<MCPIcon />);
    const { container: container2 } = render(<MCPIcon />);

    const svg1 = container1.querySelector("svg");
    const svg2 = container2.querySelector("svg");

    expect(svg1?.getAttribute("viewBox")).toBe(svg2?.getAttribute("viewBox"));
    expect(svg1?.getAttribute("width")).toBe(svg2?.getAttribute("width"));
    expect(svg1?.getAttribute("height")).toBe(svg2?.getAttribute("height"));
  });

  it("preserves path data integrity", () => {
    const { container } = render(<MCPIcon />);
    const paths = container.querySelectorAll("path");
    paths.forEach((path) => {
      expect(path.getAttribute("d")).toBeTruthy();
    });
  });
});
