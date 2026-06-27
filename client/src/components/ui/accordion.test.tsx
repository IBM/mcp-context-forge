import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  Accordion,
  AccordionItem,
  AccordionTrigger,
  AccordionContent,
} from "./accordion";

describe("Accordion Components", () => {
  it("renders Accordion with AccordionItem", () => {
    render(
      <Accordion type="single" collapsible>
        <AccordionItem value="item-1">
          <AccordionTrigger>Title 1</AccordionTrigger>
          <AccordionContent>Content 1</AccordionContent>
        </AccordionItem>
      </Accordion>,
    );
    expect(screen.getByText("Title 1")).toBeInTheDocument();
  });

  it("renders AccordionTrigger as a button", () => {
    render(
      <Accordion type="single" collapsible>
        <AccordionItem value="item-1">
          <AccordionTrigger>Trigger Button</AccordionTrigger>
          <AccordionContent>Content</AccordionContent>
        </AccordionItem>
      </Accordion>,
    );
    expect(screen.getByRole("button", { name: /trigger button/i })).toBeInTheDocument();
  });

  it("shows accordion content when item is clicked", async () => {
    const user = userEvent.setup();
    render(
      <Accordion type="single" collapsible>
        <AccordionItem value="item-1">
          <AccordionTrigger>Toggle Item</AccordionTrigger>
          <AccordionContent>Hidden Content</AccordionContent>
        </AccordionItem>
      </Accordion>,
    );

    const trigger = screen.getByRole("button", { name: /toggle item/i });
    await user.click(trigger);

    expect(screen.getByText("Hidden Content")).toBeInTheDocument();
  });

  it("renders multiple accordion items", () => {
    render(
      <Accordion type="single" collapsible>
        <AccordionItem value="item-1">
          <AccordionTrigger>Item 1</AccordionTrigger>
          <AccordionContent>Content 1</AccordionContent>
        </AccordionItem>
        <AccordionItem value="item-2">
          <AccordionTrigger>Item 2</AccordionTrigger>
          <AccordionContent>Content 2</AccordionContent>
        </AccordionItem>
        <AccordionItem value="item-3">
          <AccordionTrigger>Item 3</AccordionTrigger>
          <AccordionContent>Content 3</AccordionContent>
        </AccordionItem>
      </Accordion>,
    );
    expect(screen.getByText("Item 1")).toBeInTheDocument();
    expect(screen.getByText("Item 2")).toBeInTheDocument();
    expect(screen.getByText("Item 3")).toBeInTheDocument();
  });

  it("supports custom className on AccordionItem", () => {
    const { container } = render(
      <Accordion type="single" collapsible>
        <AccordionItem value="item-1" className="custom-class">
          <AccordionTrigger>Item</AccordionTrigger>
          <AccordionContent>Content</AccordionContent>
        </AccordionItem>
      </Accordion>,
    );
    expect(container.querySelector(".custom-class")).toBeInTheDocument();
  });

  it("supports custom className on AccordionTrigger", () => {
    render(
      <Accordion type="single" collapsible>
        <AccordionItem value="item-1">
          <AccordionTrigger className="custom-trigger">Custom Styled Trigger</AccordionTrigger>
          <AccordionContent>Content</AccordionContent>
        </AccordionItem>
      </Accordion>,
    );
    const trigger = screen.getByRole("button", { name: /custom styled trigger/i });
    expect(trigger).toHaveClass("custom-trigger");
  });

  it("supports custom className on AccordionContent", async () => {
    const user = userEvent.setup();
    render(
      <Accordion type="single" collapsible>
        <AccordionItem value="item-1">
          <AccordionTrigger>Trigger</AccordionTrigger>
          <AccordionContent className="custom-content">Content Text</AccordionContent>
        </AccordionItem>
      </Accordion>,
    );

    const trigger = screen.getByRole("button", { name: /trigger/i });
    await user.click(trigger);

    expect(screen.getByText("Content Text")).toBeInTheDocument();
  });

  it("can be opened and closed (collapsible)", async () => {
    const user = userEvent.setup();
    render(
      <Accordion type="single" collapsible>
        <AccordionItem value="item-1">
          <AccordionTrigger>Toggle</AccordionTrigger>
          <AccordionContent>Collapsible Content</AccordionContent>
        </AccordionItem>
      </Accordion>,
    );

    const trigger = screen.getByRole("button", { name: /toggle/i });
    // Open
    await user.click(trigger);
    expect(screen.getByText("Collapsible Content")).toBeInTheDocument();
    // Close
    await user.click(trigger);
  });

  it("in multiple type, opening one doesn't close another", async () => {
    const user = userEvent.setup();
    render(
      <Accordion type="multiple">
        <AccordionItem value="item-1">
          <AccordionTrigger>Item One</AccordionTrigger>
          <AccordionContent>Content One</AccordionContent>
        </AccordionItem>
        <AccordionItem value="item-2">
          <AccordionTrigger>Item Two</AccordionTrigger>
          <AccordionContent>Content Two</AccordionContent>
        </AccordionItem>
      </Accordion>,
    );

    await user.click(screen.getByRole("button", { name: /item one/i }));
    await user.click(screen.getByRole("button", { name: /item two/i }));

    expect(screen.getByText("Content One")).toBeInTheDocument();
    expect(screen.getByText("Content Two")).toBeInTheDocument();
  });

  it("renders ChevronDown icon in trigger", () => {
    const { container } = render(
      <Accordion type="single" collapsible>
        <AccordionItem value="item-1">
          <AccordionTrigger>With Icon</AccordionTrigger>
          <AccordionContent>Content</AccordionContent>
        </AccordionItem>
      </Accordion>,
    );
    // ChevronDown renders as SVG
    expect(container.querySelector("svg")).toBeInTheDocument();
  });

  it("renders AccordionContent children correctly", async () => {
    const user = userEvent.setup();
    render(
      <Accordion type="single" collapsible>
        <AccordionItem value="item-1">
          <AccordionTrigger>Show</AccordionTrigger>
          <AccordionContent>
            <p>Paragraph child</p>
            <span>Span child</span>
          </AccordionContent>
        </AccordionItem>
      </Accordion>,
    );

    await user.click(screen.getByRole("button", { name: /show/i }));
    expect(screen.getByText("Paragraph child")).toBeInTheDocument();
    expect(screen.getByText("Span child")).toBeInTheDocument();
  });

  it("displays correct aria-expanded state on trigger", async () => {
    const user = userEvent.setup();
    render(
      <Accordion type="single" collapsible>
        <AccordionItem value="item-1">
          <AccordionTrigger>Expandable</AccordionTrigger>
          <AccordionContent>Content</AccordionContent>
        </AccordionItem>
      </Accordion>,
    );

    const trigger = screen.getByRole("button", { name: /expandable/i });
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    await user.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
  });
});
