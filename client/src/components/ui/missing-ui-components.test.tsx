import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Checkbox } from "./checkbox";
import { Switch } from "./switch";
import { Textarea } from "./textarea";
import { Toaster } from "./sonner";
import { Loading } from "./loading";

// Mock useTheme for Toaster/Sonner
vi.mock("@/hooks/useTheme", () => ({
  useTheme: () => ({ resolvedTheme: "light" }),
}));

// Mock react-intl for Loading component
vi.mock("react-intl", () => ({
  useIntl: () => ({
    formatMessage: ({ id }: { id: string }) => id,
  }),
}));

// Mock sonner library
vi.mock("sonner", () => ({
  Toaster: ({
    children,
    ...props
  }: {
    children?: React.ReactNode;
    theme?: string;
    className?: string;
    icons?: Record<string, React.ReactNode>;
    style?: React.CSSProperties;
    toastOptions?: Record<string, unknown>;
  }) => (
    <div data-testid="sonner-toaster" data-theme={props.theme} className={props.className}>
      {children}
    </div>
  ),
}));

import React from "react";

// ─────────────────────────────────────────────
// Checkbox tests
// ─────────────────────────────────────────────
describe("Checkbox", () => {
  it("renders unchecked by default", () => {
    const { container } = render(<Checkbox />);
    expect(container.firstChild).toBeTruthy();
  });

  it("renders with custom className", () => {
    const { container } = render(<Checkbox className="custom-class" />);
    const el = container.firstChild as HTMLElement;
    expect(el.className).toContain("custom-class");
  });

  it("can be disabled", () => {
    render(<Checkbox disabled data-testid="cb" />);
    // Radix renders a button with disabled attr
    const btn = document.querySelector("button");
    expect(btn).toHaveAttribute("disabled");
  });

  it("calls onCheckedChange when clicked", () => {
    const handler = vi.fn();
    render(<Checkbox onCheckedChange={handler} data-testid="cb" />);
    const btn = document.querySelector("button")!;
    fireEvent.click(btn);
    expect(handler).toHaveBeenCalled();
  });

  it("renders with aria-label", () => {
    render(<Checkbox aria-label="Accept terms" />);
    const btn = document.querySelector("button")!;
    expect(btn).toHaveAttribute("aria-label", "Accept terms");
  });
});

// ─────────────────────────────────────────────
// Switch tests
// ─────────────────────────────────────────────
describe("Switch", () => {
  it("renders without crashing", () => {
    const { container } = render(<Switch />);
    expect(container.firstChild).toBeTruthy();
  });

  it("renders with custom className", () => {
    const { container } = render(<Switch className="my-switch" />);
    const el = container.firstChild as HTMLElement;
    expect(el.className).toContain("my-switch");
  });

  it("can be disabled", () => {
    render(<Switch disabled />);
    const btn = document.querySelector("button")!;
    expect(btn).toHaveAttribute("disabled");
  });

  it("fires onCheckedChange when toggled", () => {
    const handler = vi.fn();
    render(<Switch onCheckedChange={handler} />);
    const btn = document.querySelector("button")!;
    fireEvent.click(btn);
    expect(handler).toHaveBeenCalled();
  });

  it("reflects checked state", () => {
    render(<Switch checked={true} onCheckedChange={vi.fn()} />);
    const btn = document.querySelector("button")!;
    expect(btn).toHaveAttribute("data-state", "checked");
  });

  it("reflects unchecked state", () => {
    render(<Switch checked={false} onCheckedChange={vi.fn()} />);
    const btn = document.querySelector("button")!;
    expect(btn).toHaveAttribute("data-state", "unchecked");
  });
});

// ─────────────────────────────────────────────
// Textarea tests
// ─────────────────────────────────────────────
describe("Textarea", () => {
  it("renders a textarea element", () => {
    render(<Textarea />);
    const ta = screen.getByRole("textbox");
    expect(ta.tagName).toBe("TEXTAREA");
  });

  it("applies custom className", () => {
    render(<Textarea className="my-textarea" />);
    const ta = screen.getByRole("textbox");
    expect(ta.className).toContain("my-textarea");
  });

  it("accepts placeholder", () => {
    render(<Textarea placeholder="Write something..." />);
    const ta = screen.getByPlaceholderText("Write something...");
    expect(ta).toBeTruthy();
  });

  it("fires onChange when typed", () => {
    const handler = vi.fn();
    render(<Textarea onChange={handler} />);
    const ta = screen.getByRole("textbox");
    fireEvent.change(ta, { target: { value: "hello" } });
    expect(handler).toHaveBeenCalled();
  });

  it("can be disabled", () => {
    render(<Textarea disabled />);
    const ta = screen.getByRole("textbox");
    expect(ta).toBeDisabled();
  });

  it("renders with a value", () => {
    render(<Textarea value="preset" onChange={vi.fn()} />);
    const ta = screen.getByRole("textbox") as HTMLTextAreaElement;
    expect(ta.value).toBe("preset");
  });

  it("applies default base classes for styling", () => {
    render(<Textarea />);
    const ta = screen.getByRole("textbox");
    expect(ta.className).toContain("rounded-md");
  });
});

// ─────────────────────────────────────────────
// Sonner / Toaster tests
// ─────────────────────────────────────────────
describe("Toaster (sonner)", () => {
  it("renders without crashing", () => {
    render(<Toaster />);
    const toaster = screen.getByTestId("sonner-toaster");
    expect(toaster).toBeTruthy();
  });

  it("applies light theme when resolvedTheme is light", () => {
    render(<Toaster />);
    const toaster = screen.getByTestId("sonner-toaster");
    expect(toaster).toHaveAttribute("data-theme", "light");
  });

  it("renders with toaster group className", () => {
    render(<Toaster />);
    const toaster = screen.getByTestId("sonner-toaster");
    expect(toaster.className).toContain("toaster");
  });
});

// ─────────────────────────────────────────────
// Loading tests
// ─────────────────────────────────────────────
describe("Loading", () => {
  it("renders page variant by default", () => {
    render(<Loading />);
    const status = screen.getByRole("status");
    expect(status).toBeTruthy();
  });

  it("renders inline variant", () => {
    render(<Loading variant="inline" />);
    const status = screen.getByRole("status");
    expect(status).toBeTruthy();
  });

  it("has aria-live attribute for accessibility", () => {
    render(<Loading />);
    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-live", "polite");
  });

  it("has aria-label from intl message", () => {
    render(<Loading />);
    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-label", "common.loading");
  });

  it("page variant shows Context Forge text", () => {
    render(<Loading variant="page" />);
    expect(screen.getByText("Context Forge")).toBeTruthy();
  });

  it("inline variant does not show Context Forge text", () => {
    render(<Loading variant="inline" />);
    expect(screen.queryByText("Context Forge")).toBeNull();
  });

  it("page variant has large SVG", () => {
    const { container } = render(<Loading variant="page" />);
    const svg = container.querySelector("svg");
    expect(svg).toBeTruthy();
    // SVG className is SVGAnimatedString in JSDOM; use getAttribute
    expect(svg!.getAttribute("class")).toContain("h-16");
  });

  it("inline variant has small SVG", () => {
    const { container } = render(<Loading variant="inline" />);
    const svg = container.querySelector("svg");
    expect(svg!.getAttribute("class")).toContain("size-4");
  });
});
