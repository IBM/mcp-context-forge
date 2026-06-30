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

  it("renders the success status row and rendered-messages block", () => {
    render(
      <PromptPreviewResult
        preview={previewProps({
          hasRun: true,
          result: {
            renderTimeMs: 42,
            rendered: {
              messages: [
                { role: "user", content: { type: "text", text: "hi Alice" } },
              ],
            },
          },
        })}
      />,
    );
    expect(screen.getByText("200 OK")).toBeInTheDocument();
    expect(screen.getByText(/Render 42 ms/)).toBeInTheDocument();
    // The serialized JSON response carries the rendered message text.
    const pre = document.querySelector('pre');
    expect(pre?.textContent ?? "").toContain("hi Alice");
  });

  it("renders the failure status row and the error message", () => {
    render(
      <PromptPreviewResult
        preview={previewProps({
          hasRun: true,
          error: { renderTimeMs: 7, message: "missing required arg `user`" },
        })}
      />,
    );
    expect(screen.getByText(/Render failed/i)).toBeInTheDocument();
    expect(screen.getByText(/Render 7 ms/)).toBeInTheDocument();
    expect(screen.getByText(/missing required arg `user`/)).toBeInTheDocument();
  });
});
