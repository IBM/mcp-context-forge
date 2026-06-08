import { describe, it, expect, beforeEach } from "vitest";
import { render } from "@testing-library/react";
import React from "react";
import { Input } from "./input";

describe("Input", () => {
  beforeEach(() => {
    // Clear state if needed
  });

  describe("Rendering", () => {
    it("should render the input element", () => {
      const { container } = render(<Input />);
      const el = container.querySelector('input[data-slot="input"]');
      expect(el).toBeInTheDocument();
    });

    it("should render as an input HTML element", () => {
      const { container } = render(<Input />);
      const el = container.querySelector('input[data-slot="input"]');
      expect(el?.tagName).toBe("INPUT");
    });

    it("should have data-slot attribute set to input", () => {
      const { container } = render(<Input />);
      const el = container.querySelector('input[data-slot="input"]');
      expect(el).toHaveAttribute("data-slot", "input");
    });

    it("should have displayName property", () => {
      expect(Input.displayName).toBe("Input");
    });
  });

  describe("Default Classes", () => {
    it("should apply default input classes", () => {
      const { container } = render(<Input />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveClass("h-9");
      expect(el).toHaveClass("w-full");
      expect(el).toHaveClass("min-w-0");
      expect(el).toHaveClass("rounded-md");
      expect(el).toHaveClass("border");
      expect(el).toHaveClass("border-input");
      expect(el).toHaveClass("bg-transparent");
      expect(el).toHaveClass("px-2.5");
      expect(el).toHaveClass("py-1");
      expect(el).toHaveClass("text-base");
      expect(el).toHaveClass("shadow-xs");
    });

    it("should have outline-none class", () => {
      const { container } = render(<Input />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveClass("outline-none");
    });

    it("should have transition class", () => {
      const { container } = render(<Input />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveClass("transition-[color,box-shadow]");
    });

    it("should have focus-visible classes", () => {
      const { container } = render(<Input />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveClass("focus-visible:border-ring");
      expect(el).toHaveClass("focus-visible:ring-3");
      expect(el).toHaveClass("focus-visible:ring-ring/50");
    });

    it("should have placeholder text color", () => {
      const { container } = render(<Input />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveClass("placeholder:text-muted-foreground");
    });

    it("should have file input styling", () => {
      const { container } = render(<Input type="file" />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveClass("file:inline-flex");
      expect(el).toHaveClass("file:h-7");
      expect(el).toHaveClass("file:border-0");
      expect(el).toHaveClass("file:bg-transparent");
      expect(el).toHaveClass("file:text-sm");
      expect(el).toHaveClass("file:font-medium");
      expect(el).toHaveClass("file:text-foreground");
    });
  });

  describe("Custom ClassName Merging", () => {
    it("should merge custom className with default classes", () => {
      const { container } = render(<Input className="custom-class" />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveClass("custom-class");
      expect(el).toHaveClass("h-9");
      expect(el).toHaveClass("w-full");
      expect(el).toHaveClass("border");
    });

    it("should merge multiple custom classes with default classes", () => {
      const { container } = render(<Input className="my-input custom-styling" />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveClass("my-input");
      expect(el).toHaveClass("custom-styling");
      expect(el).toHaveClass("h-9");
      expect(el).toHaveClass("bg-transparent");
    });

    it("should allow custom className to override default bg color", () => {
      const { container } = render(<Input className="bg-red-500" />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveClass("bg-red-500");
      expect(el?.className).toContain("bg-red-500");
    });

    it("should allow custom className to override border color", () => {
      const { container } = render(<Input className="border-blue-500" />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveClass("border-blue-500");
    });

    it("should handle empty className", () => {
      const { container } = render(<Input className="" />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toBeInTheDocument();
      expect(el).toHaveClass("h-9");
      expect(el).toHaveClass("border");
    });
  });

  describe("Input Type", () => {
    it("should support type=password", () => {
      const { container } = render(<Input type="password" />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveAttribute("type", "password");
    });

    it("should support type=email", () => {
      const { container } = render(<Input type="email" />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveAttribute("type", "email");
    });

    it("should support type=number", () => {
      const { container } = render(<Input type="number" />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveAttribute("type", "number");
    });

    it("should support type=file", () => {
      const { container } = render(<Input type="file" />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveAttribute("type", "file");
    });

    it("should support type=date", () => {
      const { container } = render(<Input type="date" />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveAttribute("type", "date");
    });

    it("should support type=checkbox", () => {
      const { container } = render(<Input type="checkbox" />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveAttribute("type", "checkbox");
    });

    it("should support type=radio", () => {
      const { container } = render(<Input type="radio" />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveAttribute("type", "radio");
    });

    it("should support type=range", () => {
      const { container } = render(<Input type="range" />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveAttribute("type", "range");
    });
  });

  describe("Props Forwarding", () => {
    it("should forward standard HTML attributes", () => {
      const { container } = render(<Input id="my-input" title="Input field" />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveAttribute("id", "my-input");
      expect(el).toHaveAttribute("title", "Input field");
    });

    it("should forward data-* attributes", () => {
      const { container } = render(<Input data-testid="input-1" data-custom="value" />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveAttribute("data-testid", "input-1");
      expect(el).toHaveAttribute("data-custom", "value");
    });

    it("should forward placeholder prop", () => {
      const { container } = render(<Input placeholder="Enter text" />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveAttribute("placeholder", "Enter text");
    });

    it("should forward value prop", () => {
      const { container } = render(<Input value="initial value" readOnly />);
      const el = container.querySelector('input[data-slot="input"]') as HTMLInputElement;

      expect(el).toHaveValue("initial value");
    });

    it("should forward name prop", () => {
      const { container } = render(<Input name="username" />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveAttribute("name", "username");
    });

    it("should forward className along with other props", () => {
      const { container } = render(
        <Input
          className="custom-input"
          id="inp-2"
          data-testid="test-inp"
          placeholder="Type here"
        />,
      );
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveClass("custom-input");
      expect(el).toHaveAttribute("id", "inp-2");
      expect(el).toHaveAttribute("data-testid", "test-inp");
      expect(el).toHaveAttribute("placeholder", "Type here");
    });

    it("should forward style prop", () => {
      const { container } = render(
        <Input style={{ backgroundColor: "rgb(255, 0, 0)", fontSize: "14px" }} />,
      );
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveStyle("background-color: rgb(255, 0, 0)");
      expect(el).toHaveStyle("font-size: 14px");
    });

    it("should forward aria-* attributes", () => {
      const { container } = render(
        <Input aria-label="Email input" aria-describedby="email-help" />,
      );
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveAttribute("aria-label", "Email input");
      expect(el).toHaveAttribute("aria-describedby", "email-help");
    });

    it("should forward multiple standard div attributes", () => {
      const { container } = render(
        <Input id="inp1" title="Input" data-testid="test-inp" tabIndex={0} />,
      );
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveAttribute("id", "inp1");
      expect(el).toHaveAttribute("title", "Input");
      expect(el).toHaveAttribute("data-testid", "test-inp");
      expect(el).toHaveAttribute("tabIndex", "0");
    });

    it("should work with spread props", () => {
      const props = {
        id: "spread-input",
        "data-custom": "value",
        className: "spread-class",
        placeholder: "Spread",
      };

      const { container } = render(<Input {...props} />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveAttribute("id", "spread-input");
      expect(el).toHaveAttribute("data-custom", "value");
      expect(el).toHaveClass("spread-class");
      expect(el).toHaveAttribute("placeholder", "Spread");
    });
  });

  describe("Accessibility", () => {
    it("should support aria-label", () => {
      const { container } = render(<Input aria-label="Username" />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveAttribute("aria-label", "Username");
    });

    it("should support aria-labelledby", () => {
      const { container } = render(<Input aria-labelledby="label-id" />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveAttribute("aria-labelledby", "label-id");
    });

    it("should support aria-describedby", () => {
      const { container } = render(<Input aria-describedby="desc-id" />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveAttribute("aria-describedby", "desc-id");
    });

    it("should support aria-required", () => {
      const { container } = render(<Input aria-required="true" />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveAttribute("aria-required", "true");
    });

    it("should support aria-invalid for error states", () => {
      const { container } = render(<Input aria-invalid="true" />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveAttribute("aria-invalid", "true");
      expect(el).toHaveClass("aria-invalid:border-destructive");
      expect(el).toHaveClass("aria-invalid:ring-3");
    });

    it("should support aria-invalid=false for valid states", () => {
      const { container } = render(<Input aria-invalid="false" />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveAttribute("aria-invalid", "false");
    });
  });

  describe("Disabled State", () => {
    it("should support disabled attribute", () => {
      const { container } = render(<Input disabled />);
      const el = container.querySelector('input[data-slot="input"]') as HTMLInputElement;

      expect(el).toBeDisabled();
      expect(el).toHaveAttribute("disabled");
    });

    it("should have disabled styling classes", () => {
      const { container } = render(<Input disabled />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveClass("disabled:pointer-events-none");
      expect(el).toHaveClass("disabled:cursor-not-allowed");
      expect(el).toHaveClass("disabled:opacity-50");
    });

    it("should not be disabled by default", () => {
      const { container } = render(<Input />);
      const el = container.querySelector('input[data-slot="input"]') as HTMLInputElement;

      expect(el).not.toBeDisabled();
    });

    it("should support readonly attribute", () => {
      const { container } = render(<Input readOnly />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveAttribute("readonly");
    });

    it("should support required attribute", () => {
      const { container } = render(<Input required />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveAttribute("required");
    });
  });

  describe("Ref Forwarding", () => {
    it("should forward ref to the underlying input element", () => {
      const ref = React.createRef<HTMLInputElement>();
      render(<Input ref={ref} />);

      expect(ref.current).toBeInTheDocument();
      expect(ref.current?.tagName).toBe("INPUT");
    });

    it("should allow ref access for DOM manipulation", () => {
      const ref = React.createRef<HTMLInputElement>();
      render(<Input ref={ref} />);

      expect(ref.current).toBeTruthy();
      expect(ref.current?.classList.contains("h-9")).toBe(true);
      expect(ref.current?.classList.contains("border")).toBe(true);
    });

    it("should allow ref to set value programmatically", () => {
      const ref = React.createRef<HTMLInputElement>();
      render(<Input ref={ref} />);

      if (ref.current) {
        ref.current.value = "programmatic value";
      }

      expect((ref.current as HTMLInputElement).value).toBe("programmatic value");
    });

    it("should allow ref to focus the input", () => {
      const ref = React.createRef<HTMLInputElement>();
      render(<Input ref={ref} />);

      ref.current?.focus();
      expect(ref.current).toHaveFocus();
    });
  });

  describe("Export", () => {
    it("should export Input component", () => {
      expect(Input).toBeDefined();
      expect(Input.displayName).toBe("Input");
    });
  });

  describe("Integration", () => {
    it("should render multiple inputs independently", () => {
      const { container } = render(
        <div>
          <Input data-testid="input-1" placeholder="First" />
          <Input data-testid="input-2" placeholder="Second" />
          <Input data-testid="input-3" placeholder="Third" />
        </div>,
      );

      const inputs = container.querySelectorAll('input[data-slot="input"]');
      expect(inputs).toHaveLength(3);
    });

    it("should work in a form context", () => {
      const { container } = render(
        <form>
          <Input name="email" type="email" placeholder="Email" required />
          <Input name="password" type="password" placeholder="Password" required />
        </form>,
      );

      const inputs = container.querySelectorAll('input[data-slot="input"]');
      expect(inputs).toHaveLength(2);
    });

    it("should work with label element", () => {
      const { container } = render(
        <div>
          <label htmlFor="username">Username:</label>
          <Input id="username" name="username" />
        </div>,
      );

      const input = container.querySelector("#username");
      expect(input).toBeInTheDocument();
    });

    it("should work with aria-invalid in form context", () => {
      const { container } = render(
        <div>
          <label htmlFor="email">Email</label>
          <Input id="email" type="email" aria-invalid="true" aria-describedby="email-error" />
          <span id="email-error">Invalid email</span>
        </div>,
      );

      const input = container.querySelector("#email");
      expect(input).toHaveAttribute("aria-invalid", "true");
      expect(input).toHaveAttribute("aria-describedby", "email-error");
    });

    it("should support size customization via className", () => {
      const { container } = render(<Input className="h-12 text-lg" />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveClass("h-12");
      expect(el).toHaveClass("text-lg");
    });

    it("should work with max/minLength attributes", () => {
      const { container } = render(<Input maxLength={50} minLength={5} />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveAttribute("maxlength", "50");
      expect(el).toHaveAttribute("minlength", "5");
    });

    it("should work with pattern attribute", () => {
      const { container } = render(<Input type="text" pattern="[0-9]+" />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toHaveAttribute("pattern", "[0-9]+");
    });
  });

  describe("Edge Cases", () => {
    it("should handle undefined className prop", () => {
      const { container } = render(<Input className={undefined} />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toBeInTheDocument();
      expect(el).toHaveClass("h-9");
    });

    it("should handle whitespace-only className", () => {
      const { container } = render(<Input className="   " />);
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toBeInTheDocument();
      expect(el).toHaveClass("h-9");
    });

    it("should maintain default classes when className is provided", () => {
      const { container } = render(<Input className="custom" />);
      const el = container.querySelector('input[data-slot="input"]');

      // All default classes should still be present
      expect(el).toHaveClass("h-9");
      expect(el).toHaveClass("w-full");
      expect(el).toHaveClass("border");
      expect(el).toHaveClass("bg-transparent");
      // Plus custom classes
      expect(el).toHaveClass("custom");
    });

    it("should handle multiple rerenders with different props", () => {
      const { container, rerender } = render(<Input placeholder="initial" />);

      let el = container.querySelector('input[data-slot="input"]');
      expect(el).toHaveAttribute("placeholder", "initial");

      rerender(<Input placeholder="updated" />);
      el = container.querySelector('input[data-slot="input"]');
      expect(el).toHaveAttribute("placeholder", "updated");

      rerender(<Input placeholder="final" />);
      el = container.querySelector('input[data-slot="input"]');
      expect(el).toHaveAttribute("placeholder", "final");
    });

    it("should preserve data-slot through all prop changes", () => {
      const { container, rerender } = render(<Input id="inp-1" />);

      rerender(<Input className="test" id="inp-2" placeholder="changed" />);

      const el = container.querySelector('input[data-slot="input"]');
      expect(el).toHaveAttribute("data-slot", "input");
    });

    it("should handle rapid type changes", () => {
      const { rerender, container } = render(<Input type="text" />);

      const types = ["text", "email", "password", "number", "text"];

      types.forEach((type) => {
        rerender(<Input type={type} />);
        const el = container.querySelector('input[data-slot="input"]');
        expect(el).toHaveAttribute("type", type);
      });
    });

    it("should handle empty value", () => {
      const { container } = render(<Input value="" readOnly />);
      const el = container.querySelector('input[data-slot="input"]') as HTMLInputElement;

      expect(el.value).toBe("");
    });
  });

  describe("Component Types", () => {
    it("should accept React.ComponentProps<'input'> type", () => {
      const { container } = render(
        <Input
          id="test"
          className="custom"
          data-testid="input"
          aria-label="test"
          type="email"
          placeholder="test@example.com"
        />,
      );
      const el = container.querySelector('input[data-slot="input"]');

      expect(el).toBeInTheDocument();
      expect(el).toHaveAttribute("id", "test");
    });
  });
});
