import { describe, it, expect, beforeEach } from "vitest";
import { render } from "@testing-library/react";
import React from "react";
import { Separator } from "./separator";

describe("Separator", () => {
  beforeEach(() => {
    // Clear state if needed
  });

  describe("Rendering", () => {
    it("should render the separator element", () => {
      const { container } = render(<Separator />);
      const el = container.querySelector('[data-slot="separator"]');
      expect(el).toBeInTheDocument();
    });

    it("should have data-slot attribute set to separator", () => {
      const { container } = render(<Separator />);
      const el = container.querySelector('[data-slot="separator"]');
      expect(el).toHaveAttribute("data-slot", "separator");
    });

    it("should render with default horizontal orientation", () => {
      const { container } = render(<Separator />);
      const el = container.querySelector('[data-slot="separator"]');
      expect(el).toBeInTheDocument();
      expect(el).toHaveAttribute("data-orientation", "horizontal");
    });
  });

  describe("Styling", () => {
    it("should apply default separator classes", () => {
      const { container } = render(<Separator />);
      const el = container.querySelector('[data-slot="separator"]');

      expect(el).toHaveClass("shrink-0");
      expect(el).toHaveClass("bg-border");
    });

    it("should apply horizontal-specific classes by default", () => {
      const { container } = render(<Separator orientation="horizontal" />);
      const el = container.querySelector('[data-slot="separator"]');

      expect(el).toHaveClass("data-horizontal:h-px");
      expect(el).toHaveClass("data-horizontal:w-full");
    });

    it("should apply vertical-specific classes when orientation is vertical", () => {
      const { container } = render(<Separator orientation="vertical" />);
      const el = container.querySelector('[data-slot="separator"]');

      expect(el).toHaveClass("data-vertical:w-px");
      expect(el).toHaveClass("data-vertical:self-stretch");
    });

    it("should merge custom className with default classes", () => {
      const { container } = render(<Separator className="custom-class" />);
      const el = container.querySelector('[data-slot="separator"]');

      expect(el).toHaveClass("custom-class");
      expect(el).toHaveClass("bg-border");
      expect(el).toHaveClass("shrink-0");
    });

    it("should allow custom className to be combined with multiple default classes", () => {
      const { container } = render(<Separator className="my-custom-separator custom-styling" />);
      const el = container.querySelector('[data-slot="separator"]');

      expect(el).toHaveClass("my-custom-separator");
      expect(el).toHaveClass("custom-styling");
      expect(el).toHaveClass("bg-border");
    });
  });

  describe("Orientation: Horizontal", () => {
    it("should render as horizontal by default", () => {
      const { container } = render(<Separator />);
      const el = container.querySelector('[data-slot="separator"]');

      expect(el).toHaveAttribute("data-orientation", "horizontal");
    });

    it("should render as horizontal when explicitly set", () => {
      const { container } = render(<Separator orientation="horizontal" />);
      const el = container.querySelector('[data-slot="separator"]');

      expect(el).toHaveAttribute("data-orientation", "horizontal");
    });

    it("should have horizontal height classes", () => {
      const { container } = render(<Separator orientation="horizontal" />);
      const el = container.querySelector('[data-slot="separator"]');

      expect(el).toHaveClass("data-horizontal:h-px");
    });

    it("should have horizontal width classes", () => {
      const { container } = render(<Separator orientation="horizontal" />);
      const el = container.querySelector('[data-slot="separator"]');

      expect(el).toHaveClass("data-horizontal:w-full");
    });
  });

  describe("Orientation: Vertical", () => {
    it("should render as vertical when explicitly set", () => {
      const { container } = render(<Separator orientation="vertical" />);
      const el = container.querySelector('[data-slot="separator"]');

      expect(el).toHaveAttribute("data-orientation", "vertical");
    });

    it("should have vertical width classes", () => {
      const { container } = render(<Separator orientation="vertical" />);
      const el = container.querySelector('[data-slot="separator"]');

      expect(el).toHaveClass("data-vertical:w-px");
    });

    it("should have vertical self-stretch classes", () => {
      const { container } = render(<Separator orientation="vertical" />);
      const el = container.querySelector('[data-slot="separator"]');

      expect(el).toHaveClass("data-vertical:self-stretch");
    });
  });

  describe("Accessibility", () => {
    it("should be decorative by default", () => {
      const { container } = render(<Separator />);
      const el = container.querySelector('[data-slot="separator"]');

      expect(el).toHaveAttribute("role", "none");
    });

    it("should have role=none when decorative=true", () => {
      const { container } = render(<Separator decorative={true} />);
      const el = container.querySelector('[data-slot="separator"]');

      expect(el).toHaveAttribute("role", "none");
    });

    it("should have role=separator when decorative=false", () => {
      const { container } = render(<Separator decorative={false} />);
      const el = container.querySelector('[data-slot="separator"]');

      expect(el).toHaveAttribute("role", "separator");
    });

    it("should support custom aria-label", () => {
      const { container } = render(<Separator aria-label="Section divider" decorative={false} />);
      const el = container.querySelector('[data-slot="separator"]');

      expect(el).toHaveAttribute("aria-label", "Section divider");
    });

    it("should support aria-labelledby", () => {
      const { container } = render(<Separator aria-labelledby="sep-label" decorative={false} />);
      const el = container.querySelector('[data-slot="separator"]');

      expect(el).toHaveAttribute("aria-labelledby", "sep-label");
    });
  });

  describe("Props Forwarding", () => {
    it("should forward standard HTML attributes", () => {
      const { container } = render(<Separator id="my-separator" title="A separator" />);
      const el = container.querySelector('[data-slot="separator"]');

      expect(el).toHaveAttribute("id", "my-separator");
      expect(el).toHaveAttribute("title", "A separator");
    });

    it("should forward data-* attributes", () => {
      const { container } = render(<Separator data-testid="sep-1" data-custom="value" />);
      const el = container.querySelector('[data-slot="separator"]');

      expect(el).toHaveAttribute("data-testid", "sep-1");
      expect(el).toHaveAttribute("data-custom", "value");
    });

    it("should forward aria-* attributes", () => {
      const { container } = render(
        <Separator aria-label="Divider" aria-describedby="desc-1" decorative={false} />,
      );
      const el = container.querySelector('[data-slot="separator"]');

      expect(el).toHaveAttribute("aria-label", "Divider");
      expect(el).toHaveAttribute("aria-describedby", "desc-1");
    });

    it("should forward className along with other props", () => {
      const { container } = render(
        <Separator className="custom-sep" id="sep-2" data-testid="sep-test" />,
      );
      const el = container.querySelector('[data-slot="separator"]');

      expect(el).toHaveClass("custom-sep");
      expect(el).toHaveAttribute("id", "sep-2");
      expect(el).toHaveAttribute("data-testid", "sep-test");
    });

    it("should accept all Radix Root props", () => {
      const { container } = render(
        <Separator orientation="vertical" decorative={false} className="my-sep" />,
      );
      const el = container.querySelector('[data-slot="separator"]');

      expect(el).toHaveAttribute("data-orientation", "vertical");
      expect(el).toHaveAttribute("role", "separator");
      expect(el).toHaveClass("my-sep");
    });
  });

  describe("Ref Forwarding", () => {
    it("should forward ref to the underlying element", () => {
      const ref = React.createRef<HTMLDivElement>();
      render(<Separator ref={ref} />);

      expect(ref.current).toBeInTheDocument();
      expect(ref.current).toHaveAttribute("data-slot", "separator");
    });

    it("should allow ref access for DOM manipulation", () => {
      const ref = React.createRef<HTMLDivElement>();
      render(<Separator ref={ref} />);

      expect(ref.current).toBeTruthy();
      expect(ref.current?.classList.contains("bg-border")).toBe(true);
    });
  });

  describe("Export", () => {
    it("should export Separator component", () => {
      expect(Separator).toBeDefined();
      expect(typeof Separator).toBe("function");
    });
  });

  describe("Integration", () => {
    it("should render multiple separators independently", () => {
      const { container } = render(
        <div>
          <div>Section 1</div>
          <Separator />
          <div>Section 2</div>
          <Separator orientation="vertical" />
          <div>Section 3</div>
        </div>,
      );

      const separators = container.querySelectorAll('[data-slot="separator"]');
      expect(separators).toHaveLength(2);
      expect(separators[0]).toHaveAttribute("data-orientation", "horizontal");
      expect(separators[1]).toHaveAttribute("data-orientation", "vertical");
    });

    it("should work as a semantic separator when decorative=false", () => {
      const { container } = render(
        <div>
          <h2>Title</h2>
          <Separator decorative={false} />
          <p>Content</p>
        </div>,
      );

      const separator = container.querySelector('[data-slot="separator"]');
      expect(separator).toHaveAttribute("role", "separator");
    });

    it("should work as a decorative separator by default", () => {
      const { container } = render(
        <div>
          <h2>Title</h2>
          <Separator />
          <p>Content</p>
        </div>,
      );

      const separator = container.querySelector('[data-slot="separator"]');
      expect(separator).toHaveAttribute("role", "none");
    });

    it("should combine orientation, decorative, and className", () => {
      const { container } = render(
        <Separator orientation="vertical" decorative={false} className="my-divider" />,
      );

      const el = container.querySelector('[data-slot="separator"]');
      expect(el).toHaveAttribute("data-orientation", "vertical");
      expect(el).toHaveAttribute("role", "separator");
      expect(el).toHaveClass("my-divider");
      expect(el).toHaveClass("data-vertical:w-px");
    });
  });

  describe("Edge Cases", () => {
    it("should handle empty className", () => {
      const { container } = render(<Separator className="" />);
      const el = container.querySelector('[data-slot="separator"]');

      expect(el).toBeInTheDocument();
      expect(el).toHaveClass("bg-border");
    });

    it("should handle multiple rerenders with different props", () => {
      const { container, rerender } = render(<Separator orientation="horizontal" />);

      let el = container.querySelector('[data-slot="separator"]');
      expect(el).toHaveAttribute("data-orientation", "horizontal");

      rerender(<Separator orientation="vertical" />);
      el = container.querySelector('[data-slot="separator"]');
      expect(el).toHaveAttribute("data-orientation", "vertical");

      rerender(<Separator orientation="horizontal" />);
      el = container.querySelector('[data-slot="separator"]');
      expect(el).toHaveAttribute("data-orientation", "horizontal");
    });

    it("should handle changing decorative state", () => {
      const { container, rerender } = render(<Separator decorative={true} />);

      let el = container.querySelector('[data-slot="separator"]');
      expect(el).toHaveAttribute("role", "none");

      rerender(<Separator decorative={false} />);
      el = container.querySelector('[data-slot="separator"]');
      expect(el).toHaveAttribute("role", "separator");
    });

    it("should handle changing className", () => {
      const { container, rerender } = render(<Separator className="initial" />);

      let el = container.querySelector('[data-slot="separator"]');
      expect(el).toHaveClass("initial");

      rerender(<Separator className="updated" />);
      el = container.querySelector('[data-slot="separator"]');
      expect(el).toHaveClass("updated");
    });

    it("should preserve data-slot through all prop changes", () => {
      const { container, rerender } = render(<Separator orientation="horizontal" />);

      rerender(<Separator orientation="vertical" decorative={false} className="test" />);

      const el = container.querySelector('[data-slot="separator"]');
      expect(el).toHaveAttribute("data-slot", "separator");
    });
  });
});
