import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { CardTag } from "./card-tag";

describe("CardTag", () => {
  it("renders a plain chip with no tooltip trigger by default", () => {
    render(<CardTag>label</CardTag>);

    const tag = screen.getByText("label");
    expect(tag).toBeInTheDocument();
    // No tooltip => not wrapped in a focusable trigger.
    expect(tag.closest("button")).toBeNull();
  });

  it("applies the neutral variant classes", () => {
    render(<CardTag variant="neutral">mime</CardTag>);

    expect(screen.getByText("mime")).toHaveClass("bg-neutral-100");
  });

  it("exposes an accessible tooltip when tooltip text is provided", async () => {
    render(<CardTag tooltip="More info">chip</CardTag>);

    const trigger = screen.getByText("chip").closest("button");
    expect(trigger).not.toBeNull();

    // Radix opens the tooltip on focus, giving keyboard users the hint.
    trigger!.focus();
    expect(await screen.findByRole("tooltip")).toHaveTextContent("More info");
  });
});
