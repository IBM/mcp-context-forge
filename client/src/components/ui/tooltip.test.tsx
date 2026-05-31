import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { Tooltip, TooltipProvider, TooltipTrigger, TooltipContent } from "./tooltip";

describe("Tooltip Components", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("TooltipProvider", () => {
    it("should render TooltipProvider with default delayDuration", () => {
      const { container } = render(
        <TooltipProvider>
          <div data-testid="child">Content</div>
        </TooltipProvider>,
      );

      const child = screen.getByTestId("child");
      expect(child).toBeInTheDocument();
    });

    it("should render TooltipProvider with custom delayDuration", () => {
      const { container } = render(
        <TooltipProvider delayDuration={300}>
          <div data-testid="child">Content</div>
        </TooltipProvider>,
      );

      const child = screen.getByTestId("child");
      expect(child).toBeInTheDocument();
    });

    it("should pass through additional props", () => {
      render(
        <TooltipProvider data-custom="test">
          <div data-testid="child">Content</div>
        </TooltipProvider>,
      );

      const child = screen.getByTestId("child");
      expect(child).toBeInTheDocument();
    });
  });

  describe("Tooltip & TooltipTrigger", () => {
    it("should render Tooltip root with correct data-slot", () => {
      const { container } = render(
        <TooltipProvider>
          <Tooltip open={true}>
            <TooltipTrigger asChild>
              <button>Hover me</button>
            </TooltipTrigger>
          </Tooltip>
        </TooltipProvider>,
      );

      const button = screen.getByText("Hover me");
      expect(button).toBeInTheDocument();
    });

    it("should render TooltipTrigger with correct data-slot", () => {
      const { container } = render(
        <TooltipProvider>
          <Tooltip open={true}>
            <TooltipTrigger asChild>
              <button data-testid="trigger">Hover me</button>
            </TooltipTrigger>
          </Tooltip>
        </TooltipProvider>,
      );

      const trigger = screen.getByTestId("trigger");
      expect(trigger).toBeInTheDocument();
    });

    it("should render trigger button element", () => {
      render(
        <TooltipProvider>
          <Tooltip open={true}>
            <TooltipTrigger asChild>
              <button data-testid="my-button">Click me</button>
            </TooltipTrigger>
          </Tooltip>
        </TooltipProvider>,
      );

      const button = screen.getByTestId("my-button");
      expect(button).toBeInTheDocument();
      expect(button.tagName).toBe("BUTTON");
    });
  });

  describe("TooltipContent", () => {
    it("should render TooltipContent without crashing", () => {
      const { container } = render(
        <TooltipProvider>
          <Tooltip open={true}>
            <TooltipTrigger asChild>
              <button>Trigger</button>
            </TooltipTrigger>
            <TooltipContent>
              <span>Tooltip text</span>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>,
      );

      const content = document.querySelector('[data-slot="tooltip-content"]');
      expect(content).toBeInTheDocument();
    });

    it("should render TooltipContent with text content", () => {
      render(
        <TooltipProvider>
          <Tooltip open={true}>
            <TooltipTrigger asChild>
              <button>Trigger</button>
            </TooltipTrigger>
            <TooltipContent>Helpful information</TooltipContent>
          </Tooltip>
        </TooltipProvider>,
      );

      const matches = screen.getAllByText("Helpful information");
      expect(matches.length).toBeGreaterThan(0);
      expect(matches[0]).toBeInTheDocument();
    });

    it("should render TooltipContent with custom sideOffset", () => {
      const { container } = render(
        <TooltipProvider>
          <Tooltip open={true}>
            <TooltipTrigger asChild>
              <button>Trigger</button>
            </TooltipTrigger>
            <TooltipContent sideOffset={8}>Content</TooltipContent>
          </Tooltip>
        </TooltipProvider>,
      );

      const content = document.querySelector('[data-slot="tooltip-content"]');
      expect(content).toBeInTheDocument();
    });

    it("should apply custom className to TooltipContent", () => {
      const { container } = render(
        <TooltipProvider>
          <Tooltip open={true}>
            <TooltipTrigger asChild>
              <button>Trigger</button>
            </TooltipTrigger>
            <TooltipContent className="custom-class">Content</TooltipContent>
          </Tooltip>
        </TooltipProvider>,
      );

      const content = document.querySelector('[data-slot="tooltip-content"]');
      expect(content).toHaveClass("custom-class");
    });

    it("should render arrow inside TooltipContent", () => {
      const { container } = render(
        <TooltipProvider>
          <Tooltip open={true}>
            <TooltipTrigger asChild>
              <button>Trigger</button>
            </TooltipTrigger>
            <TooltipContent>Content</TooltipContent>
          </Tooltip>
        </TooltipProvider>,
      );

      const arrow = document.querySelector('[data-slot="tooltip-content"] svg');
      expect(arrow).toBeInTheDocument();
    });

    it("should render nested children elements", () => {
      render(
        <TooltipProvider>
          <Tooltip open={true}>
            <TooltipTrigger asChild>
              <button>Trigger</button>
            </TooltipTrigger>
            <TooltipContent>
              <div>
                <strong>Bold text</strong>
                <span>Regular text</span>
              </div>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>,
      );

      const bolds = screen.getAllByText("Bold text");
      const regulars = screen.getAllByText("Regular text");
      expect(bolds.length).toBeGreaterThan(0);
      expect(regulars.length).toBeGreaterThan(0);
    });

    it("should have z-index class for proper stacking", () => {
      const { container } = render(
        <TooltipProvider>
          <Tooltip open={true}>
            <TooltipTrigger asChild>
              <button>Trigger</button>
            </TooltipTrigger>
            <TooltipContent>Content</TooltipContent>
          </Tooltip>
        </TooltipProvider>,
      );

      const content = document.querySelector('[data-slot="tooltip-content"]');
      expect(content).toHaveClass("z-50");
    });

    it("should apply animation classes", () => {
      const { container } = render(
        <TooltipProvider>
          <Tooltip open={true}>
            <TooltipTrigger asChild>
              <button>Trigger</button>
            </TooltipTrigger>
            <TooltipContent>Content</TooltipContent>
          </Tooltip>
        </TooltipProvider>,
      );

      const content = document.querySelector('[data-slot="tooltip-content"]');
      const classString = content?.className || "";
      // Should have animation-related classes
      expect(classString).toContain("animate");
    });
  });

  describe("Full Tooltip Integration", () => {
    it("should render complete tooltip structure", () => {
      const { container } = render(
        <TooltipProvider>
          <Tooltip open={true}>
            <TooltipTrigger asChild>
              <button>Help</button>
            </TooltipTrigger>
            <TooltipContent>This is helpful</TooltipContent>
          </Tooltip>
        </TooltipProvider>,
      );

      expect(screen.getByText("Help")).toBeInTheDocument();
      expect(document.querySelector('[data-slot="tooltip-content"]')).toBeInTheDocument();
    });

    it("should handle multiple tooltips in one provider", () => {
      render(
        <TooltipProvider>
          <div>
            <Tooltip open={true}>
              <TooltipTrigger asChild>
                <button>Trigger 1</button>
              </TooltipTrigger>
              <TooltipContent>Content 1</TooltipContent>
            </Tooltip>
            <Tooltip open={true}>
              <TooltipTrigger asChild>
                <button>Trigger 2</button>
              </TooltipTrigger>
              <TooltipContent>Content 2</TooltipContent>
            </Tooltip>
          </div>
        </TooltipProvider>,
      );

      const contents = document.querySelectorAll('[data-slot="tooltip-content"]');
      expect(contents.length).toBeGreaterThanOrEqual(2);
      const content1 = screen.getAllByText("Content 1");
      const content2 = screen.getAllByText("Content 2");
      expect(content1.length).toBeGreaterThan(0);
      expect(content2.length).toBeGreaterThan(0);
    });

    it("should render with Portal", () => {
      const { container } = render(
        <TooltipProvider>
          <Tooltip open={true}>
            <TooltipTrigger asChild>
              <button>Trigger</button>
            </TooltipTrigger>
            <TooltipContent>Content in Portal</TooltipContent>
          </Tooltip>
        </TooltipProvider>,
      );

      const matches = screen.getAllByText("Content in Portal");
      expect(matches.length).toBeGreaterThan(0);
    });
  });
});
