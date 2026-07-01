import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders as render } from "@/test/test-utils";
import { PromptCodeTab } from "./PromptCodeTab";
import { promptsApi } from "@/api/prompts";
import type { PromptRead } from "@/generated/types";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/api/prompts", () => ({
  promptsApi: { render: vi.fn() },
}));

function mockPrompt(overrides?: Partial<NonNullable<PromptRead>>): NonNullable<PromptRead> {
  return {
    id: "p1",
    name: "greet_user",
    originalName: "greet_user",
    customName: "",
    customNameSlug: "greet_user",
    description: null,
    template: "Hello {user_name}",
    arguments: [
      { name: "user_name", description: "Who to greet", required: true },
      { name: "tone", description: "Friendly or formal", required: false },
    ],
    createdAt: "2026-06-30T00:00:00",
    updatedAt: "2026-06-30T00:00:00",
    enabled: true,
    ...overrides,
  };
}

// Tokens render across many spans (prism-react-renderer), so the active
// snippet's full text is easier to read off the rendered <pre> element.
function activeCode(): string {
  const pre = document.querySelector('[data-slot="tabs-content"][data-state="active"] pre');
  return pre?.textContent ?? "";
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("PromptCodeTab", () => {
  it("renders the args form, the four snippet tabs, and the Preview button", () => {
    render(<PromptCodeTab prompt={mockPrompt()} />);
    expect(screen.getByLabelText(/user_name/)).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "curl" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "TypeScript" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^preview$/i })).toBeInTheDocument();
  });

  it("propagates arg changes into the live snippet", async () => {
    const user = userEvent.setup();
    render(<PromptCodeTab prompt={mockPrompt()} />);

    expect(activeCode()).toContain('"user_name":""');

    await user.type(screen.getByLabelText(/user_name/), "Alice");
    expect(activeCode()).toContain('"user_name":"Alice"');
  });

  it("passes the typed args to the render API on Preview", async () => {
    vi.mocked(promptsApi.render).mockResolvedValue({ messages: [] });
    const user = userEvent.setup();
    render(<PromptCodeTab prompt={mockPrompt()} />);

    await user.type(screen.getByLabelText(/user_name/), "Bob");
    await user.click(screen.getByRole("button", { name: /^preview$/i }));

    await waitFor(() =>
      expect(promptsApi.render).toHaveBeenCalledWith(
        "p1",
        expect.objectContaining({ user_name: "Bob" }),
      ),
    );
  });

  it("resets args when the selected prompt changes", () => {
    const { rerender } = render(<PromptCodeTab prompt={mockPrompt({ id: "p1" })} />);
    const input = screen.getByLabelText(/user_name/) as HTMLInputElement;
    input.focus();
    input.value = "Alice";
    input.dispatchEvent(new Event("input", { bubbles: true }));

    rerender(<PromptCodeTab prompt={mockPrompt({ id: "p2", name: "different_prompt" })} />);
    expect(activeCode()).toContain("different_prompt");
    expect((screen.getByLabelText(/user_name/) as HTMLInputElement).value).toBe("");
  });

  it("renders the empty-args message when the prompt declares no arguments", () => {
    render(<PromptCodeTab prompt={mockPrompt({ arguments: [] })} />);
    expect(screen.getByText(/no arguments/i)).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "curl" })).toBeInTheDocument();
  });
});
