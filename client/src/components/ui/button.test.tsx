import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Button } from "./button";

describe("Button Component", () => {
  it("renders a regular button by default", () => {
    render(<Button data-testid="btn">Click me</Button>);
    const button = screen.getByTestId("btn");
    expect(button.tagName).toBe("BUTTON");
    expect(button).toHaveTextContent("Click me");
  });

  it("renders as child element when asChild is true", () => {
    render(
      <Button asChild data-testid="link-btn">
        <a href="https://example.com">Link Button</a>
      </Button>,
    );
    const link = screen.getByTestId("link-btn");
    expect(link.tagName).toBe("A");
    expect(link).toHaveAttribute("href", "https://example.com");
    expect(link).toHaveTextContent("Link Button");
  });

  it("applies variants and sizes", () => {
    render(
      <Button variant="destructive" size="sm" data-testid="custom-btn">
        Custom
      </Button>,
    );
    const btn = screen.getByTestId("custom-btn");
    expect(btn).toHaveAttribute("data-variant", "destructive");
    expect(btn).toHaveAttribute("data-size", "sm");
  });
});
