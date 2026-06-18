import { describe, it, expect, beforeEach } from "vitest";
import { render } from "@testing-library/react";
import { Badge, badgeVariants } from "./badge";

describe("Badge", () => {
  beforeEach(() => {
    // noop - keep parity with other tests
  });

  describe("Rendering", () => {
    it("should render the badge element with children", () => {
      const { getByText } = render(<Badge>My Badge</Badge>);
      const el = getByText("My Badge");
      expect(el).toBeInTheDocument();
      expect(el.tagName).toBe("DIV");
      expect(document.body.textContent).toContain("My Badge");
    });

    it("should apply default base classes", () => {
      const { getByText } = render(<Badge>Base</Badge>);
      const el = getByText("Base");

      expect(el).toHaveClass("inline-flex");
      expect(el).toHaveClass("rounded-full");
      expect(el).toHaveClass("px-2.5");
      expect(el).toHaveClass("text-xs");
      expect(el).toHaveClass("font-semibold");
    });
  });

  describe("Variants", () => {
    it("should use the default variant when none provided", () => {
      const { getByText } = render(<Badge>Default</Badge>);
      const el = getByText("Default");

      expect(el.className).toContain("bg-primary");
      expect(el.className).toContain("text-primary-foreground");
    });

    it("should include all named variants via badgeVariants", () => {
      const expectations: Record<string, string> = {
        default: "bg-primary",
        secondary: "bg-secondary",
        destructive: "bg-destructive",
        outline: "text-foreground",
        success: "bg-green-100",
        warning: "bg-yellow-100",
        draft: "bg-gray-100",
      };

      for (const [variant, token] of Object.entries(expectations)) {
        const classes = badgeVariants({
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          variant: variant as any,
        });
        expect(classes).toContain(token);
      }
    });

    it("should update classes when rerendering with different variants", () => {
      const { getByText, rerender } = render(<Badge>Toggle</Badge>);
      const el = getByText("Toggle");

      // default
      expect(el.className).toContain("bg-primary");

      // outline
      rerender(<Badge variant="outline">Toggle</Badge>);
      expect(getByText("Toggle").className).toContain("text-foreground");

      // success
      rerender(<Badge variant="success">Toggle</Badge>);
      expect(getByText("Toggle").className).toContain("bg-green-100");

      // destructive
      rerender(<Badge variant="destructive">Toggle</Badge>);
      expect(getByText("Toggle").className).toContain("bg-destructive");
    });
  });

  describe("Class merging & edge cases", () => {
    it("should merge custom className with default classes", () => {
      const { getByText } = render(<Badge className="custom-class">Merged</Badge>);
      const el = getByText("Merged");

      expect(el).toHaveClass("custom-class");
      expect(el).toHaveClass("inline-flex");
      expect(el).toHaveClass("rounded-full");
    });

    it("should handle empty or undefined className without breaking defaults", () => {
      const { getByText } = render(<Badge className="">Empty</Badge>);
      expect(getByText("Empty")).toHaveClass("inline-flex");

      const { getByText: g2 } = render(
        // undefined is allowed by the component props
        <Badge className={undefined}>Undef</Badge>,
      );
      expect(g2("Undef")).toHaveClass("inline-flex");
    });
  });

  describe("Props forwarding and attributes", () => {
    it("should forward standard attributes", () => {
      const { getByText } = render(
        <Badge id="my-badge" title="Badge title">
          Forward
        </Badge>,
      );
      const el = getByText("Forward");

      expect(el).toHaveAttribute("id", "my-badge");
      expect(el).toHaveAttribute("title", "Badge title");
    });

    it("should forward data-* and aria-* attributes", () => {
      const { getByText } = render(
        <Badge data-testid="badge-1" data-custom="x" aria-label="Badge label">
          A11y
        </Badge>,
      );
      const el = getByText("A11y");

      expect(el).toHaveAttribute("data-testid", "badge-1");
      expect(el).toHaveAttribute("data-custom", "x");
      expect(el).toHaveAttribute("aria-label", "Badge label");
    });

    it("should forward style and tabIndex", () => {
      const { getByText } = render(
        <Badge style={{ color: "rgb(0,128,0)" }} tabIndex={0}>
          Styled
        </Badge>,
      );
      const el = getByText("Styled");

      expect(el).toHaveStyle("color: rgb(0, 128, 0)");
      expect(el).toHaveAttribute("tabindex", "0");
    });
  });

  describe("Export & displayName", () => {
    it("should export Badge and have displayName or function name", () => {
      expect(Badge).toBeDefined();
      expect((Badge as any).displayName ?? Badge.name).toBe("Badge");
      expect(typeof Badge).toBe("function");
    });
  });

  describe("Integration & robustness", () => {
    it("should render multiple badges independently", () => {
      const { getByText } = render(
        <div>
          <Badge data-testid="b1">One</Badge>
          <Badge variant="outline" data-testid="b2">
            Two
          </Badge>
        </div>,
      );

      const one = getByText("One");
      const two = getByText("Two");

      expect(one).toBeInTheDocument();
      expect(two).toBeInTheDocument();
      expect(one).toHaveClass("bg-primary");
      expect(two).toHaveClass("text-foreground");
    });

    it("should preserve default classes across rerenders and prop changes", () => {
      const { getByText, rerender } = render(<Badge>Keep</Badge>);
      expect(getByText("Keep")).toHaveClass("inline-flex");

      rerender(<Badge className="added">Keep</Badge>);
      expect(getByText("Keep")).toHaveClass("inline-flex");
      expect(getByText("Keep")).toHaveClass("added");

      rerender(<Badge variant="warning">Keep</Badge>);
      expect(getByText("Keep")).toHaveClass("bg-yellow-100");
      expect(getByText("Keep")).toHaveClass("inline-flex");
    });
  });
});
