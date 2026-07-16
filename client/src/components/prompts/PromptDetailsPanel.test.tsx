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

  it("shows Try it and Definition tabs, with Try it (preview) active by default", async () => {
    const user = userEvent.setup();
    render(
      <PromptDetailsPanel
        prompts={[mockPrompt()]}
        title="hugging-face"
        open={true}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByRole("tab", { name: /try it/i })).toHaveAttribute("data-state", "active");
    expect(screen.getByRole("button", { name: /^preview$/i })).toBeInTheDocument();

    // Definition tab reveals the prompt table with its columns.
    await user.click(screen.getByRole("tab", { name: /definition/i }));
    expect(screen.getByRole("columnheader", { name: /^name$/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /prompt id/i })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: /source url/i })).not.toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "greet_user" })).toBeInTheDocument();
  });

  it("resets to the Try it tab each time the panel is reopened", async () => {
    const user = userEvent.setup();
    const props = {
      prompts: [mockPrompt()],
      title: "hugging-face",
      onClose: vi.fn(),
    };
    const { rerender } = render(<PromptDetailsPanel {...props} open={true} />);

    // Switch to Definition, then close and reopen the panel.
    await user.click(screen.getByRole("tab", { name: /definition/i }));
    expect(screen.getByRole("tab", { name: /definition/i })).toHaveAttribute(
      "data-state",
      "active",
    );

    rerender(<PromptDetailsPanel {...props} open={false} />);
    rerender(<PromptDetailsPanel {...props} open={true} />);

    expect(screen.getByRole("tab", { name: /try it/i })).toHaveAttribute("data-state", "active");
  });

  it("updates the Prompt details sidebar when a Definition table row is selected", async () => {
    const user = userEvent.setup();
    const publicPrompt = mockPrompt({ id: "a", name: "prompt_a", visibility: "public" });
    const privatePrompt = mockPrompt({ id: "b", name: "prompt_b", visibility: "private" });
    render(
      <PromptDetailsPanel
        prompts={[publicPrompt, privatePrompt]}
        title="hugging-face"
        open={true}
        onClose={vi.fn()}
      />,
    );

    // First prompt is selected initially; the sidebar shows its visibility.
    expect(screen.getByText("Public")).toBeInTheDocument();
    expect(screen.queryByText("Private")).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /definition/i }));
    await user.click(screen.getByRole("cell", { name: "prompt_b" }));

    // Sidebar now reflects the row that was picked.
    expect(screen.getByText("Private")).toBeInTheDocument();
    expect(screen.queryByText("Public")).not.toBeInTheDocument();
  });

  it("keeps the panel title free of an overflow menu (moved to the table)", () => {
    render(
      <PromptDetailsPanel
        prompts={[mockPrompt()]}
        title="hugging-face"
        open={true}
        onClose={vi.fn()}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    // The Try it tab is active; no row menu is rendered until Definition is opened.
    expect(screen.queryByRole("button", { name: /more options/i })).not.toBeInTheDocument();
  });

  it("renders a row overflow menu in the Definition table when onEdit is provided", async () => {
    const user = userEvent.setup();
    render(
      <PromptDetailsPanel
        prompts={[mockPrompt()]}
        title="hugging-face"
        open={true}
        onClose={vi.fn()}
        onEdit={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("tab", { name: /definition/i }));
    expect(
      screen.getByRole("button", { name: /more options for greet_user/i }),
    ).toBeInTheDocument();
  });

  it("does not render a row overflow menu when neither onEdit nor onDelete is provided", async () => {
    const user = userEvent.setup();
    render(
      <PromptDetailsPanel
        prompts={[mockPrompt()]}
        title="hugging-face"
        open={true}
        onClose={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("tab", { name: /definition/i }));
    expect(screen.queryByRole("button", { name: /more options/i })).not.toBeInTheDocument();
  });

  it("calls onEdit with the row's prompt when Edit is clicked in the Definition table", async () => {
    const onEdit = vi.fn();
    const user = userEvent.setup();
    const prompt = mockPrompt();
    render(
      <PromptDetailsPanel
        prompts={[prompt]}
        title="hugging-face"
        open={true}
        onClose={vi.fn()}
        onEdit={onEdit}
      />,
    );

    await user.click(screen.getByRole("tab", { name: /definition/i }));
    await user.click(screen.getByRole("button", { name: /more options for greet_user/i }));
    await user.click(screen.getByRole("menuitem", { name: /^edit$/i }));
    expect(onEdit).toHaveBeenCalledWith(prompt);
  });

  it("calls onDelete with the row's prompt when Delete is clicked in the Definition table", async () => {
    const onDelete = vi.fn();
    const user = userEvent.setup();
    const prompt = mockPrompt();
    render(
      <PromptDetailsPanel
        prompts={[prompt]}
        title="hugging-face"
        open={true}
        onClose={vi.fn()}
        onDelete={onDelete}
      />,
    );

    await user.click(screen.getByRole("tab", { name: /definition/i }));
    await user.click(screen.getByRole("button", { name: /more options for greet_user/i }));
    await user.click(screen.getByRole("menuitem", { name: /^delete$/i }));
    expect(onDelete).toHaveBeenCalledWith(prompt);
  });

  it("renders Technical name and Prompt ID with copy buttons", () => {
    render(
      <PromptDetailsPanel
        prompts={[mockPrompt()]}
        title="hugging-face"
        open={true}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText("Technical name")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /copy technical name/i })).toBeInTheDocument();
    expect(screen.getByText("Prompt ID")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /copy prompt id/i })).toBeInTheDocument();
  });

  it("renders Source URL with copy button when federationSource is set", () => {
    const prompt = mockPrompt({ federationSource: "https://mcp.example.com/prompts" });
    render(<PromptDetailsPanel prompts={[prompt]} title="test" open={true} onClose={vi.fn()} />);

    expect(screen.getByText("Source URL")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /copy source url/i })).toBeInTheDocument();
  });

  it("omits Source URL when federationSource is not set", () => {
    render(
      <PromptDetailsPanel prompts={[mockPrompt()]} title="test" open={true} onClose={vi.fn()} />,
    );

    expect(screen.queryByText("Source URL")).not.toBeInTheDocument();
  });

  it("renders Version when version is set", () => {
    const prompt = mockPrompt({ version: 3 });
    render(<PromptDetailsPanel prompts={[prompt]} title="test" open={true} onClose={vi.fn()} />);

    expect(screen.getByText("Version")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("omits Version when version is null", () => {
    const prompt = mockPrompt({ version: null });
    render(<PromptDetailsPanel prompts={[prompt]} title="test" open={true} onClose={vi.fn()} />);

    expect(screen.queryByText("Version")).not.toBeInTheDocument();
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
