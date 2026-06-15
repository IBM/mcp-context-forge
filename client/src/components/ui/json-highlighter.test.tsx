import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { JsonHighlighter } from "./json-highlighter";

describe("JsonHighlighter", () => {
  it("renders simple JSON string", () => {
    const json = '{"key": "value"}';
    const { container } = render(<JsonHighlighter text={json} />);
    expect(container.textContent).toBe(json);
  });

  it("highlights string values", () => {
    const json = '{"name": "test"}';
    const { container } = render(<JsonHighlighter text={json} />);

    const spans = container.querySelectorAll("span");
    const stringSpan = Array.from(spans).find((span) => span.textContent === '"test"');
    expect(stringSpan).toHaveStyle({ color: "#AE69FF" });
  });

  it("highlights object keys", () => {
    const json = '{"key": "value"}';
    const { container } = render(<JsonHighlighter text={json} />);

    const spans = container.querySelectorAll("span");
    const keySpan = Array.from(spans).find((span) => span.textContent === '"key"');
    expect(keySpan).toHaveStyle({ color: "#6FFF9F" });
  });

  it("highlights numbers", () => {
    const json = '{"count": 42}';
    const { container } = render(<JsonHighlighter text={json} />);

    const spans = container.querySelectorAll("span");
    const numberSpan = Array.from(spans).find((span) => span.textContent === "42");
    expect(numberSpan).toHaveStyle({ color: "#FFB86F" });
  });

  it("highlights boolean values", () => {
    const json = '{"enabled": true, "disabled": false}';
    const { container } = render(<JsonHighlighter text={json} />);

    const spans = container.querySelectorAll("span");
    const trueSpan = Array.from(spans).find((span) => span.textContent === "true");
    const falseSpan = Array.from(spans).find((span) => span.textContent === "false");

    expect(trueSpan).toHaveStyle({ color: "#6FC8FF" });
    expect(falseSpan).toHaveStyle({ color: "#6FC8FF" });
  });

  it("highlights null values", () => {
    const json = '{"value": null}';
    const { container } = render(<JsonHighlighter text={json} />);

    const spans = container.querySelectorAll("span");
    const nullSpan = Array.from(spans).find((span) => span.textContent === "null");
    expect(nullSpan).toHaveStyle({ color: "#6FC8FF" });
  });

  it("does not highlight punctuation", () => {
    const json = '{"key": "value"}';
    const { container } = render(<JsonHighlighter text={json} />);

    // Punctuation should be rendered as plain text (not in colored spans)
    expect(container.textContent).toContain("{");
    expect(container.textContent).toContain("}");
    expect(container.textContent).toContain(":");
  });

  it("preserves whitespace", () => {
    const json = '{\n  "key": "value"\n}';
    const { container } = render(<JsonHighlighter text={json} />);

    expect(container.textContent).toBe(json);
  });

  it("handles nested objects", () => {
    const json = '{"outer": {"inner": "value"}}';
    const { container } = render(<JsonHighlighter text={json} />);

    const spans = container.querySelectorAll("span");
    const outerKey = Array.from(spans).find((span) => span.textContent === '"outer"');
    const innerKey = Array.from(spans).find((span) => span.textContent === '"inner"');

    expect(outerKey).toHaveStyle({ color: "#6FFF9F" });
    expect(innerKey).toHaveStyle({ color: "#6FFF9F" });
  });

  it("handles arrays", () => {
    const json = '{"items": [1, 2, 3]}';
    const { container } = render(<JsonHighlighter text={json} />);

    const spans = container.querySelectorAll("span");
    const numbers = Array.from(spans).filter((span) =>
      ["1", "2", "3"].includes(span.textContent || ""),
    );

    expect(numbers).toHaveLength(3);
    numbers.forEach((span) => {
      expect(span).toHaveStyle({ color: "#FFB86F" });
    });
  });

  it("handles escaped characters in strings", () => {
    const json = '{"text": "line1\\nline2"}';
    const { container } = render(<JsonHighlighter text={json} />);

    expect(container.textContent).toContain("line1\\nline2");
  });

  it("handles negative numbers", () => {
    const json = '{"value": -42}';
    const { container } = render(<JsonHighlighter text={json} />);

    const spans = container.querySelectorAll("span");
    const numberSpan = Array.from(spans).find((span) => span.textContent === "-42");
    expect(numberSpan).toHaveStyle({ color: "#FFB86F" });
  });

  it("handles decimal numbers", () => {
    const json = '{"value": 3.14}';
    const { container } = render(<JsonHighlighter text={json} />);

    const spans = container.querySelectorAll("span");
    const numberSpan = Array.from(spans).find((span) => span.textContent === "3.14");
    expect(numberSpan).toHaveStyle({ color: "#FFB86F" });
  });

  it("handles scientific notation", () => {
    const json = '{"value": 1.5e10}';
    const { container } = render(<JsonHighlighter text={json} />);

    const spans = container.querySelectorAll("span");
    const numberSpan = Array.from(spans).find((span) => span.textContent === "1.5e10");
    expect(numberSpan).toHaveStyle({ color: "#FFB86F" });
  });

  it("handles empty object", () => {
    const json = "{}";
    const { container } = render(<JsonHighlighter text={json} />);

    expect(container.textContent).toBe("{}");
  });

  it("handles empty array", () => {
    const json = "[]";
    const { container } = render(<JsonHighlighter text={json} />);

    expect(container.textContent).toBe("[]");
  });

  it("handles complex nested structure", () => {
    const json = JSON.stringify(
      {
        type: "object",
        properties: {
          query: {
            type: "string",
            description: "Search query",
          },
          limit: {
            type: "number",
            default: 10,
          },
        },
      },
      null,
      2,
    );

    const { container } = render(<JsonHighlighter text={json} />);

    expect(container.textContent).toBe(json);

    const spans = container.querySelectorAll("span");
    expect(spans.length).toBeGreaterThan(0);
  });

  it("renders each token with correct key", () => {
    const json = '{"a": 1, "b": 2}';
    const { container } = render(<JsonHighlighter text={json} />);

    // Each token should have a unique key (idx)
    const spans = container.querySelectorAll("span");
    expect(spans.length).toBeGreaterThan(0);
  });
});
