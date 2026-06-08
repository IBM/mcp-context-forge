import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RadioGroup, RadioGroupItem } from "./radio-group";

describe("RadioGroup", () => {
  describe("RadioGroup Root Rendering", () => {
    it("should render the radio group root element", () => {
      const { container } = render(
        <RadioGroup>
          <RadioGroupItem value="option1" id="option1" />
        </RadioGroup>,
      );

      const radioGroup = container.querySelector('[role="radiogroup"]');
      expect(radioGroup).toBeInTheDocument();
    });

    it("should apply default grid classes", () => {
      const { container } = render(
        <RadioGroup>
          <RadioGroupItem value="option1" id="option1" />
        </RadioGroup>,
      );

      const radioGroup = container.querySelector('[role="radiogroup"]');
      expect(radioGroup).toHaveClass("grid");
      expect(radioGroup).toHaveClass("gap-2");
    });

    it("should merge custom className with default classes", () => {
      const { container } = render(
        <RadioGroup className="custom-class">
          <RadioGroupItem value="option1" id="option1" />
        </RadioGroup>,
      );

      const radioGroup = container.querySelector('[role="radiogroup"]');
      expect(radioGroup).toHaveClass("custom-class");
      expect(radioGroup).toHaveClass("grid");
    });

    it("should support ref forwarding", () => {
      const ref = { current: null } as any;
      render(
        <RadioGroup ref={ref}>
          <RadioGroupItem value="option1" id="option1" />
        </RadioGroup>,
      );

      expect(ref.current).toBeInTheDocument();
    });

    it("should forward custom props", () => {
      const { container } = render(
        <RadioGroup data-testid="group" id="my-group">
          <RadioGroupItem value="option1" id="option1" />
        </RadioGroup>,
      );

      const group = screen.getByTestId("group");
      expect(group).toHaveAttribute("id", "my-group");
    });

    it("should have displayName", () => {
      expect(RadioGroup.displayName).toBeDefined();
    });
  });

  describe("RadioGroupItem Rendering", () => {
    it("should render radio item elements", () => {
      const { container } = render(
        <RadioGroup>
          <RadioGroupItem value="option1" id="option1" />
          <RadioGroupItem value="option2" id="option2" />
        </RadioGroup>,
      );

      const items = container.querySelectorAll('[role="radio"]');
      expect(items).toHaveLength(2);
    });

    it("should render with correct classes", () => {
      const { container } = render(
        <RadioGroup>
          <RadioGroupItem value="option1" id="option1" />
        </RadioGroup>,
      );

      const item = container.querySelector('[role="radio"]');
      expect(item).toHaveClass("aspect-square");
      expect(item).toHaveClass("h-4");
      expect(item).toHaveClass("w-4");
      expect(item).toHaveClass("rounded-full");
      expect(item).toHaveClass("border");
    });

    it("should merge custom className with default classes", () => {
      const { container } = render(
        <RadioGroup>
          <RadioGroupItem value="option1" id="option1" className="custom" />
        </RadioGroup>,
      );

      const item = container.querySelector('[role="radio"]');
      expect(item).toHaveClass("custom");
      expect(item).toHaveClass("h-4");
    });

    it("should support ref forwarding on item", () => {
      const ref = { current: null } as any;
      render(
        <RadioGroup>
          <RadioGroupItem ref={ref} value="option1" id="option1" />
        </RadioGroup>,
      );

      expect(ref.current).toBeInTheDocument();
    });

    it("should have displayName", () => {
      expect(RadioGroupItem.displayName).toBeDefined();
    });
  });

  describe("Item Styling", () => {
    it("should have border styling", () => {
      const { container } = render(
        <RadioGroup>
          <RadioGroupItem value="option1" id="option1" />
        </RadioGroup>,
      );

      const item = container.querySelector('[role="radio"]');
      expect(item).toHaveClass("border");
      expect(item).toHaveClass("border-neutral-300");
    });

    it("should have size classes", () => {
      const { container } = render(
        <RadioGroup>
          <RadioGroupItem value="option1" id="option1" />
        </RadioGroup>,
      );

      const item = container.querySelector('[role="radio"]');
      expect(item).toHaveClass("h-4");
      expect(item).toHaveClass("w-4");
      expect(item).toHaveClass("aspect-square");
    });

    it("should have focus outline classes", () => {
      const { container } = render(
        <RadioGroup>
          <RadioGroupItem value="option1" id="option1" />
        </RadioGroup>,
      );

      const item = container.querySelector('[role="radio"]');
      expect(item).toHaveClass("focus:outline-none");
      expect(item).toHaveClass("focus-visible:ring-2");
    });

    it("should have text color classes", () => {
      const { container } = render(
        <RadioGroup>
          <RadioGroupItem value="option1" id="option1" />
        </RadioGroup>,
      );

      const item = container.querySelector('[role="radio"]');
      expect(item).toHaveClass("text-neutral-950");
    });

    it("should have disabled state classes", () => {
      const { container } = render(
        <RadioGroup>
          <RadioGroupItem value="option1" id="option1" />
        </RadioGroup>,
      );

      const item = container.querySelector('[role="radio"]');
      expect(item).toHaveClass("disabled:cursor-not-allowed");
      expect(item).toHaveClass("disabled:opacity-50");
    });
  });

  describe("Dark Mode Support", () => {
    it("should have dark mode classes", () => {
      const { container } = render(
        <RadioGroup>
          <RadioGroupItem value="option1" id="option1" />
        </RadioGroup>,
      );

      const item = container.querySelector('[role="radio"]');
      expect(item).toHaveClass("dark:border-neutral-700");
      expect(item).toHaveClass("dark:text-neutral-50");
      expect(item).toHaveClass("dark:ring-offset-neutral-950");
      expect(item).toHaveClass("dark:focus-visible:ring-neutral-300");
    });
  });

  describe("Accessibility Attributes", () => {
    it("should have role=radiogroup on root", () => {
      const { container } = render(
        <RadioGroup>
          <RadioGroupItem value="option1" id="option1" />
        </RadioGroup>,
      );

      const group = container.querySelector('[role="radiogroup"]');
      expect(group).toHaveAttribute("role", "radiogroup");
    });

    it("should have role=radio on items", () => {
      const { container } = render(
        <RadioGroup>
          <RadioGroupItem value="option1" id="option1" />
        </RadioGroup>,
      );

      const item = container.querySelector('[role="radio"]');
      expect(item).toHaveAttribute("role", "radio");
    });

    it("should support aria-label on group", () => {
      const { container } = render(
        <RadioGroup aria-label="Choose option">
          <RadioGroupItem value="option1" id="option1" />
        </RadioGroup>,
      );

      const group = container.querySelector('[role="radiogroup"]');
      expect(group).toHaveAttribute("aria-label", "Choose option");
    });

    it("should support aria-label on items", () => {
      const { container } = render(
        <RadioGroup>
          <RadioGroupItem value="option1" id="option1" aria-label="Option 1" />
        </RadioGroup>,
      );

      const item = container.querySelector('[role="radio"]');
      expect(item).toHaveAttribute("aria-label", "Option 1");
    });

    it("should support aria-describedby", () => {
      const { container } = render(
        <RadioGroup>
          <RadioGroupItem value="option1" id="option1" aria-describedby="desc1" />
        </RadioGroup>,
      );

      const item = container.querySelector('[role="radio"]');
      expect(item).toHaveAttribute("aria-describedby", "desc1");
    });
  });

  describe("Selection and State", () => {
    it("should support value prop", () => {
      const { container, rerender } = render(
        <RadioGroup value="option1">
          <RadioGroupItem value="option1" id="option1" />
          <RadioGroupItem value="option2" id="option2" />
        </RadioGroup>,
      );

      let items = container.querySelectorAll('[role="radio"]');
      expect(items[0]).toHaveAttribute("aria-checked", "true");
      expect(items[1]).toHaveAttribute("aria-checked", "false");

      rerender(
        <RadioGroup value="option2">
          <RadioGroupItem value="option1" id="option1" />
          <RadioGroupItem value="option2" id="option2" />
        </RadioGroup>,
      );

      items = container.querySelectorAll('[role="radio"]');
      expect(items[0]).toHaveAttribute("aria-checked", "false");
      expect(items[1]).toHaveAttribute("aria-checked", "true");
    });

    it("should support defaultValue prop", () => {
      const { container } = render(
        <RadioGroup defaultValue="option2">
          <RadioGroupItem value="option1" id="option1" />
          <RadioGroupItem value="option2" id="option2" />
        </RadioGroup>,
      );

      const items = container.querySelectorAll('[role="radio"]');
      expect(items[0]).toHaveAttribute("aria-checked", "false");
      expect(items[1]).toHaveAttribute("aria-checked", "true");
    });

    it("should call onValueChange callback", async () => {
      const user = userEvent.setup();
      const onChange = vi.fn<[string]>();

      const { container } = render(
        <RadioGroup onValueChange={onChange}>
          <RadioGroupItem value="option1" id="option1" />
          <RadioGroupItem value="option2" id="option2" />
        </RadioGroup>,
      );

      const item2 = container.querySelectorAll('[role="radio"]')[1];
      await user.click(item2);

      expect(onChange).toHaveBeenCalledWith("option2");
    });

    it("should only have one selected at a time", () => {
      const { container } = render(
        <RadioGroup value="option2">
          <RadioGroupItem value="option1" id="option1" />
          <RadioGroupItem value="option2" id="option2" />
          <RadioGroupItem value="option3" id="option3" />
        </RadioGroup>,
      );

      const selected = container.querySelectorAll('[aria-checked="true"]');
      expect(selected).toHaveLength(1);
    });
  });

  describe("Keyboard Navigation", () => {
    it("should support arrow key navigation", async () => {
      const user = userEvent.setup();
      const onChange = vi.fn<[string]>();

      const { container } = render(
        <RadioGroup onValueChange={onChange}>
          <RadioGroupItem value="option1" id="option1" />
          <RadioGroupItem value="option2" id="option2" />
          <RadioGroupItem value="option3" id="option3" />
        </RadioGroup>,
      );

      const firstItem = container.querySelector('[role="radio"]') as HTMLElement;
      firstItem.focus();

      await user.keyboard("{ArrowRight}");
      const itemsAfter = container.querySelectorAll('[role="radio"]');
      expect(itemsAfter[1]).toHaveFocus();
    });

    it("should support tab navigation", async () => {
      const user = userEvent.setup();

      const { container } = render(
        <RadioGroup>
          <RadioGroupItem value="option1" id="option1" />
          <RadioGroupItem value="option2" id="option2" />
        </RadioGroup>,
      );

      const firstItem = container.querySelector('[role="radio"]') as HTMLElement;

      await user.tab();
      expect(firstItem).toHaveFocus();
    });

    it("should support space key selection", async () => {
      const user = userEvent.setup();
      const onChange = vi.fn<[string]>();

      const { container } = render(
        <RadioGroup onValueChange={onChange}>
          <RadioGroupItem value="option1" id="option1" />
          <RadioGroupItem value="option2" id="option2" />
        </RadioGroup>,
      );

      const firstItem = container.querySelector('[role="radio"]') as HTMLElement;
      firstItem.focus();

      await user.keyboard(" ");
      expect(onChange).toHaveBeenCalled();
    });
  });

  describe("Disabled State", () => {
    it("should support disabled on items", () => {
      const { container } = render(
        <RadioGroup>
          <RadioGroupItem value="option1" id="option1" disabled />
          <RadioGroupItem value="option2" id="option2" />
        </RadioGroup>,
      );

      const items = container.querySelectorAll('[role="radio"]');
      expect(items[0]).toHaveAttribute("disabled");
      expect(items[1]).not.toHaveAttribute("disabled");
    });

    it("should prevent interaction on disabled items", async () => {
      const user = userEvent.setup();
      const onChange = vi.fn<[string]>();

      const { container } = render(
        <RadioGroup onValueChange={onChange}>
          <RadioGroupItem value="option1" id="option1" disabled />
        </RadioGroup>,
      );

      const item = container.querySelector('[role="radio"]') as HTMLElement;
      await user.click(item);

      expect(onChange).not.toHaveBeenCalled();
    });

    it("should have disabled opacity class", () => {
      const { container } = render(
        <RadioGroup>
          <RadioGroupItem value="option1" id="option1" disabled />
        </RadioGroup>,
      );

      const item = container.querySelector('[role="radio"]');
      expect(item).toHaveClass("disabled:opacity-50");
    });
  });

  describe("Circle Indicator Icon", () => {
    it("should render SVG circle inside selected item", () => {
      const { container } = render(
        <RadioGroup value="option1">
          <RadioGroupItem value="option1" id="option1" />
        </RadioGroup>,
      );

      const svg = container.querySelector('[role="radio"] svg');
      expect(svg).toBeInTheDocument();
    });

    it("should have correct SVG icon classes", () => {
      const { container } = render(
        <RadioGroup value="option1">
          <RadioGroupItem value="option1" id="option1" />
        </RadioGroup>,
      );

      const svg = container.querySelector('[role="radio"] svg');
      expect(svg).toHaveClass("h-2.5");
      expect(svg).toHaveClass("w-2.5");
      expect(svg).toHaveClass("fill-current");
    });

    it("should have indicator container structure", () => {
      const { container } = render(
        <RadioGroup value="option1">
          <RadioGroupItem value="option1" id="option1" />
        </RadioGroup>,
      );

      const item = container.querySelector('[role="radio"]');
      const indicatorContainer = item?.querySelector(".flex");
      expect(indicatorContainer).toBeInTheDocument();
    });
  });

  describe("Multiple Items", () => {
    it("should render multiple items independently", () => {
      const { container } = render(
        <RadioGroup value="option2">
          <RadioGroupItem value="option1" id="option1" />
          <RadioGroupItem value="option2" id="option2" />
          <RadioGroupItem value="option3" id="option3" />
        </RadioGroup>,
      );

      const items = container.querySelectorAll('[role="radio"]');
      expect(items).toHaveLength(3);
      expect(items[0]).toHaveAttribute("aria-checked", "false");
      expect(items[1]).toHaveAttribute("aria-checked", "true");
      expect(items[2]).toHaveAttribute("aria-checked", "false");
    });
  });

  describe("Integration", () => {
    it("should work with associated labels", () => {
      const { container } = render(
        <RadioGroup>
          <div>
            <RadioGroupItem value="opt1" id="opt1" />
            <label htmlFor="opt1">Option 1</label>
          </div>
          <div>
            <RadioGroupItem value="opt2" id="opt2" />
            <label htmlFor="opt2">Option 2</label>
          </div>
        </RadioGroup>,
      );

      const labels = container.querySelectorAll("label");
      expect(labels).toHaveLength(2);
    });

    it("should work in form context", async () => {
      const user = userEvent.setup();
      const onChange = vi.fn<[string]>();

      const { container } = render(
        <form>
          <fieldset>
            <legend>Select option</legend>
            <RadioGroup onValueChange={onChange}>
              <RadioGroupItem value="opt1" id="opt1" />
              <RadioGroupItem value="opt2" id="opt2" />
            </RadioGroup>
          </fieldset>
        </form>,
      );

      const items = container.querySelectorAll('[role="radio"]');
      await user.click(items[0]);

      expect(onChange).toHaveBeenCalledWith("opt1");
    });

    it("should handle rapid value changes", () => {
      const { rerender, container } = render(
        <RadioGroup value="opt1">
          <RadioGroupItem value="opt1" id="opt1" />
          <RadioGroupItem value="opt2" id="opt2" />
          <RadioGroupItem value="opt3" id="opt3" />
        </RadioGroup>,
      );

      for (let i = 1; i <= 3; i++) {
        const value = `opt${i}`;
        rerender(
          <RadioGroup value={value}>
            <RadioGroupItem value="opt1" id="opt1" />
            <RadioGroupItem value="opt2" id="opt2" />
            <RadioGroupItem value="opt3" id="opt3" />
          </RadioGroup>,
        );

        const items = container.querySelectorAll('[role="radio"]');
        const selectedItem = Array.from(items).find(
          (item) => item.getAttribute("aria-checked") === "true",
        );
        expect(selectedItem).toHaveAttribute("aria-checked", "true");
      }
    });
  });

  describe("Grid Layout", () => {
    it("should have grid container", () => {
      const { container } = render(
        <RadioGroup>
          <RadioGroupItem value="option1" id="option1" />
        </RadioGroup>,
      );

      const group = container.querySelector('[role="radiogroup"]');
      expect(group).toHaveClass("grid");
    });

    it("should have gap between items", () => {
      const { container } = render(
        <RadioGroup>
          <RadioGroupItem value="option1" id="option1" />
        </RadioGroup>,
      );

      const group = container.querySelector('[role="radiogroup"]');
      expect(group).toHaveClass("gap-2");
    });
  });

  describe("Props Forwarding", () => {
    it("should forward standard HTML attributes to root", () => {
      const { container } = render(
        <RadioGroup title="Radio Options" data-custom="value">
          <RadioGroupItem value="option1" id="option1" />
        </RadioGroup>,
      );

      const group = container.querySelector('[role="radiogroup"]');
      expect(group).toHaveAttribute("title", "Radio Options");
      expect(group).toHaveAttribute("data-custom", "value");
    });

    it("should forward standard HTML attributes to item", () => {
      const { container } = render(
        <RadioGroup>
          <RadioGroupItem value="option1" id="option1" title="Select this" data-option="1" />
        </RadioGroup>,
      );

      const item = container.querySelector('[role="radio"]');
      expect(item).toHaveAttribute("title", "Select this");
      expect(item).toHaveAttribute("data-option", "1");
    });
  });

  describe("Focus States", () => {
    it("should have focus-visible ring styles", () => {
      const { container } = render(
        <RadioGroup>
          <RadioGroupItem value="option1" id="option1" />
        </RadioGroup>,
      );

      const radioItem = container.querySelector('[role="radio"]');
      expect(radioItem).toHaveClass("focus-visible:ring-2");
      expect(radioItem).toHaveClass("focus-visible:ring-offset-2");
    });

    it("should show focus ring when focused", async () => {
      const user = userEvent.setup();
      const { container } = render(
        <RadioGroup>
          <RadioGroupItem value="option1" id="option1" />
        </RadioGroup>,
      );

      const radioItem = container.querySelector('[role="radio"]') as HTMLElement;
      await user.click(radioItem);

      expect(radioItem).toHaveFocus();
    });
  });
});
