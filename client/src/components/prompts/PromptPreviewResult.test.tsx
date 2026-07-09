import { describe, it, expect } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders as render } from "@/test/test-utils";
import { PromptPreviewResult } from "./PromptPreviewResult";
import type { PromptPreviewState } from "./usePromptPreview";

function previewProps(
  overrides: Partial<Pick<PromptPreviewState, "result" | "error" | "hasRun">>,
): Pick<PromptPreviewState, "result" | "error" | "hasRun"> {
  return {
    result: null,
    error: null,
    hasRun: false,
    ...overrides,
  };
}

describe("PromptPreviewResult", () => {
  it("renders nothing before the first run", () => {
    const { container } = render(<PromptPreviewResult preview={previewProps({})} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders the success status row with the real HTTP status and the rendered-messages block", () => {
    render(
      <PromptPreviewResult
        preview={previewProps({
          hasRun: true,
          result: {
            renderTimeMs: 42,
            status: 200,
            rendered: {
              messages: [{ role: "user", content: { type: "text", text: "hi Alice" } }],
            },
          },
        })}
      />,
    );
    expect(screen.getByText("200 OK")).toBeInTheDocument();
    expect(screen.getByText(/Render 42 ms/)).toBeInTheDocument();
    // The serialized JSON response carries the rendered message text.
    const pre = document.querySelector("pre");
    expect(pre?.textContent ?? "").toContain("hi Alice");
  });

  it("uses the actual 2xx status code returned by the backend", () => {
    render(
      <PromptPreviewResult
        preview={previewProps({
          hasRun: true,
          result: {
            renderTimeMs: 12,
            status: 202,
            rendered: { messages: [] },
          },
        })}
      />,
    );
    expect(screen.getByText("202 OK")).toBeInTheDocument();
  });

  it("prefixes the error row with the HTTP status when available", () => {
    render(
      <PromptPreviewResult
        preview={previewProps({
          hasRun: true,
          error: { renderTimeMs: 7, status: 422, message: "missing required arg `user`" },
        })}
      />,
    );
    expect(screen.getByText(/422 — render failed/i)).toBeInTheDocument();
    expect(screen.getByText(/Render 7 ms/)).toBeInTheDocument();
    expect(screen.getByText(/missing required arg `user`/)).toBeInTheDocument();
  });

  it("falls back to the plain failure label when no status is available (e.g. network error)", () => {
    render(
      <PromptPreviewResult
        preview={previewProps({
          hasRun: true,
          error: { renderTimeMs: 7, status: null, message: "network error" },
        })}
      />,
    );
    expect(screen.getByText(/^Render failed$/i)).toBeInTheDocument();
    expect(screen.getByText(/network error/)).toBeInTheDocument();
  });
});
