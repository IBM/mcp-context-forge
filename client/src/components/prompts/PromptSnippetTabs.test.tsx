import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders as render } from "@/test/test-utils";
import { PromptSnippetTabs } from "./PromptSnippetTabs";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

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
    const visible = screen.getByText(/curl -X POST/, { exact: false });
    expect(visible).toBeInTheDocument();
    expect(visible.textContent).toContain('"user":"Alice"');
  });

  it("switches to the JSON-RPC snippet when its tab is activated", async () => {
    const user = userEvent.setup();
    render(<PromptSnippetTabs promptName="greet" args={{}} />);
    await user.click(screen.getByRole("tab", { name: "JSON-RPC" }));
    const panel = screen.getByText(/"method": "prompts\/get"/);
    expect(panel).toBeInTheDocument();
  });

  it("copies the active snippet to the clipboard on click", async () => {
    // jsdom defines navigator.clipboard via a getter (newer userEvent ships
    // its own shim too), so plain defineProperty(value) is silently ignored —
    // spy directly on the existing method instead.
    const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();

    const user = userEvent.setup();
    render(<PromptSnippetTabs promptName="greet" args={{ user: "Alice" }} />);
    await user.click(screen.getByRole("button", { name: /copy curl snippet/i }));
    expect(writeText).toHaveBeenCalledTimes(1);
    expect(writeText.mock.calls[0][0]).toContain("curl -X POST");
    expect(writeText.mock.calls[0][0]).toContain('"user":"Alice"');
  });

  it("rebuilds the snippet when args change", () => {
    const { rerender } = render(
      <PromptSnippetTabs promptName="greet" args={{ user: "Alice" }} />,
    );
    expect(screen.getByText(/"user":"Alice"/)).toBeInTheDocument();
    rerender(<PromptSnippetTabs promptName="greet" args={{ user: "Bob" }} />);
    expect(screen.getByText(/"user":"Bob"/)).toBeInTheDocument();
  });

  it("renders the endpoint + auth footer with the env-var literals", () => {
    render(<PromptSnippetTabs promptName="greet" args={{}} />);
    // Footer is rendered per-tab; expect at least one match.
    const footers = screen.getAllByText(/\$MCPGATEWAY_URL/);
    expect(footers.length).toBeGreaterThan(0);
    expect(screen.getAllByText("$MCPGATEWAY_BEARER_TOKEN").length).toBeGreaterThan(0);
  });
});
