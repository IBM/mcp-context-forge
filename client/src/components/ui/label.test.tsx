import { describe, it, expect, beforeEach } from "vitest";
import { render } from "@testing-library/react";
import React from "react";
import { Label } from "./label";

describe("Label", () => {
  beforeEach(() => {
    // Clear state if needed
  });

  describe("Rendering", () => {
    it("should render the label element", () => {
      const { container } = render(<Label>Label text</Label>);
      const el = container.querySelector("label");
      expect(el).toBeInTheDocument();
    });

    it("should render as a label HTML element", () => {
      const { container } = render(<Label>Test</Label>);
      const el = container.querySelector("label");
      expect(el?.tagName).toBe("LABEL");
    });

    it("should render children text content", () => {
      render(<Label>Click me</Label>);
      expect(document.body.textContent).toContain("Click me");
    });

    it("should render with complex children", () => {
      const { container } = render(
        <Label>
          <span>Required</span>
          <span>*</span>
        </Label>,
      );
      const label = container.querySelector("label");
      expect(label).toBeInTheDocument();
      expect(label?.textContent).toContain("Required");
      expect(label?.textContent).toContain("*");
    });
  });

  describe("Display Name", () => {
    it("should have displayName property", () => {
      expect(Label.displayName).toBeDefined();
    });

    it("should have displayName from Root", () => {
      expect(Label.displayName).toBe("Label");
    });
  });

  describe("Default Classes", () => {
    it("should apply default label classes", () => {
      const { container } = render(<Label>Label</Label>);
      const el = container.querySelector("label");

      expect(el).toHaveClass("text-sm");
      expect(el).toHaveClass("font-medium");
      expect(el).toHaveClass("leading-none");
    });

    it("should have peer-disabled styling classes", () => {
      const { container } = render(<Label>Label</Label>);
      const el = container.querySelector("label");

      expect(el).toHaveClass("peer-disabled:cursor-not-allowed");
      expect(el).toHaveClass("peer-disabled:opacity-70");
    });
  });

  describe("Custom ClassName Merging", () => {
    it("should merge custom className with default classes", () => {
      const { container } = render(<Label className="custom-label">Label</Label>);
      const el = container.querySelector("label");

      expect(el).toHaveClass("custom-label");
      expect(el).toHaveClass("text-sm");
      expect(el).toHaveClass("font-medium");
      expect(el).toHaveClass("leading-none");
    });

    it("should merge multiple custom classes with default classes", () => {
      const { container } = render(<Label className="my-label label-custom">Label</Label>);
      const el = container.querySelector("label");

      expect(el).toHaveClass("my-label");
      expect(el).toHaveClass("label-custom");
      expect(el).toHaveClass("text-sm");
      expect(el).toHaveClass("font-medium");
    });

    it("should allow custom className to override default text color", () => {
      const { container } = render(<Label className="text-lg">Label</Label>);
      const el = container.querySelector("label");

      expect(el).toHaveClass("text-lg");
      expect(el?.className).toContain("text-lg");
    });

    it("should allow custom className to override default font weight", () => {
      const { container } = render(<Label className="font-bold">Label</Label>);
      const el = container.querySelector("label");

      expect(el).toHaveClass("font-bold");
    });

    it("should handle empty className", () => {
      const { container } = render(<Label className="">Label</Label>);
      const el = container.querySelector("label");

      expect(el).toBeInTheDocument();
      expect(el).toHaveClass("text-sm");
      expect(el).toHaveClass("font-medium");
    });
  });

  describe("htmlFor Attribute", () => {
    it("should forward htmlFor attribute", () => {
      const { container } = render(<Label htmlFor="username-input">Username</Label>);
      const el = container.querySelector("label");

      expect(el).toHaveAttribute("for", "username-input");
    });

    it("should link to input element via htmlFor", () => {
      const { container } = render(
        <div>
          <Label htmlFor="email-field">Email</Label>
          <input id="email-field" type="email" />
        </div>,
      );

      const label = container.querySelector("label");
      const input = container.querySelector("#email-field");

      expect(label).toHaveAttribute("for", "email-field");
      expect(input).toHaveAttribute("id", "email-field");
    });

    it("should not have htmlFor by default", () => {
      const { container } = render(<Label>Label</Label>);
      const el = container.querySelector("label");

      expect(el).not.toHaveAttribute("for");
    });

    it("should support htmlFor for various input types", () => {
      const { container } = render(
        <div>
          <Label htmlFor="password">Password</Label>
          <input id="password" type="password" />
        </div>,
      );

      const label = container.querySelector("label");
      expect(label).toHaveAttribute("for", "password");
    });
  });

  describe("Props Forwarding", () => {
    it("should forward id prop", () => {
      const { container } = render(<Label id="my-label">Label</Label>);
      const el = container.querySelector("label");

      expect(el).toHaveAttribute("id", "my-label");
    });

    it("should forward title prop", () => {
      const { container } = render(<Label title="Label tooltip">Label</Label>);
      const el = container.querySelector("label");

      expect(el).toHaveAttribute("title", "Label tooltip");
    });

    it("should forward data-testid attribute", () => {
      const { container } = render(<Label data-testid="label-1">Label</Label>);
      const el = container.querySelector("label");

      expect(el).toHaveAttribute("data-testid", "label-1");
    });

    it("should forward custom data-* attributes", () => {
      const { container } = render(
        <Label data-custom="value" data-another="test">
          Label
        </Label>,
      );
      const el = container.querySelector("label");

      expect(el).toHaveAttribute("data-custom", "value");
      expect(el).toHaveAttribute("data-another", "test");
    });

    it("should forward style prop", () => {
      const { container } = render(
        <Label style={{ color: "rgb(255, 0, 0)", fontSize: "16px" }}>Label</Label>,
      );
      const el = container.querySelector("label");

      expect(el).toHaveStyle("color: rgb(255, 0, 0)");
      expect(el).toHaveStyle("font-size: 16px");
    });

    it("should forward tabIndex prop", () => {
      const { container } = render(<Label tabIndex={1}>Label</Label>);
      const el = container.querySelector("label");

      expect(el).toHaveAttribute("tabindex", "1");
    });

    it("should forward aria-* attributes", () => {
      const { container } = render(
        <Label aria-label="Label text" aria-describedby="desc-1">
          Label
        </Label>,
      );
      const el = container.querySelector("label");

      expect(el).toHaveAttribute("aria-label", "Label text");
      expect(el).toHaveAttribute("aria-describedby", "desc-1");
    });

    it("should forward multiple props together", () => {
      const { container } = render(
        <Label
          htmlFor="field-1"
          className="custom"
          id="label-1"
          data-testid="test-label"
          title="Field label"
        >
          Label
        </Label>,
      );
      const el = container.querySelector("label");

      expect(el).toHaveAttribute("for", "field-1");
      expect(el).toHaveClass("custom");
      expect(el).toHaveAttribute("id", "label-1");
      expect(el).toHaveAttribute("data-testid", "test-label");
      expect(el).toHaveAttribute("title", "Field label");
    });

    it("should work with spread props", () => {
      const props = {
        htmlFor: "input-id",
        "data-custom": "value",
        className: "spread-label",
        title: "Spread",
      };

      const { container } = render(<Label {...props}>Label</Label>);
      const el = container.querySelector("label");

      expect(el).toHaveAttribute("for", "input-id");
      expect(el).toHaveAttribute("data-custom", "value");
      expect(el).toHaveClass("spread-label");
      expect(el).toHaveAttribute("title", "Spread");
    });
  });

  describe("Accessibility", () => {
    it("should have proper label semantics", () => {
      const { container } = render(
        <div>
          <Label htmlFor="name-input">Name</Label>
          <input id="name-input" type="text" aria-label="Full name" />
        </div>,
      );

      const label = container.querySelector("label");
      const input = container.querySelector("#name-input");

      expect(label).toHaveAttribute("for", "name-input");
      expect(input).toHaveAttribute("id", "name-input");
    });

    it("should support aria-label on label", () => {
      const { container } = render(<Label aria-label="Accessible label text">Label</Label>);
      const el = container.querySelector("label");

      expect(el).toHaveAttribute("aria-label", "Accessible label text");
    });

    it("should support aria-labelledby", () => {
      const { container } = render(<Label aria-labelledby="title-id">Label</Label>);
      const el = container.querySelector("label");

      expect(el).toHaveAttribute("aria-labelledby", "title-id");
    });

    it("should support aria-describedby", () => {
      const { container } = render(<Label aria-describedby="hint-id">Label</Label>);
      const el = container.querySelector("label");

      expect(el).toHaveAttribute("aria-describedby", "hint-id");
    });

    it("should work with disabled inputs via peer-disabled", () => {
      const { container } = render(
        <div>
          <Label htmlFor="disabled-input">Disabled field</Label>
          <input id="disabled-input" type="text" disabled />
        </div>,
      );

      const label = container.querySelector("label");
      expect(label).toHaveClass("peer-disabled:opacity-70");
    });
  });

  describe("Ref Forwarding", () => {
    it("should forward ref to the underlying label element", () => {
      const ref = React.createRef<HTMLLabelElement>();
      render(<Label ref={ref}>Label</Label>);

      expect(ref.current).toBeInTheDocument();
      expect(ref.current?.tagName).toBe("LABEL");
    });

    it("should allow ref access for DOM manipulation", () => {
      const ref = React.createRef<HTMLLabelElement>();
      render(<Label ref={ref}>Label</Label>);

      expect(ref.current).toBeTruthy();
      expect(ref.current?.classList.contains("text-sm")).toBe(true);
      expect(ref.current?.classList.contains("font-medium")).toBe(true);
    });

    it("should allow ref to get text content", () => {
      const ref = React.createRef<HTMLLabelElement>();
      render(<Label ref={ref}>My Label</Label>);

      expect(ref.current?.textContent).toBe("My Label");
    });

    it("should allow ref to access htmlFor attribute", () => {
      const ref = React.createRef<HTMLLabelElement>();
      render(
        <Label ref={ref} htmlFor="input-1">
          Label
        </Label>,
      );

      expect(ref.current?.getAttribute("for")).toBe("input-1");
    });

    it("should allow ref to access id attribute", () => {
      const ref = React.createRef<HTMLLabelElement>();
      render(
        <Label ref={ref} id="label-1">
          Label
        </Label>,
      );

      expect(ref.current?.getAttribute("id")).toBe("label-1");
    });
  });

  describe("Export", () => {
    it("should export Label component", () => {
      expect(Label).toBeDefined();
      expect(Label.displayName).toBe("Label");
    });
  });

  describe("Integration", () => {
    it("should work in a form context", () => {
      const { container } = render(
        <form>
          <Label htmlFor="email">Email Address</Label>
          <input id="email" type="email" name="email" required />
          <Label htmlFor="password">Password</Label>
          <input id="password" type="password" name="password" required />
        </form>,
      );

      const labels = container.querySelectorAll("label");
      expect(labels).toHaveLength(2);
      expect(labels[0]).toHaveAttribute("for", "email");
      expect(labels[1]).toHaveAttribute("for", "password");
    });

    it("should work with checkbox inputs", () => {
      const { container } = render(
        <div>
          <input id="agree" type="checkbox" />
          <Label htmlFor="agree">I agree to terms</Label>
        </div>,
      );

      const label = container.querySelector("label");
      expect(label).toHaveAttribute("for", "agree");
      expect(label?.textContent).toContain("I agree to terms");
    });

    it("should work with radio inputs", () => {
      const { container } = render(
        <div>
          <input id="option1" type="radio" name="choice" />
          <Label htmlFor="option1">Option 1</Label>
          <input id="option2" type="radio" name="choice" />
          <Label htmlFor="option2">Option 2</Label>
        </div>,
      );

      const labels = container.querySelectorAll("label");
      expect(labels).toHaveLength(2);
      expect(labels[0]).toHaveAttribute("for", "option1");
      expect(labels[1]).toHaveAttribute("for", "option2");
    });

    it("should work with select inputs", () => {
      const { container } = render(
        <div>
          <Label htmlFor="country">Country</Label>
          <select id="country" name="country">
            <option>Select country</option>
          </select>
        </div>,
      );

      const label = container.querySelector("label");
      expect(label).toHaveAttribute("for", "country");
    });

    it("should work with textarea inputs", () => {
      const { container } = render(
        <div>
          <Label htmlFor="comments">Comments</Label>
          <textarea id="comments" name="comments"></textarea>
        </div>,
      );

      const label = container.querySelector("label");
      expect(label).toHaveAttribute("for", "comments");
    });

    it("should render multiple labels independently", () => {
      const { container } = render(
        <div>
          <Label htmlFor="field1" data-testid="label-1">
            Field 1
          </Label>
          <Label htmlFor="field2" data-testid="label-2">
            Field 2
          </Label>
          <Label htmlFor="field3" data-testid="label-3">
            Field 3
          </Label>
        </div>,
      );

      const labels = container.querySelectorAll("label");
      expect(labels).toHaveLength(3);
    });
  });

  describe("Edge Cases", () => {
    it("should handle undefined className", () => {
      const { container } = render(<Label className={undefined}>Label</Label>);
      const el = container.querySelector("label");

      expect(el).toBeInTheDocument();
      expect(el).toHaveClass("text-sm");
    });

    it("should handle whitespace-only className", () => {
      const { container } = render(<Label className="   ">Label</Label>);
      const el = container.querySelector("label");

      expect(el).toBeInTheDocument();
      expect(el).toHaveClass("text-sm");
    });

    it("should handle empty children", () => {
      const { container } = render(<Label></Label>);
      const el = container.querySelector("label");

      expect(el).toBeInTheDocument();
      expect(el?.textContent).toBe("");
    });

    it("should maintain default classes when custom classes are added", () => {
      const { container } = render(<Label className="custom">Label</Label>);
      const el = container.querySelector("label");

      expect(el).toHaveClass("text-sm");
      expect(el).toHaveClass("font-medium");
      expect(el).toHaveClass("leading-none");
      expect(el).toHaveClass("custom");
    });

    it("should handle multiple rerenders with different props", () => {
      const { rerender, container } = render(<Label htmlFor="field1">Label 1</Label>);

      let el = container.querySelector("label");
      expect(el).toHaveAttribute("for", "field1");

      rerender(<Label htmlFor="field2">Label 2</Label>);
      el = container.querySelector("label");
      expect(el).toHaveAttribute("for", "field2");

      rerender(<Label htmlFor="field3">Label 3</Label>);
      el = container.querySelector("label");
      expect(el).toHaveAttribute("for", "field3");
    });

    it("should handle changing className", () => {
      const { rerender, container } = render(<Label className="initial">Label</Label>);

      let el = container.querySelector("label");
      expect(el).toHaveClass("initial");

      rerender(<Label className="updated">Label</Label>);
      el = container.querySelector("label");
      expect(el).toHaveClass("updated");
    });

    it("should handle changing children", () => {
      const { rerender, container } = render(<Label>Text 1</Label>);

      let el = container.querySelector("label");
      expect(el?.textContent).toBe("Text 1");

      rerender(<Label>Text 2</Label>);
      el = container.querySelector("label");
      expect(el?.textContent).toBe("Text 2");

      rerender(<Label>Text 3</Label>);
      el = container.querySelector("label");
      expect(el?.textContent).toBe("Text 3");
    });

    it("should preserve default classes through all rerenders", () => {
      const { rerender, container } = render(<Label htmlFor="f1">Label</Label>);

      rerender(
        <Label htmlFor="f2" className="custom">
          Label
        </Label>,
      );

      const el = container.querySelector("label");
      expect(el).toHaveClass("text-sm");
      expect(el).toHaveClass("font-medium");
      expect(el).toHaveClass("leading-none");
      expect(el).toHaveClass("custom");
    });

    it("should handle rapid prop changes", () => {
      const { rerender, container } = render(<Label htmlFor="f1">Label</Label>);

      for (let i = 2; i <= 5; i++) {
        rerender(<Label htmlFor={`f${i}`}>Label</Label>);
        const el = container.querySelector("label");
        expect(el).toHaveAttribute("for", `f${i}`);
      }
    });
  });

  describe("Component Types", () => {
    it("should accept Radix UI label props", () => {
      const { container } = render(
        <Label htmlFor="test" className="custom" id="label-id" data-testid="label" title="test">
          Label
        </Label>,
      );
      const el = container.querySelector("label");

      expect(el).toBeInTheDocument();
      expect(el).toHaveAttribute("for", "test");
    });
  });
});
