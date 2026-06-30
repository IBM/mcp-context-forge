import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { Popover, PopoverTrigger, PopoverContent, PopoverAnchor } from "./popover";

describe("Popover Components", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("Popover & PopoverTrigger", () => {
    it("renders the trigger with the correct data-slot", () => {
      render(
        <Popover>
          <PopoverTrigger data-testid="trigger">Open</PopoverTrigger>
        </Popover>,
      );

      const trigger = screen.getByTestId("trigger");
      expect(trigger).toBeInTheDocument();
      expect(trigger).toHaveAttribute("data-slot", "popover-trigger");
    });

    it("supports asChild on the trigger", () => {
      render(
        <Popover>
          <PopoverTrigger asChild>
            <button data-testid="my-button">Open</button>
          </PopoverTrigger>
        </Popover>,
      );

      const button = screen.getByTestId("my-button");
      expect(button.tagName).toBe("BUTTON");
    });
  });

  describe("PopoverContent", () => {
    it("renders content with the correct data-slot when open", () => {
      render(
        <Popover open={true}>
          <PopoverTrigger>Open</PopoverTrigger>
          <PopoverContent>Popover body</PopoverContent>
        </Popover>,
      );

      const content = document.querySelector('[data-slot="popover-content"]');
      expect(content).toBeInTheDocument();
      expect(screen.getByText("Popover body")).toBeInTheDocument();
    });

    it("applies a custom className", () => {
      render(
        <Popover open={true}>
          <PopoverTrigger>Open</PopoverTrigger>
          <PopoverContent className="custom-class">Body</PopoverContent>
        </Popover>,
      );

      const content = document.querySelector('[data-slot="popover-content"]');
      expect(content).toHaveClass("custom-class");
      expect(content).toHaveClass("z-50");
    });

    it("honors a custom align prop", () => {
      render(
        <Popover open={true}>
          <PopoverTrigger>Open</PopoverTrigger>
          <PopoverContent align="end">Body</PopoverContent>
        </Popover>,
      );

      const content = document.querySelector('[data-slot="popover-content"]');
      expect(content).toHaveAttribute("data-align", "end");
    });

    it("does not render content while closed", () => {
      render(
        <Popover>
          <PopoverTrigger>Open</PopoverTrigger>
          <PopoverContent>Hidden body</PopoverContent>
        </Popover>,
      );

      expect(screen.queryByText("Hidden body")).not.toBeInTheDocument();
    });
  });

  describe("PopoverAnchor", () => {
    it("renders the anchor with the correct data-slot", () => {
      render(
        <Popover>
          <PopoverAnchor data-testid="anchor" />
          <PopoverTrigger>Open</PopoverTrigger>
        </Popover>,
      );

      const anchor = screen.getByTestId("anchor");
      expect(anchor).toHaveAttribute("data-slot", "popover-anchor");
    });
  });
});
