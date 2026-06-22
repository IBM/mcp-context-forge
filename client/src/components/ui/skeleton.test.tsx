import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import React from "react";
import { Skeleton } from "./skeleton";

describe("Skeleton", () => {
  it("should render the skeleton element", () => {
    const { container } = render(<Skeleton />);
    const el = container.querySelector('[data-slot="skeleton"]');
    expect(el).toBeInTheDocument();
  });

  it("should merge custom className", () => {
    const { container } = render(<Skeleton className="custom-class" />);
    const el = container.querySelector('[data-slot="skeleton"]');
    expect(el).toHaveClass("custom-class");
  });

  it("should forward HTML attributes", () => {
    const { container } = render(<Skeleton id="test-id" data-testid="skeleton-test" />);
    const el = container.querySelector('[data-slot="skeleton"]');
    expect(el).toHaveAttribute("id", "test-id");
    expect(el).toHaveAttribute("data-testid", "skeleton-test");
  });
});
