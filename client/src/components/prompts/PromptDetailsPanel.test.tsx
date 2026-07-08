import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders as render } from "@/test/test-utils";
import { PromptDetailsPanel } from "./PromptDetailsPanel";
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
    description: "Greets the user",
    template: "Hello {user_name}",
    arguments: [{ name: "user_name", description: "Who to greet", required: true }],
    createdAt: "2026-06-30T00:00:00",
    updatedAt: "2026-06-30T00:00:00",
    enabled: true,
    ...overrides,
  };
}

describe("PromptDetailsPanel", () => {
  it("renders the first prompt's name and Code tab when open", () => {
    render(<PromptDetailsPanel prompts={[mockPrompt()]} open={true} onClose={vi.fn()} />);

    expect(
      screen.getByRole("heading", { name: /prompt details: greet_user/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("Greets the user")).toBeInTheDocument();
    expect(screen.getByLabelText(/user_name/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^preview$/i })).toBeInTheDocument();
  });

  it("marks the region as hidden when closed", () => {
    render(<PromptDetailsPanel prompts={[mockPrompt()]} open={false} onClose={vi.fn()} />);

    const region = screen.getByRole("region", { hidden: true });
    expect(region).toHaveAttribute("aria-hidden", "true");
    expect(region).toHaveAttribute("data-state", "closed");
  });

  it("fires onClose when Escape is pressed", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<PromptDetailsPanel prompts={[mockPrompt()]} open={true} onClose={onClose} />);

    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("fires onClose when the backdrop is clicked", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<PromptDetailsPanel prompts={[mockPrompt()]} open={true} onClose={onClose} />);

    // The overlay is the aria-hidden sibling behind the aside.
    const overlay = document.querySelector('[data-state="open"][aria-hidden="true"]');
    expect(overlay).not.toBeNull();
    await user.click(overlay as Element);
    expect(onClose).toHaveBeenCalled();
  });

  it("fires onClose when the close button is activated", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<PromptDetailsPanel prompts={[mockPrompt()]} open={true} onClose={onClose} />);

    await user.click(screen.getByRole("button", { name: /close prompt details/i }));
    expect(onClose).toHaveBeenCalled();
  });

  it("switches the Code tab when a different prompt pill is picked", async () => {
    const user = userEvent.setup();
    const promptA = mockPrompt({ id: "a", name: "prompt_a", description: "First" });
    const promptB = mockPrompt({
      id: "b",
      name: "prompt_b",
      description: "Second",
      arguments: [{ name: "topic", description: "Topic", required: true }],
    });
    render(<PromptDetailsPanel prompts={[promptA, promptB]} open={true} onClose={vi.fn()} />);

    expect(screen.getByRole("heading", { name: /prompt details: prompt_a/i })).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "prompt_b" }));

    expect(screen.getByRole("heading", { name: /prompt details: prompt_b/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/topic/)).toBeInTheDocument();
  });

  it("honors initialPromptId when opening", () => {
    const promptA = mockPrompt({ id: "a", name: "prompt_a" });
    const promptB = mockPrompt({ id: "b", name: "prompt_b", description: "Second" });
    render(
      <PromptDetailsPanel
        prompts={[promptA, promptB]}
        initialPromptId="b"
        open={true}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByRole("heading", { name: /prompt details: prompt_b/i })).toBeInTheDocument();
  });
});
