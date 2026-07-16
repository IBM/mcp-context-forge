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
  it("renders the group title and the first prompt's Code tab when open", () => {
    render(
      <PromptDetailsPanel
        prompts={[mockPrompt()]}
        title="hugging-face"
        open={true}
        onClose={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("heading", { name: /prompt details: hugging-face/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("Greets the user")).toBeInTheDocument();
    expect(screen.getByLabelText(/user_name/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^preview$/i })).toBeInTheDocument();
  });

  it("marks the region as hidden and inert when closed", () => {
    render(
      <PromptDetailsPanel
        prompts={[mockPrompt()]}
        title="hugging-face"
        open={false}
        onClose={vi.fn()}
      />,
    );

    const region = screen.getByRole("region", { hidden: true });
    expect(region).toHaveAttribute("aria-hidden", "true");
    expect(region).toHaveAttribute("inert");
    expect(region).toHaveAttribute("data-state", "closed");
  });

  it("fires onClose when Escape is pressed", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(
      <PromptDetailsPanel
        prompts={[mockPrompt()]}
        title="hugging-face"
        open={true}
        onClose={onClose}
      />,
    );

    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("fires onClose when the backdrop is clicked", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(
      <PromptDetailsPanel
        prompts={[mockPrompt()]}
        title="hugging-face"
        open={true}
        onClose={onClose}
      />,
    );

    // The overlay is the aria-hidden sibling behind the aside.
    const overlay = document.querySelector('[data-state="open"][aria-hidden="true"]');
    expect(overlay).not.toBeNull();
    await user.click(overlay as Element);
    expect(onClose).toHaveBeenCalled();
  });

  it("fires onClose when the close button is activated", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(
      <PromptDetailsPanel
        prompts={[mockPrompt()]}
        title="hugging-face"
        open={true}
        onClose={onClose}
      />,
    );

    await user.click(screen.getByRole("button", { name: /close prompt details/i }));
    expect(onClose).toHaveBeenCalled();
  });

  it("keeps the group title in the heading and swaps the Code tab when a pill is picked", async () => {
    const user = userEvent.setup();
    const promptA = mockPrompt({ id: "a", name: "prompt_a", description: "First" });
    const promptB = mockPrompt({
      id: "b",
      name: "prompt_b",
      description: "Second",
      arguments: [{ name: "topic", description: "Topic", required: true }],
    });
    render(
      <PromptDetailsPanel
        prompts={[promptA, promptB]}
        title="hugging-face"
        open={true}
        onClose={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("heading", { name: /prompt details: hugging-face/i }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/user_name/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "prompt_b" }));

    expect(
      screen.getByRole("heading", { name: /prompt details: hugging-face/i }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/topic/)).toBeInTheDocument();
  });

  it("honors initialPromptId when opening", () => {
    const promptA = mockPrompt({ id: "a", name: "prompt_a" });
    const promptB = mockPrompt({
      id: "b",
      name: "prompt_b",
      description: "Second",
      arguments: [{ name: "topic", description: "Topic", required: true }],
    });
    render(
      <PromptDetailsPanel
        prompts={[promptA, promptB]}
        title="hugging-face"
        initialPromptId="b"
        open={true}
        onClose={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("heading", { name: /prompt details: hugging-face/i }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/topic/)).toBeInTheDocument();
  });

  it("renders a local subheader with source, visibility, and argument count for prompts without a gateway", () => {
    const local = mockPrompt({
      visibility: "public",
      arguments: [
        { name: "topic", description: "", required: true },
        { name: "audience", description: "", required: false },
        { name: "tone", description: "", required: false },
      ],
    });
    render(
      <PromptDetailsPanel prompts={[local]} title="REST prompts" open={true} onClose={vi.fn()} />,
    );

    expect(screen.getByText("Local prompt · public · 3 arguments")).toBeInTheDocument();
    expect(screen.queryByText(/connected MCP server/i)).not.toBeInTheDocument();
  });

  it("renders the singular federated subheader when the group has exactly one prompt", () => {
    const federated = mockPrompt({ gatewaySlug: "hugging-face" });
    render(
      <PromptDetailsPanel
        prompts={[federated]}
        title="hugging-face"
        open={true}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText("Prompt added from connected MCP server")).toBeInTheDocument();
    expect(screen.queryByText(/local prompt/i)).not.toBeInTheDocument();
  });

  it("renders the plural federated subheader when the group has more than one prompt", () => {
    const a = mockPrompt({ id: "a", name: "prompt_a", gatewaySlug: "hugging-face" });
    const b = mockPrompt({ id: "b", name: "prompt_b", gatewaySlug: "hugging-face" });
    render(
      <PromptDetailsPanel prompts={[a, b]} title="hugging-face" open={true} onClose={vi.fn()} />,
    );

    expect(screen.getByText("Prompts added from connected MCP server")).toBeInTheDocument();
  });

  it("hides the prompt-picker pill row when the group has exactly one prompt", () => {
    render(
      <PromptDetailsPanel
        prompts={[mockPrompt()]}
        title="hugging-face"
        open={true}
        onClose={vi.fn()}
      />,
    );

    expect(screen.queryByRole("group", { name: /select prompt/i })).not.toBeInTheDocument();
  });

  it("shows the prompt-picker pill row when the group has more than one prompt", () => {
    const a = mockPrompt({ id: "a", name: "prompt_a" });
    const b = mockPrompt({ id: "b", name: "prompt_b" });
    render(<PromptDetailsPanel prompts={[a, b]} title="group" open={true} onClose={vi.fn()} />);

    expect(screen.getByRole("group", { name: /select prompt/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "prompt_a", pressed: true })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "prompt_b", pressed: false })).toBeInTheDocument();
  });

  it("singularizes the local subheader when the prompt has exactly one argument", () => {
    const local = mockPrompt({
      visibility: "private",
      arguments: [{ name: "topic", description: "", required: true }],
    });
    render(
      <PromptDetailsPanel prompts={[local]} title="REST prompts" open={true} onClose={vi.fn()} />,
    );

    expect(screen.getByText("Local prompt · private · 1 argument")).toBeInTheDocument();
  });

  it("calls onAddTag with the merged, de-duplicated tag list", async () => {
    const user = userEvent.setup();
    const onAddTag = vi.fn().mockResolvedValue(undefined);
    const prompt = mockPrompt({ id: "p1", tags: [{ id: "dev", label: "dev" }] });

    render(
      <PromptDetailsPanel
        prompts={[prompt]}
        title="hugging-face"
        open={true}
        onClose={vi.fn()}
        onAddTag={onAddTag}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Add tags" }));
    await user.type(screen.getByPlaceholderText("Add tags separated with commas"), "alerts, dev");
    await user.click(screen.getByRole("button", { name: "Add" }));

    // "dev" already exists and is dropped; "alerts" is appended.
    expect(onAddTag).toHaveBeenCalledWith("p1", ["dev", "alerts"]);
  });
});
