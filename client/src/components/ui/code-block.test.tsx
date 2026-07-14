import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CodeBlock } from "./code-block";

describe("CodeBlock", () => {
  it("renders the supplied code", () => {
    render(<CodeBlock code='{"a":1}' language="json" />);
    expect(screen.getByText('"a"')).toBeInTheDocument();
  });

  it("invokes onCopy with the raw code when the copy button is clicked", async () => {
    const user = userEvent.setup();
    const onCopy = vi.fn();
    render(<CodeBlock code="hello world" language="bash" copyLabel="bash" onCopy={onCopy} />);
    await user.click(screen.getByRole("button", { name: /bash/i }));
    expect(onCopy).toHaveBeenCalledWith("hello world");
  });

  it("copies to the clipboard and shows a tooltip when copiedLabel is set", async () => {
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
    render(<CodeBlock code="hello world" language="bash" copyLabel="bash" copiedLabel="Copied!" />);
    await user.click(screen.getByRole("button", { name: /bash/i }));
    expect(writeText).toHaveBeenCalledWith("hello world");
    expect(screen.getByRole("tooltip")).toHaveTextContent("Copied!");
  });

  it("hides the copy button when hideCopy is set", () => {
    render(<CodeBlock code="x" language="json" hideCopy />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("falls back to a generic aria-label when no copyLabel is supplied", () => {
    render(<CodeBlock code="x" language="json" />);
    expect(screen.getByRole("button", { name: /copy code/i })).toBeInTheDocument();
  });
});
