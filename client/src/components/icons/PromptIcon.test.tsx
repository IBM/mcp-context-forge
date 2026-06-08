import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { PromptIcon } from "./PromptIcon";

describe("PromptIcon", () => {
  it("renders SVG element", () => {
    const { container } = render(<PromptIcon />);
    expect(container.querySelector("svg")).toBeInTheDocument();
  });

  it("renders with correct viewBox", () => {
    const { container } = render(<PromptIcon />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("viewBox", "0 0 18 18");
  });

  it("renders with correct width and height", () => {
    const { container } = render(<PromptIcon />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("width", "18");
    expect(svg).toHaveAttribute("height", "18");
  });

  it("renders with fill none", () => {
    const { container } = render(<PromptIcon />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("fill", "none");
  });

  it("renders multiple path elements", () => {
    const { container } = render(<PromptIcon />);
    const paths = container.querySelectorAll("path");
    expect(paths.length).toBeGreaterThanOrEqual(1);
  });

  it("renders paths with fill currentColor", () => {
    const { container } = render(<PromptIcon />);
    const paths = container.querySelectorAll("path");
    paths.forEach((path) => {
      expect(path).toHaveAttribute("fill", "currentColor");
    });
  });

  it("applies custom className", () => {
    const { container } = render(<PromptIcon className="custom-class" />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveClass("custom-class");
  });

  it("applies multiple custom classes", () => {
    const { container } = render(<PromptIcon className="w-5 h-5 text-gray-700" />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveClass("w-5");
    expect(svg).toHaveClass("h-5");
    expect(svg).toHaveClass("text-gray-700");
  });

  it("renders without className when not provided", () => {
    const { container } = render(<PromptIcon />);
    const svg = container.querySelector("svg");
    expect(svg?.className.baseVal).toBe("");
  });

  it("renders with undefined className gracefully", () => {
    const { container } = render(<PromptIcon className={undefined} />);
    const svg = container.querySelector("svg");
    expect(svg).toBeInTheDocument();
  });

  it("renders with xmlns attribute", () => {
    const { container } = render(<PromptIcon />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("xmlns", "http://www.w3.org/2000/svg");
  });

  it("preserves path data", () => {
    const { container } = render(<PromptIcon />);
    const paths = container.querySelectorAll("path");
    paths.forEach((path) => {
      expect(path.getAttribute("d")).toBeTruthy();
    });
  });

  it("renders icon with consistent properties", () => {
    const { container: container1 } = render(<PromptIcon />);
    const { container: container2 } = render(<PromptIcon />);

    const svg1 = container1.querySelector("svg");
    const svg2 = container2.querySelector("svg");

    expect(svg1?.getAttribute("viewBox")).toBe(svg2?.getAttribute("viewBox"));
    expect(svg1?.getAttribute("width")).toBe(svg2?.getAttribute("width"));
  });
});
