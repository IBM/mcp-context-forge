import { describe, it, expect, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders as render } from "@/test/test-utils";
import { PromptDefinitionTable } from "./PromptDefinitionTable";
import type { PromptRead } from "@/generated/types";

function mockPrompt(overrides?: Partial<NonNullable<PromptRead>>): NonNullable<PromptRead> {
  return {
    id: "p1",
    name: "greet_user",
    originalName: "greet_user",
    customName: "",
    customNameSlug: "greet_user",
    description: "Greets the user",
    template: "Hello {user_name}",
    arguments: [],
    createdAt: "2026-06-30T00:00:00",
    updatedAt: "2026-06-30T00:00:00",
    enabled: true,
    ...overrides,
  };
}

describe("PromptDefinitionTable", () => {
  it("renders a row per prompt with its name and a copyable ID", () => {
    const a = mockPrompt({ id: "a", name: "prompt_a" });
    const b = mockPrompt({ id: "b", name: "prompt_b" });
    render(<PromptDefinitionTable prompts={[a, b]} onSelectPrompt={vi.fn()} />);

    expect(screen.getByRole("cell", { name: "prompt_a" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "prompt_b" })).toBeInTheDocument();
    expect(screen.getByText("a")).toBeInTheDocument();
    expect(screen.getByText("b")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /copy prompt id/i })).toHaveLength(2);
  });

  it("does not render a Source URL column", () => {
    render(<PromptDefinitionTable prompts={[mockPrompt()]} onSelectPrompt={vi.fn()} />);

    expect(screen.queryByRole("columnheader", { name: /source url/i })).not.toBeInTheDocument();
  });

  it("prefers displayName over the technical name for the Name column", () => {
    const prompt = mockPrompt({ displayName: "Greet User" });
    render(<PromptDefinitionTable prompts={[prompt]} onSelectPrompt={vi.fn()} />);

    expect(screen.getByRole("cell", { name: "Greet User" })).toBeInTheDocument();
  });

  it("calls onSelectPrompt with the row's prompt when the row is clicked", async () => {
    const onSelectPrompt = vi.fn();
    const user = userEvent.setup();
    const a = mockPrompt({ id: "a", name: "prompt_a" });
    const b = mockPrompt({ id: "b", name: "prompt_b" });
    render(<PromptDefinitionTable prompts={[a, b]} onSelectPrompt={onSelectPrompt} />);

    await user.click(screen.getByRole("cell", { name: "prompt_b" }));
    expect(onSelectPrompt).toHaveBeenCalledWith(b);
  });

  it("does not select the row when the copy button is clicked", async () => {
    const onSelectPrompt = vi.fn();
    const user = userEvent.setup();
    render(<PromptDefinitionTable prompts={[mockPrompt()]} onSelectPrompt={onSelectPrompt} />);

    await user.click(screen.getByRole("button", { name: /copy prompt id/i }));
    expect(onSelectPrompt).not.toHaveBeenCalled();
  });

  it("selects the row via keyboard, but not when a key fires from an in-row control", async () => {
    const onSelectPrompt = vi.fn();
    const user = userEvent.setup();
    render(<PromptDefinitionTable prompts={[mockPrompt()]} onSelectPrompt={onSelectPrompt} />);

    // Enter from the copy button must not bubble up into a row selection.
    screen.getByRole("button", { name: /copy prompt id/i }).focus();
    await user.keyboard("{Enter}");
    expect(onSelectPrompt).not.toHaveBeenCalled();

    // Enter on the row itself does select it.
    const dataRow = screen.getAllByRole("row")[1];
    dataRow.focus();
    await user.keyboard("{Enter}");
    expect(onSelectPrompt).toHaveBeenCalledTimes(1);
  });

  it("omits the row overflow menu when neither onEdit nor onDelete is provided", () => {
    render(<PromptDefinitionTable prompts={[mockPrompt()]} onSelectPrompt={vi.fn()} />);

    expect(screen.queryByRole("button", { name: /more options/i })).not.toBeInTheDocument();
  });

  it("invokes onEdit and onDelete with the row's prompt from the overflow menu", async () => {
    const onEdit = vi.fn();
    const onDelete = vi.fn();
    const onSelectPrompt = vi.fn();
    const user = userEvent.setup();
    const prompt = mockPrompt();
    render(
      <PromptDefinitionTable
        prompts={[prompt]}
        onSelectPrompt={onSelectPrompt}
        onEdit={onEdit}
        onDelete={onDelete}
      />,
    );

    await user.click(screen.getByRole("button", { name: /more options for greet_user/i }));
    await user.click(screen.getByRole("menuitem", { name: /^edit$/i }));
    expect(onEdit).toHaveBeenCalledWith(prompt);

    await user.click(screen.getByRole("button", { name: /more options for greet_user/i }));
    await user.click(screen.getByRole("menuitem", { name: /^delete$/i }));
    expect(onDelete).toHaveBeenCalledWith(prompt);

    // Opening the menu / picking an action must not also select the row.
    expect(onSelectPrompt).not.toHaveBeenCalled();
  });

  it("renders only the actions provided", async () => {
    const user = userEvent.setup();
    render(
      <PromptDefinitionTable prompts={[mockPrompt()]} onSelectPrompt={vi.fn()} onEdit={vi.fn()} />,
    );

    await user.click(screen.getByRole("button", { name: /more options for greet_user/i }));
    const menu = screen.getByRole("menu");
    expect(within(menu).getByRole("menuitem", { name: /^edit$/i })).toBeInTheDocument();
    expect(within(menu).queryByRole("menuitem", { name: /^delete$/i })).not.toBeInTheDocument();
  });
});
