import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders as render } from "@/test/test-utils";
import { CodeBlock } from "./code-block";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

describe("CodeBlock", () => {
  it("renders the supplied code", () => {
    render(<CodeBlock code='{"a":1}' language="json" />);
    expect(screen.getByText('"a"')).toBeInTheDocument();
  });

  it("shows a copy button by default and copies the raw code", async () => {
    // userEvent.setup() initializes the jsdom clipboard, so spy after it.
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
    render(<CodeBlock code="hello world" language="bash" copyLabel="bash" />);
    await user.click(screen.getByRole("button", { name: /copy bash/i }));
    expect(writeText).toHaveBeenCalledWith("hello world");
  });

  it("hides the copy button when hideCopy is set", () => {
    render(<CodeBlock code="x" language="json" hideCopy />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("falls back to the generic copy aria-label when no copyLabel is given", () => {
    render(<CodeBlock code="x" language="json" />);
    expect(screen.getByRole("button", { name: /copy snippet/i })).toBeInTheDocument();
  });
});
