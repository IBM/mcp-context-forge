import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders as render } from "@/test/test-utils";
import { PromptPreviewButton } from "./PromptPreviewButton";

function makePreview(
  overrides: Partial<{
    run: () => Promise<void>;
    isLoading: boolean;
    hasRun: boolean;
  }> = {},
) {
  return {
    run: vi.fn().mockResolvedValue(undefined),
    isLoading: false,
    hasRun: false,
    ...overrides,
  };
}

describe("PromptPreviewButton", () => {
  it("renders Preview in the idle state", () => {
    render(<PromptPreviewButton preview={makePreview()} />);
    expect(screen.getByRole("button", { name: /^preview$/i })).toBeInTheDocument();
  });

  it("calls run on click", async () => {
    const preview = makePreview();
    const user = userEvent.setup();
    render(<PromptPreviewButton preview={preview} />);
    await user.click(screen.getByRole("button", { name: /preview/i }));
    expect(preview.run).toHaveBeenCalledTimes(1);
  });

  it("renders Re-run after the first successful invocation", () => {
    render(<PromptPreviewButton preview={makePreview({ hasRun: true })} />);
    expect(screen.getByRole("button", { name: /re-run/i })).toBeInTheDocument();
  });

  it("disables and shows the rendering label while a request is in flight", () => {
    render(<PromptPreviewButton preview={makePreview({ isLoading: true })} />);
    const btn = screen.getByRole("button", { name: /rendering/i });
    expect(btn).toBeDisabled();
  });
});
