import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { MainNavIcon } from "./MainNavIcon";

describe("MainNavIcon", () => {
  it("renders SVG element", () => {
    const { container } = render(<MainNavIcon />);
    expect(container.querySelector("svg")).toBeInTheDocument();
  });

  it("renders with correct viewBox", () => {
    const { container } = render(<MainNavIcon />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("viewBox", "0 0 22 20");
  });

  it("renders with correct width and height", () => {
    const { container } = render(<MainNavIcon />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("width", "22");
    expect(svg).toHaveAttribute("height", "20");
  });

  it("renders with fill none", () => {
    const { container } = render(<MainNavIcon />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("fill", "none");
  });

  it("renders multiple path elements", () => {
    const { container } = render(<MainNavIcon />);
    const paths = container.querySelectorAll("path");
    expect(paths.length).toBeGreaterThanOrEqual(2);
  });

  it("renders paths with fill currentColor", () => {
    const { container } = render(<MainNavIcon />);
    const paths = container.querySelectorAll("path");
    let hasCurrentColorFill = false;
    paths.forEach((path) => {
      if (path.getAttribute("fill") === "currentColor") {
        hasCurrentColorFill = true;
      }
    });
    expect(hasCurrentColorFill).toBe(true);
  });

  it("renders path with red fill for accent", () => {
    const { container } = render(<MainNavIcon />);
    const paths = container.querySelectorAll("path");
    let hasRedFill = false;
    paths.forEach((path) => {
      if (path.getAttribute("fill") === "#FF4540") {
        hasRedFill = true;
      }
    });
    expect(hasRedFill).toBe(true);
  });

  it("applies custom className", () => {
    const { container } = render(<MainNavIcon className="custom-class" />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveClass("custom-class");
  });

  it("applies multiple custom classes", () => {
    const { container } = render(<MainNavIcon className="w-6 h-6 text-red-500" />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveClass("w-6");
    expect(svg).toHaveClass("h-6");
    expect(svg).toHaveClass("text-red-500");
  });

  it("renders without className when not provided", () => {
    const { container } = render(<MainNavIcon />);
    const svg = container.querySelector("svg");
    expect(svg?.className.baseVal).toBe("");
  });

  it("renders with undefined className gracefully", () => {
    const { container } = render(<MainNavIcon className={undefined} />);
    const svg = container.querySelector("svg");
    expect(svg).toBeInTheDocument();
  });

  it("renders with xmlns attribute", () => {
    const { container } = render(<MainNavIcon />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("xmlns", "http://www.w3.org/2000/svg");
  });

  it("preserves path data", () => {
    const { container } = render(<MainNavIcon />);
    const paths = container.querySelectorAll("path");
    paths.forEach((path) => {
      expect(path.getAttribute("d")).toBeTruthy();
    });
  });

  it("renders icon with consistent properties", () => {
    const { container: container1 } = render(<MainNavIcon />);
    const { container: container2 } = render(<MainNavIcon />);

    const svg1 = container1.querySelector("svg");
    const svg2 = container2.querySelector("svg");

    expect(svg1?.getAttribute("viewBox")).toBe(svg2?.getAttribute("viewBox"));
    expect(svg1?.getAttribute("width")).toBe(svg2?.getAttribute("width"));
    expect(svg1?.getAttribute("height")).toBe(svg2?.getAttribute("height"));
  });

  it("has fillRule attribute on path", () => {
    const { container } = render(<MainNavIcon />);
    const path = container.querySelector("path[fill-rule]");
    expect(path).toBeInTheDocument();
  });

  it("has clipRule attribute on path", () => {
    const { container } = render(<MainNavIcon />);
    const path = container.querySelector("path[clip-rule]");
    expect(path).toBeInTheDocument();
  });
});
