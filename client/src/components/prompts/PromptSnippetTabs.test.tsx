import { useState, type ReactNode } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders as render } from "@/test/test-utils";
import { PromptSnippetTabs } from "./PromptSnippetTabs";

// prism-react-renderer breaks the snippet across many <span> tokens, so
// getByText against the rendered string won't match — read the code
// element's full textContent instead.
function activeCode(): string {
  // Each tab renders a single <pre><code> inside the visible TabsContent.
  const pre = document.querySelector('[data-slot="tabs-content"][data-state="active"] pre');
  return pre?.textContent ?? "";
}

// Thin wrapper that supplies the controlled `value` + `onValueChange` — most
// tests only care about the snippet behavior, not the wiring, so keep the
// controller boilerplate out of each case.
function ControlledSnippetTabs(props: {
  promptName: string;
  args: Record<string, string>;
  actions?: ReactNode;
  onChange?: (value: string) => void;
  initialValue?: string;
}) {
  const [value, setValue] = useState(props.initialValue ?? "curl");
  return (
    <PromptSnippetTabs
      promptName={props.promptName}
      args={props.args}
      value={value}
      onValueChange={(next) => {
        props.onChange?.(next);
        setValue(next);
      }}
      actions={props.actions}
    />
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("PromptSnippetTabs", () => {
  it("renders all four language tabs", () => {
    render(<ControlledSnippetTabs promptName="greet" args={{}} />);
    expect(screen.getByRole("tab", { name: "curl" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "JSON-RPC" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Python" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "TypeScript" })).toBeInTheDocument();
  });

  it("shows the curl snippet when the controlled value is 'curl'", () => {
    render(<ControlledSnippetTabs promptName="greet" args={{ user: "Alice" }} />);
    expect(activeCode()).toContain("curl -X POST");
    expect(activeCode()).toContain('"user":"Alice"');
  });

  it("switches to the JSON-RPC snippet when its tab is activated", async () => {
    const user = userEvent.setup();
    render(<ControlledSnippetTabs promptName="greet" args={{}} />);
    await user.click(screen.getByRole("tab", { name: "JSON-RPC" }));
    expect(activeCode()).toContain('"method": "prompts/get"');
  });

  it("calls onValueChange with the newly-activated language", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<ControlledSnippetTabs promptName="greet" args={{}} onChange={onChange} />);
    await user.click(screen.getByRole("tab", { name: "Python" }));
    expect(onChange).toHaveBeenCalledWith("python");
  });

  it("copies the active snippet to the clipboard on click", async () => {
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
    render(<ControlledSnippetTabs promptName="greet" args={{ user: "Alice" }} />);
    await user.click(screen.getByRole("button", { name: /copy curl snippet/i }));
    expect(writeText).toHaveBeenCalledTimes(1);
    expect(writeText.mock.calls[0][0]).toContain("curl -X POST");
    expect(writeText.mock.calls[0][0]).toContain('"user":"Alice"');
    expect(screen.getByRole("tooltip")).toHaveTextContent("Copied!");
  });

  it("rebuilds the snippet when args change", () => {
    const { rerender } = render(
      <ControlledSnippetTabs promptName="greet" args={{ user: "Alice" }} />,
    );
    expect(activeCode()).toContain('"user":"Alice"');
    rerender(<ControlledSnippetTabs promptName="greet" args={{ user: "Bob" }} />);
    expect(activeCode()).toContain('"user":"Bob"');
  });

  it("renders the trailing actions slot beside the tab list", () => {
    render(
      <ControlledSnippetTabs
        promptName="greet"
        args={{}}
        actions={<button type="button">Preview</button>}
      />,
    );
    expect(screen.getByRole("button", { name: "Preview" })).toBeInTheDocument();
  });
});
