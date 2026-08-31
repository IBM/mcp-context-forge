import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { GitHubIcon } from "./GitHubIcon";

describe("GitHubIcon", () => {
  it("renders SVG element", () => {
    const { container } = render(<GitHubIcon />);
    expect(container.querySelector("svg")).toBeInTheDocument();
  });

  it("renders with correct viewBox", () => {
    const { container } = render(<GitHubIcon />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("viewBox", "0 0 24 24");
  });

  it("renders with fill currentColor", () => {
    const { container } = render(<GitHubIcon />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("fill", "currentColor");
  });

  it("renders path element", () => {
    const { container } = render(<GitHubIcon />);
    const path = container.querySelector("path");
    expect(path).toBeInTheDocument();
  });

  it("renders path with GitHub logo shape", () => {
    const { container } = render(<GitHubIcon />);
    const path = container.querySelector("path");
    expect(path?.getAttribute("d")).toBeTruthy();
  });

  it("applies custom className", () => {
    const { container } = render(<GitHubIcon className="custom-class" />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveClass("custom-class");
  });

  it("applies multiple custom classes", () => {
    const { container } = render(<GitHubIcon className="w-6 h-6 text-white" />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveClass("w-6");
    expect(svg).toHaveClass("h-6");
    expect(svg).toHaveClass("text-white");
  });

  it("renders without className when not provided", () => {
    const { container } = render(<GitHubIcon />);
    const svg = container.querySelector("svg");
    expect(svg?.className.baseVal).toBe("");
  });

  it("renders with undefined className gracefully", () => {
    const { container } = render(<GitHubIcon className={undefined} />);
    const svg = container.querySelector("svg");
    expect(svg).toBeInTheDocument();
  });

  it("renders with xmlns attribute", () => {
    const { container } = render(<GitHubIcon />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("xmlns", "http://www.w3.org/2000/svg");
  });

  it("is semantic with aria-hidden or role", () => {
    const { container } = render(<GitHubIcon />);
    const svg = container.querySelector("svg");
    const hasSemanticProps = svg?.hasAttribute("aria-hidden") || svg?.hasAttribute("role");
    expect(hasSemanticProps).toBeTruthy();
  });

  it("renders consistently across multiple renders", () => {
    const { container: container1 } = render(<GitHubIcon />);
    const { container: container2 } = render(<GitHubIcon />);

    const svg1 = container1.querySelector("svg");
    const svg2 = container2.querySelector("svg");

    expect(svg1?.getAttribute("viewBox")).toBe(svg2?.getAttribute("viewBox"));
    expect(svg1?.getAttribute("fill")).toBe(svg2?.getAttribute("fill"));
  });

  it("preserves GitHub logo integrity", () => {
    const { container } = render(<GitHubIcon />);
    const path = container.querySelector("path");
    const pathData = path?.getAttribute("d");
    expect(pathData).toContain("M");
    expect(pathData).toContain("C");
  });
});
