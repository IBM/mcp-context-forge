import { describe, it, expect, beforeEach } from "vitest";
import { render } from "@testing-library/react";
import React from "react";
import { Skeleton } from "./skeleton";

describe("Skeleton", () => {
  beforeEach(() => {
    // Clear state if needed
  });

  describe("Rendering", () => {
    it("should render the skeleton element", () => {
      const { container } = render(<Skeleton />);
      const el = container.querySelector('[data-slot="skeleton"]');
      expect(el).toBeInTheDocument();
    });

    it("should render as a div element", () => {
      const { container } = render(<Skeleton />);
      const el = container.querySelector('[data-slot="skeleton"]');
      expect(el?.tagName).toBe("DIV");
    });

    it("should have data-slot attribute set to skeleton", () => {
      const { container } = render(<Skeleton />);
      const el = container.querySelector('[data-slot="skeleton"]');
      expect(el).toHaveAttribute("data-slot", "skeleton");
    });
  });

  describe("Styling", () => {
    it("should apply default skeleton classes", () => {
      const { container } = render(<Skeleton />);
      const el = container.querySelector('[data-slot="skeleton"]');

      expect(el).toHaveClass("animate-pulse");
      expect(el).toHaveClass("rounded-md");
      expect(el).toHaveClass("bg-muted");
    });

    it("should merge custom className with default classes", () => {
      const { container } = render(<Skeleton className="custom-class" />);
      const el = container.querySelector('[data-slot="skeleton"]');

      expect(el).toHaveClass("custom-class");
      expect(el).toHaveClass("animate-pulse");
      expect(el).toHaveClass("rounded-md");
      expect(el).toHaveClass("bg-muted");
    });

    it("should merge multiple custom classes with default classes", () => {
      const { container } = render(<Skeleton className="my-skeleton custom-styling" />);
      const el = container.querySelector('[data-slot="skeleton"]');

      expect(el).toHaveClass("my-skeleton");
      expect(el).toHaveClass("custom-styling");
      expect(el).toHaveClass("animate-pulse");
      expect(el).toHaveClass("bg-muted");
    });

    it("should allow custom className to override default bg color", () => {
      const { container } = render(<Skeleton className="bg-red-500" />);
      const el = container.querySelector('[data-slot="skeleton"]');

      expect(el).toHaveClass("bg-red-500");
      expect(el?.className).toContain("bg-red-500");
    });

    it("should allow custom className to override animation", () => {
      const { container } = render(<Skeleton className="animate-bounce" />);
      const el = container.querySelector('[data-slot="skeleton"]');

      expect(el).toHaveClass("animate-bounce");
      expect(el?.className).toContain("animate-bounce");
    });

    it("should handle empty className", () => {
      const { container } = render(<Skeleton className="" />);
      const el = container.querySelector('[data-slot="skeleton"]');

      expect(el).toBeInTheDocument();
      expect(el).toHaveClass("animate-pulse");
      expect(el).toHaveClass("bg-muted");
    });
  });

  describe("Props Forwarding", () => {
    it("should forward standard HTML attributes", () => {
      const { container } = render(<Skeleton id="my-skeleton" title="Loading skeleton" />);
      const el = container.querySelector('[data-slot="skeleton"]');

      expect(el).toHaveAttribute("id", "my-skeleton");
      expect(el).toHaveAttribute("title", "Loading skeleton");
    });

    it("should forward data-* attributes", () => {
      const { container } = render(<Skeleton data-testid="skeleton-1" data-custom="value" />);
      const el = container.querySelector('[data-slot="skeleton"]');

      expect(el).toHaveAttribute("data-testid", "skeleton-1");
      expect(el).toHaveAttribute("data-custom", "value");
    });

    it("should forward aria-* attributes", () => {
      const { container } = render(<Skeleton aria-label="Loading content" aria-busy="true" />);
      const el = container.querySelector('[data-slot="skeleton"]');

      expect(el).toHaveAttribute("aria-label", "Loading content");
      expect(el).toHaveAttribute("aria-busy", "true");
    });

    it("should forward role attribute", () => {
      const { container } = render(<Skeleton role="presentation" />);
      const el = container.querySelector('[data-slot="skeleton"]');

      expect(el).toHaveAttribute("role", "presentation");
    });

    it("should forward className along with other props", () => {
      const { container } = render(
        <Skeleton className="custom-skeleton" id="skeleton-2" data-testid="skel-test" />,
      );
      const el = container.querySelector('[data-slot="skeleton"]');

      expect(el).toHaveClass("custom-skeleton");
      expect(el).toHaveAttribute("id", "skeleton-2");
      expect(el).toHaveAttribute("data-testid", "skel-test");
    });

    it("should forward style prop", () => {
      const { container } = render(<Skeleton style={{ width: "100px", height: "20px" }} />);
      const el = container.querySelector('[data-slot="skeleton"]');

      expect(el).toHaveStyle("width: 100px");
      expect(el).toHaveStyle("height: 20px");
    });

    it("should forward multiple standard div attributes", () => {
      const { container } = render(
        <Skeleton
          id="sk1"
          title="Skeleton"
          data-testid="test-sk"
          aria-hidden="true"
          tabIndex={-1}
        />,
      );
      const el = container.querySelector('[data-slot="skeleton"]');

      expect(el).toHaveAttribute("id", "sk1");
      expect(el).toHaveAttribute("title", "Skeleton");
      expect(el).toHaveAttribute("data-testid", "test-sk");
      expect(el).toHaveAttribute("aria-hidden", "true");
      expect(el).toHaveAttribute("tabIndex", "-1");
    });
  });

  describe("Ref Forwarding", () => {
    it("should forward ref to the underlying div element", () => {
      const ref = React.createRef<HTMLDivElement>();
      render(<Skeleton ref={ref} />);

      expect(ref.current).toBeInTheDocument();
      expect(ref.current?.tagName).toBe("DIV");
    });

    it("should allow ref access for DOM manipulation", () => {
      const ref = React.createRef<HTMLDivElement>();
      render(<Skeleton ref={ref} />);

      expect(ref.current).toBeTruthy();
      expect(ref.current?.classList.contains("bg-muted")).toBe(true);
      expect(ref.current?.classList.contains("animate-pulse")).toBe(true);
    });

    it("should allow ref to be used with querySelector", () => {
      const ref = React.createRef<HTMLDivElement>();
      render(<Skeleton ref={ref} />);

      // The ref itself is the skeleton element, not a container
      expect(ref.current?.getAttribute("data-slot")).toBe("skeleton");
    });
  });

  describe("Accessibility", () => {
    it("should support aria-label for accessibility", () => {
      const { container } = render(<Skeleton aria-label="Content loading" />);
      const el = container.querySelector('[data-slot="skeleton"]');

      expect(el).toHaveAttribute("aria-label", "Content loading");
    });

    it("should support aria-busy for loading state", () => {
      const { container } = render(<Skeleton aria-busy="true" />);
      const el = container.querySelector('[data-slot="skeleton"]');

      expect(el).toHaveAttribute("aria-busy", "true");
    });

    it("should support aria-hidden for decorative skeletons", () => {
      const { container } = render(<Skeleton aria-hidden="true" />);
      const el = container.querySelector('[data-slot="skeleton"]');

      expect(el).toHaveAttribute("aria-hidden", "true");
    });

    it("should support role=presentation for purely decorative", () => {
      const { container } = render(<Skeleton role="presentation" />);
      const el = container.querySelector('[data-slot="skeleton"]');

      expect(el).toHaveAttribute("role", "presentation");
    });

    it("should support aria-labelledby", () => {
      const { container } = render(<Skeleton aria-labelledby="label-id" />);
      const el = container.querySelector('[data-slot="skeleton"]');

      expect(el).toHaveAttribute("aria-labelledby", "label-id");
    });

    it("should support aria-describedby", () => {
      const { container } = render(<Skeleton aria-describedby="desc-id" />);
      const el = container.querySelector('[data-slot="skeleton"]');

      expect(el).toHaveAttribute("aria-describedby", "desc-id");
    });
  });

  describe("Export", () => {
    it("should export Skeleton component", () => {
      expect(Skeleton).toBeDefined();
      expect(typeof Skeleton).toBe("function");
    });
  });

  describe("Integration", () => {
    it("should render multiple skeletons independently", () => {
      const { container } = render(
        <div>
          <Skeleton data-testid="skeleton-1" />
          <Skeleton data-testid="skeleton-2" />
          <Skeleton data-testid="skeleton-3" />
        </div>,
      );

      const skeletons = container.querySelectorAll('[data-slot="skeleton"]');
      expect(skeletons).toHaveLength(3);
    });

    it("should work in a loading placeholder layout", () => {
      const { container } = render(
        <div>
          <Skeleton className="w-full h-12 mb-4" />
          <Skeleton className="w-full h-64 mb-4" />
          <Skeleton className="w-1/2 h-8" />
        </div>,
      );

      const skeletons = container.querySelectorAll('[data-slot="skeleton"]');
      expect(skeletons).toHaveLength(3);
      expect(skeletons[0]).toHaveClass("w-full");
      expect(skeletons[0]).toHaveClass("h-12");
    });

    it("should work with aria-busy in loading context", () => {
      const { container } = render(
        <div role="status" aria-label="Loading content" aria-busy="true">
          <Skeleton />
        </div>,
      );

      const skeleton = container.querySelector('[data-slot="skeleton"]');
      const container_el = container.querySelector('[role="status"]');

      expect(skeleton).toBeInTheDocument();
      expect(container_el).toHaveAttribute("aria-busy", "true");
    });

    it("should render with className merging in complex layouts", () => {
      const { container } = render(
        <div className="space-y-4">
          <Skeleton className="h-12 w-12 rounded-full" />
          <div className="space-y-2">
            <Skeleton className="h-4 w-[250px]" />
            <Skeleton className="h-4 w-[200px]" />
          </div>
        </div>,
      );

      const skeletons = container.querySelectorAll('[data-slot="skeleton"]');
      expect(skeletons).toHaveLength(3);
      expect(skeletons[0]).toHaveClass("h-12");
      expect(skeletons[0]).toHaveClass("w-12");
      expect(skeletons[0]).toHaveClass("rounded-full");
    });
  });

  describe("Edge Cases", () => {
    it("should handle multiple rerenders with different props", () => {
      const { container, rerender } = render(<Skeleton className="initial" />);

      let el = container.querySelector('[data-slot="skeleton"]');
      expect(el).toHaveClass("initial");

      rerender(<Skeleton className="updated" />);
      el = container.querySelector('[data-slot="skeleton"]');
      expect(el).toHaveClass("updated");

      rerender(<Skeleton className="final" />);
      el = container.querySelector('[data-slot="skeleton"]');
      expect(el).toHaveClass("final");
    });

    it("should preserve data-slot through all prop changes", () => {
      const { container, rerender } = render(<Skeleton id="sk-1" />);

      rerender(<Skeleton className="test" id="sk-2" data-testid="skel" />);

      const el = container.querySelector('[data-slot="skeleton"]');
      expect(el).toHaveAttribute("data-slot", "skeleton");
    });

    it("should handle rapid className changes", () => {
      const { rerender, container } = render(<Skeleton className="class1" />);

      for (let i = 1; i <= 5; i++) {
        rerender(<Skeleton className={`class${i}`} />);
        const el = container.querySelector('[data-slot="skeleton"]');
        expect(el).toHaveClass(`class${i}`);
        expect(el).toHaveClass("animate-pulse");
      }
    });

    it("should handle undefined className prop", () => {
      const { container } = render(<Skeleton className={undefined} />);
      const el = container.querySelector('[data-slot="skeleton"]');

      expect(el).toBeInTheDocument();
      expect(el).toHaveClass("animate-pulse");
    });

    it("should handle whitespace-only className", () => {
      const { container } = render(<Skeleton className="   " />);
      const el = container.querySelector('[data-slot="skeleton"]');

      expect(el).toBeInTheDocument();
      expect(el).toHaveClass("animate-pulse");
    });

    it("should maintain default classes when className is provided", () => {
      const { container } = render(<Skeleton className="h-10 w-10" />);
      const el = container.querySelector('[data-slot="skeleton"]');

      // All default classes should still be present
      expect(el).toHaveClass("animate-pulse");
      expect(el).toHaveClass("rounded-md");
      expect(el).toHaveClass("bg-muted");
      // Plus custom classes
      expect(el).toHaveClass("h-10");
      expect(el).toHaveClass("w-10");
    });
  });

  describe("Size and Layout Customization", () => {
    it("should support custom width", () => {
      const { container } = render(<Skeleton className="w-96" />);
      const el = container.querySelector('[data-slot="skeleton"]');

      expect(el).toHaveClass("w-96");
    });

    it("should support custom height", () => {
      const { container } = render(<Skeleton className="h-64" />);
      const el = container.querySelector('[data-slot="skeleton"]');

      expect(el).toHaveClass("h-64");
    });

    it("should support border radius override", () => {
      const { container } = render(<Skeleton className="rounded-full" />);
      const el = container.querySelector('[data-slot="skeleton"]');

      expect(el).toHaveClass("rounded-full");
    });

    it("should support margin classes", () => {
      const { container } = render(<Skeleton className="mb-4 mt-2" />);
      const el = container.querySelector('[data-slot="skeleton"]');

      expect(el).toHaveClass("mb-4");
      expect(el).toHaveClass("mt-2");
    });

    it("should support padding classes", () => {
      const { container } = render(<Skeleton className="p-4" />);
      const el = container.querySelector('[data-slot="skeleton"]');

      expect(el).toHaveClass("p-4");
    });
  });

  describe("Component Types", () => {
    it("should accept React.ComponentProps<'div'> type", () => {
      const { container } = render(
        <Skeleton id="test" className="custom" data-testid="skeleton" aria-label="test" />,
      );
      const el = container.querySelector('[data-slot="skeleton"]');

      expect(el).toBeInTheDocument();
      expect(el).toHaveAttribute("id", "test");
    });

    it("should work with spread props", () => {
      const props = {
        id: "sk-spread",
        "data-custom": "value",
        className: "spread-class",
      };

      const { container } = render(<Skeleton {...props} />);
      const el = container.querySelector('[data-slot="skeleton"]');

      expect(el).toHaveAttribute("id", "sk-spread");
      expect(el).toHaveAttribute("data-custom", "value");
      expect(el).toHaveClass("spread-class");
    });
  });
});
