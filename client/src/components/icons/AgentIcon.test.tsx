import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { AgentIcon } from "./AgentIcon";

describe("AgentIcon", () => {
  it("renders SVG element", () => {
    const { container } = render(<AgentIcon />);
    expect(container.querySelector("svg")).toBeInTheDocument();
  });

  it("renders with correct viewBox", () => {
    const { container } = render(<AgentIcon />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("viewBox", "0 0 18 18");
  });

  it("renders with correct width and height", () => {
    const { container } = render(<AgentIcon />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("width", "18");
    expect(svg).toHaveAttribute("height", "18");
  });

  it("renders with fill none", () => {
    const { container } = render(<AgentIcon />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("fill", "none");
  });

  it("renders path elements", () => {
    const { container } = render(<AgentIcon />);
    const paths = container.querySelectorAll("path");
    expect(paths.length).toBeGreaterThan(0);
  });

  it("renders paths with stroke color", () => {
    const { container } = render(<AgentIcon />);
    const path = container.querySelector("path");
    expect(path).toHaveAttribute("stroke", "currentColor");
  });

  it("applies custom className", () => {
    const { container } = render(<AgentIcon className="custom-class" />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveClass("custom-class");
  });

  it("applies custom className while preserving attributes", () => {
    const { container } = render(<AgentIcon className="w-6 h-6" />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveClass("w-6");
    expect(svg).toHaveClass("h-6");
    expect(svg).toHaveAttribute("viewBox", "0 0 18 18");
  });

  it("renders without className when not provided", () => {
    const { container } = render(<AgentIcon />);
    const svg = container.querySelector("svg");
    expect(svg?.className.baseVal).toBe("");
  });

  it("renders with undefined className gracefully", () => {
    const { container } = render(<AgentIcon className={undefined} />);
    const svg = container.querySelector("svg");
    expect(svg).toBeInTheDocument();
  });

  it("renders with xmlns attribute", () => {
    const { container } = render(<AgentIcon />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("xmlns", "http://www.w3.org/2000/svg");
  });

  it("renders with correct stroke attributes", () => {
    const { container } = render(<AgentIcon />);
    const path = container.querySelector("path");
    expect(path).toHaveAttribute("stroke-width", "1.25");
    expect(path).toHaveAttribute("stroke-linecap", "round");
    expect(path).toHaveAttribute("stroke-linejoin", "round");
  });
});
