import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders as render } from "@/test/test-utils";
import { PromptSnippetTabs } from "./PromptSnippetTabs";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

// prism-react-renderer breaks the snippet across many <span> tokens, so
// getByText against the rendered string won't match — read the code
// element's full textContent instead.
function activeCode(): string {
  // Each tab renders a single <pre><code> inside the visible TabsContent.
  const pre = document.querySelector('[data-slot="tabs-content"][data-state="active"] pre');
  return pre?.textContent ?? "";
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("PromptSnippetTabs", () => {
  it("renders all four language tabs", () => {
    render(<PromptSnippetTabs promptName="greet" args={{}} />);
    expect(screen.getByRole("tab", { name: "curl" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "JSON-RPC" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Python" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "TypeScript" })).toBeInTheDocument();
  });

  it("defaults to the curl snippet on first render", () => {
    render(<PromptSnippetTabs promptName="greet" args={{ user: "Alice" }} />);
    expect(activeCode()).toContain("curl -X POST");
    expect(activeCode()).toContain('"user":"Alice"');
  });

  it("switches to the JSON-RPC snippet when its tab is activated", async () => {
    const user = userEvent.setup();
    render(<PromptSnippetTabs promptName="greet" args={{}} />);
    await user.click(screen.getByRole("tab", { name: "JSON-RPC" }));
    expect(activeCode()).toContain('"method": "prompts/get"');
  });

  it("copies the active snippet to the clipboard on click", async () => {
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
    render(<PromptSnippetTabs promptName="greet" args={{ user: "Alice" }} />);
    await user.click(screen.getByRole("button", { name: /copy curl snippet/i }));
    expect(writeText).toHaveBeenCalledTimes(1);
    expect(writeText.mock.calls[0][0]).toContain("curl -X POST");
    expect(writeText.mock.calls[0][0]).toContain('"user":"Alice"');
  });

  it("rebuilds the snippet when args change", () => {
    const { rerender } = render(<PromptSnippetTabs promptName="greet" args={{ user: "Alice" }} />);
    expect(activeCode()).toContain('"user":"Alice"');
    rerender(<PromptSnippetTabs promptName="greet" args={{ user: "Bob" }} />);
    expect(activeCode()).toContain('"user":"Bob"');
  });

  it("renders the trailing actions slot beside the tab list", () => {
    render(
      <PromptSnippetTabs
        promptName="greet"
        args={{}}
        actions={<button type="button">Preview</button>}
      />,
    );
    expect(screen.getByRole("button", { name: "Preview" })).toBeInTheDocument();
  });
});
