import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Typography } from "./typography";

describe("Typography Component", () => {
  it("renders the default tag for each variant", () => {
    const cases: Array<[Parameters<typeof Typography>[0]["variant"], string]> = [
      ["heading1", "H1"],
      ["heading2", "H2"],
      ["heading3", "H3"],
      ["heading4", "H4"],
      ["heading5", "H5"],
      ["heading6", "H6"],
      ["body", "P"],
      ["bodySmall", "P"],
      ["caption", "SPAN"],
      ["label", "LABEL"],
    ];

    cases.forEach(([variant, tagName]) => {
      const { unmount } = render(
        <Typography variant={variant} data-testid={`text-${variant}`}>
          Content
        </Typography>,
      );
      expect(screen.getByTestId(`text-${variant}`).tagName).toBe(tagName);
      unmount();
    });
  });

  it("defaults to body variant rendered as a paragraph", () => {
    render(<Typography data-testid="default-text">Copy</Typography>);
    const el = screen.getByTestId("default-text");
    expect(el.tagName).toBe("P");
    expect(el).toHaveAttribute("data-variant", "body");
  });

  it("overrides the rendered tag via the as prop without changing styles", () => {
    render(
      <Typography variant="heading2" as="span" data-testid="heading-span">
        Title
      </Typography>,
    );
    const el = screen.getByTestId("heading-span");
    expect(el.tagName).toBe("SPAN");
    expect(el.className).toContain("text-lg");
  });

  it("merges consumer className with variant className", () => {
    render(
      <Typography variant="body" className="text-red-500" data-testid="custom-class">
        Copy
      </Typography>,
    );
    expect(screen.getByTestId("custom-class").className).toContain("text-red-500");
  });

  it("forwards native props to the rendered element", () => {
    render(
      <Typography id="my-id" data-testid="forwarded">
        Copy
      </Typography>,
    );
    expect(screen.getByTestId("forwarded")).toHaveAttribute("id", "my-id");
  });

  it("renders with no children without throwing", () => {
    render(<Typography data-testid="empty" />);
    const el = screen.getByTestId("empty");
    expect(el.tagName).toBe("P");
    expect(el).toBeEmptyDOMElement();
  });

  it("renders nested elements as children", () => {
    render(
      <Typography variant="body" data-testid="nested">
        Intro <strong data-testid="nested-strong">bold part</strong> outro
      </Typography>,
    );
    const strong = screen.getByTestId("nested-strong");
    expect(strong.tagName).toBe("STRONG");
    expect(screen.getByTestId("nested")).toContainElement(strong);
  });

  it("forwards ARIA attributes to the rendered element", () => {
    render(
      <Typography
        variant="heading1"
        role="heading"
        aria-level={1}
        aria-label="Accessible title"
        data-testid="aria-heading"
      >
        Title
      </Typography>,
    );
    const el = screen.getByTestId("aria-heading");
    expect(el).toHaveAttribute("role", "heading");
    expect(el).toHaveAttribute("aria-level", "1");
    expect(el).toHaveAttribute("aria-label", "Accessible title");
  });

  it("exposes a native accessible role matching the default tag", () => {
    render(<Typography variant="heading2">Section title</Typography>);
    expect(screen.getByRole("heading", { level: 2 })).toBeInTheDocument();
  });

  it("keeps a native role when overriding the tag with as", () => {
    render(
      <Typography variant="label" as="p">
        Field label
      </Typography>,
    );
    expect(screen.getByText("Field label").tagName).toBe("P");
  });
});
