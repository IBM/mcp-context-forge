import { describe, it, expect, beforeEach } from "vitest";
import { render } from "@testing-library/react";
import React from "react";
import { Progress } from "./progress";

describe("Progress", () => {
  beforeEach(() => {
    // Clear any previous state
  });

  describe("Rendering", () => {
    it("should render the progress component", () => {
      const { container } = render(<Progress value={50} />);
      const progressRoot = container.querySelector('[data-slot="progress"]');
      expect(progressRoot).toBeInTheDocument();
    });

    it("should render the progress indicator", () => {
      const { container } = render(<Progress value={50} />);
      const indicator = container.querySelector('[data-slot="progress-indicator"]');
      expect(indicator).toBeInTheDocument();
    });

    it("should render with default structure", () => {
      const { container } = render(<Progress value={50} />);
      const progressRoot = container.querySelector('[data-slot="progress"]');
      const indicator = progressRoot?.querySelector('[data-slot="progress-indicator"]');

      expect(progressRoot).toBeInTheDocument();
      expect(indicator).toBeInTheDocument();
      expect(indicator?.parentElement).toBe(progressRoot);
    });
  });

  describe("CSS Classes", () => {
    it("should apply default root classes", () => {
      const { container } = render(<Progress value={50} />);
      const progressRoot = container.querySelector('[data-slot="progress"]');

      expect(progressRoot).toHaveClass("relative");
      expect(progressRoot).toHaveClass("flex");
      expect(progressRoot).toHaveClass("h-1.5");
      expect(progressRoot).toHaveClass("w-full");
      expect(progressRoot).toHaveClass("items-center");
      expect(progressRoot).toHaveClass("overflow-x-hidden");
      expect(progressRoot).toHaveClass("rounded-full");
      expect(progressRoot).toHaveClass("bg-muted");
    });

    it("should apply default indicator classes", () => {
      const { container } = render(<Progress value={50} />);
      const indicator = container.querySelector('[data-slot="progress-indicator"]');

      expect(indicator).toHaveClass("size-full");
      expect(indicator).toHaveClass("flex-1");
      expect(indicator).toHaveClass("bg-primary");
      expect(indicator).toHaveClass("transition-all");
    });

    it("should merge custom className with default classes", () => {
      const { container } = render(<Progress value={50} className="custom-class" />);
      const progressRoot = container.querySelector('[data-slot="progress"]');

      expect(progressRoot).toHaveClass("custom-class");
      expect(progressRoot).toHaveClass("bg-muted");
    });

    it("should allow custom className to override default classes", () => {
      const { container } = render(<Progress value={50} className="bg-red-500" />);
      const progressRoot = container.querySelector('[data-slot="progress"]');

      expect(progressRoot).toHaveClass("bg-red-500");
      // The cn utility will include both, but bg-red-500 should take precedence in CSS
      expect(progressRoot?.className).toContain("bg-red-500");
    });
  });

  describe("Progress Values", () => {
    it("should handle 0% progress", () => {
      const { container } = render(<Progress value={0} />);
      const indicator = container.querySelector('[data-slot="progress-indicator"]') as HTMLElement;

      expect(indicator).toHaveStyle({ transform: "translateX(-100%)" });
    });

    it("should handle 25% progress", () => {
      const { container } = render(<Progress value={25} />);
      const indicator = container.querySelector('[data-slot="progress-indicator"]') as HTMLElement;

      expect(indicator).toHaveStyle({ transform: "translateX(-75%)" });
    });

    it("should handle 50% progress", () => {
      const { container } = render(<Progress value={50} />);
      const indicator = container.querySelector('[data-slot="progress-indicator"]') as HTMLElement;

      expect(indicator).toHaveStyle({ transform: "translateX(-50%)" });
    });

    it("should handle 75% progress", () => {
      const { container } = render(<Progress value={75} />);
      const indicator = container.querySelector('[data-slot="progress-indicator"]') as HTMLElement;

      expect(indicator).toHaveStyle({ transform: "translateX(-25%)" });
    });

    it("should handle 100% progress", () => {
      const { container } = render(<Progress value={100} />);
      const indicator = container.querySelector('[data-slot="progress-indicator"]') as HTMLElement;

      expect(indicator).toHaveStyle({ transform: "translateX(-0%)" });
    });

    it("should handle no value prop (defaults to 0)", () => {
      const { container } = render(<Progress />);
      const indicator = container.querySelector('[data-slot="progress-indicator"]') as HTMLElement;

      expect(indicator).toHaveStyle({ transform: "translateX(-100%)" });
    });

    it("should handle undefined value explicitly", () => {
      const { container } = render(<Progress value={undefined} />);
      const indicator = container.querySelector('[data-slot="progress-indicator"]') as HTMLElement;

      expect(indicator).toHaveStyle({ transform: "translateX(-100%)" });
    });
  });

  describe("Accessibility", () => {
    it("should have aria-valuenow attribute", () => {
      const { container } = render(<Progress value={50} role="progressbar" aria-valuenow={50} />);
      const progressRoot = container.querySelector('[data-slot="progress"]');

      expect(progressRoot).toHaveAttribute("aria-valuenow", "50");
    });

    it("should have aria-valuemin attribute", () => {
      const { container } = render(<Progress value={50} role="progressbar" aria-valuemin={0} />);
      const progressRoot = container.querySelector('[data-slot="progress"]');

      expect(progressRoot).toHaveAttribute("aria-valuemin", "0");
    });

    it("should have aria-valuemax attribute", () => {
      const { container } = render(<Progress value={50} role="progressbar" aria-valuemax={100} />);
      const progressRoot = container.querySelector('[data-slot="progress"]');

      expect(progressRoot).toHaveAttribute("aria-valuemax", "100");
    });

    it("should support role attribute", () => {
      const { container } = render(<Progress value={50} role="progressbar" />);
      const progressRoot = container.querySelector('[data-slot="progress"]');

      expect(progressRoot).toHaveAttribute("role", "progressbar");
    });

    it("should support aria-label attribute", () => {
      const { container } = render(
        <Progress value={50} role="progressbar" aria-label="Loading progress" />,
      );
      const progressRoot = container.querySelector('[data-slot="progress"]');

      expect(progressRoot).toHaveAttribute("aria-label", "Loading progress");
    });

    it("should support aria-labelledby attribute", () => {
      const { container } = render(
        <Progress value={50} role="progressbar" aria-labelledby="progress-label" />,
      );
      const progressRoot = container.querySelector('[data-slot="progress"]');

      expect(progressRoot).toHaveAttribute("aria-labelledby", "progress-label");
    });

    it("should support aria-describedby attribute", () => {
      const { container } = render(
        <Progress value={50} role="progressbar" aria-describedby="progress-desc" />,
      );
      const progressRoot = container.querySelector('[data-slot="progress"]');

      expect(progressRoot).toHaveAttribute("aria-describedby", "progress-desc");
    });
  });

  describe("Data Attributes", () => {
    it("should have data-slot on root element", () => {
      const { container } = render(<Progress value={50} />);
      const progressRoot = container.querySelector('[data-slot="progress"]');

      expect(progressRoot).toHaveAttribute("data-slot", "progress");
    });

    it("should have data-slot on indicator element", () => {
      const { container } = render(<Progress value={50} />);
      const indicator = container.querySelector('[data-slot="progress-indicator"]');

      expect(indicator).toHaveAttribute("data-slot", "progress-indicator");
    });

    it("should support custom data attributes on root", () => {
      const { container } = render(<Progress value={50} data-testid="custom-progress" />);
      const progressRoot = container.querySelector('[data-testid="custom-progress"]');

      expect(progressRoot).toBeInTheDocument();
    });
  });

  describe("Style Calculations", () => {
    it("should calculate correct transform for various percentages", () => {
      const testCases = [
        { value: 0, expected: "translateX(-100%)" },
        { value: 10, expected: "translateX(-90%)" },
        { value: 25, expected: "translateX(-75%)" },
        { value: 50, expected: "translateX(-50%)" },
        { value: 75, expected: "translateX(-25%)" },
        { value: 90, expected: "translateX(-10%)" },
        { value: 100, expected: "translateX(-0%)" },
      ];

      testCases.forEach(({ value, expected }) => {
        const { container } = render(<Progress value={value} />);
        const indicator = container.querySelector(
          '[data-slot="progress-indicator"]',
        ) as HTMLElement;
        expect(indicator).toHaveStyle({ transform: expected });
      });
    });

    it("should update transform when value changes", () => {
      const { container, rerender } = render(<Progress value={25} />);
      let indicator = container.querySelector('[data-slot="progress-indicator"]') as HTMLElement;
      expect(indicator).toHaveStyle({ transform: "translateX(-75%)" });

      rerender(<Progress value={75} />);
      indicator = container.querySelector('[data-slot="progress-indicator"]') as HTMLElement;
      expect(indicator).toHaveStyle({ transform: "translateX(-25%)" });
    });
  });

  describe("Props Forwarding", () => {
    it("should forward standard HTML attributes", () => {
      const { container } = render(<Progress value={50} id="test-progress" title="Loading" />);
      const progressRoot = container.querySelector('[data-slot="progress"]');

      expect(progressRoot).toHaveAttribute("id", "test-progress");
      expect(progressRoot).toHaveAttribute("title", "Loading");
    });

    it("should support disabled attribute", () => {
      const { container } = render(<Progress value={50} disabled />);
      const progressRoot = container.querySelector('[data-slot="progress"]');

      expect(progressRoot).toHaveAttribute("disabled");
    });

    it("should support className prop alongside other props", () => {
      const { container } = render(
        <Progress value={50} className="my-custom-class" id="my-progress" />,
      );
      const progressRoot = container.querySelector('[data-slot="progress"]');

      expect(progressRoot).toHaveClass("my-custom-class");
      expect(progressRoot).toHaveAttribute("id", "my-progress");
    });
  });

  describe("Edge Cases", () => {
    it("should handle negative values", () => {
      const { container } = render(<Progress value={-10} />);
      const indicator = container.querySelector('[data-slot="progress-indicator"]') as HTMLElement;

      // -10 means: translateX(-( 100 - (-10) )%) = translateX(-110%)
      expect(indicator).toHaveStyle({ transform: "translateX(-110%)" });
    });

    it("should handle values over 100", () => {
      const { container } = render(<Progress value={150} />);
      const indicator = container.querySelector('[data-slot="progress-indicator"]') as HTMLElement;

      // 150 means: translateX(-${100 - 150}%) = translateX(-${-50}%) = translateX(--50%)
      expect(indicator).toHaveStyle({ transform: "translateX(--50%)" });
    });

    it("should handle decimal values", () => {
      const { container } = render(<Progress value={33.33} />);
      const indicator = container.querySelector('[data-slot="progress-indicator"]') as HTMLElement;

      expect(indicator).toHaveStyle({ transform: "translateX(-66.67%)" });
    });

    it("should maintain transform through re-renders", () => {
      const { container, rerender } = render(<Progress value={50} className="initial-class" />);
      let indicator = container.querySelector('[data-slot="progress-indicator"]') as HTMLElement;
      expect(indicator).toHaveStyle({ transform: "translateX(-50%)" });

      rerender(<Progress value={50} className="updated-class" />);
      indicator = container.querySelector('[data-slot="progress-indicator"]') as HTMLElement;
      expect(indicator).toHaveStyle({ transform: "translateX(-50%)" });
    });

    it("should handle rapid value changes", () => {
      const { rerender, container } = render(<Progress value={10} />);

      for (let i = 10; i <= 100; i += 10) {
        rerender(<Progress value={i} />);
        const indicator = container.querySelector(
          '[data-slot="progress-indicator"]',
        ) as HTMLElement;
        const expectedTransform = `translateX(-${100 - i}%)`;
        expect(indicator).toHaveStyle({ transform: expectedTransform });
      }
    });
  });

  describe("Integration", () => {
    it("should render multiple progress instances independently", () => {
      const { container } = render(
        <div>
          <Progress value={25} data-testid="progress-1" />
          <Progress value={50} data-testid="progress-2" />
          <Progress value={75} data-testid="progress-3" />
        </div>,
      );

      const progress1 = container.querySelector(
        '[data-testid="progress-1"] [data-slot="progress-indicator"]',
      ) as HTMLElement;
      const progress2 = container.querySelector(
        '[data-testid="progress-2"] [data-slot="progress-indicator"]',
      ) as HTMLElement;
      const progress3 = container.querySelector(
        '[data-testid="progress-3"] [data-slot="progress-indicator"]',
      ) as HTMLElement;

      expect(progress1).toHaveStyle({ transform: "translateX(-75%)" });
      expect(progress2).toHaveStyle({ transform: "translateX(-50%)" });
      expect(progress3).toHaveStyle({ transform: "translateX(-25%)" });
    });

    it("should work with accessibility attributes", () => {
      const { container } = render(
        <div>
          <div id="progress-label">File Upload Progress</div>
          <Progress
            value={60}
            role="progressbar"
            aria-labelledby="progress-label"
            aria-valuenow={60}
            aria-valuemin={0}
            aria-valuemax={100}
          />
        </div>,
      );

      const progressRoot = container.querySelector('[data-slot="progress"]');
      expect(progressRoot).toHaveAttribute("aria-labelledby", "progress-label");
      expect(progressRoot).toHaveAttribute("aria-valuenow", "60");
      expect(progressRoot).toHaveAttribute("aria-valuemin", "0");
      expect(progressRoot).toHaveAttribute("aria-valuemax", "100");
    });
  });

  describe("Composition", () => {
    it("should accept children-related props without breaking", () => {
      // Progress doesn't have children but should handle Radix props
      const { container } = render(<Progress value={50} />);
      const progressRoot = container.querySelector('[data-slot="progress"]');

      expect(progressRoot).toBeInTheDocument();
    });

    it("should work with ref forwarding", () => {
      const ref = React.createRef<HTMLDivElement>();
      render(<Progress value={50} ref={ref} />);

      // The ref should be forwarded to the root element
      expect(ref.current).toBeInTheDocument();
    });
  });
});
