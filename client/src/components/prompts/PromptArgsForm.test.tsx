import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders as render } from "@/test/test-utils";
import { PromptArgsForm } from "./PromptArgsForm";
import type { PromptArgument } from "@/generated/types";

function arg(name: string, required = false, description?: string): NonNullable<PromptArgument> {
  return { name, required, description };
}

describe("PromptArgsForm", () => {
  it("renders the empty-state message when the schema has no declared args", () => {
    render(<PromptArgsForm args={{}} schema={[]} onChange={vi.fn()} />);
    expect(screen.getByText(/no arguments/i)).toBeInTheDocument();
  });

  it("ignores null entries in the schema (orval emits them)", () => {
    render(<PromptArgsForm args={{}} schema={[null]} onChange={vi.fn()} />);
    expect(screen.getByText(/no arguments/i)).toBeInTheDocument();
  });

  it("renders one input per declared arg with required/optional badge", () => {
    render(
      <PromptArgsForm
        args={{}}
        schema={[arg("user_name", true), arg("tone")]}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByLabelText(/user_name/)).toBeInTheDocument();
    expect(screen.getByLabelText(/tone/)).toBeInTheDocument();
    expect(screen.getByText("Required")).toBeInTheDocument();
    expect(screen.getByText("Optional")).toBeInTheDocument();
  });

  it("emits the full args record on every change", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <PromptArgsForm
        args={{ user_name: "Al" }}
        schema={[arg("user_name", true), arg("tone")]}
        onChange={onChange}
      />,
    );
    await user.type(screen.getByLabelText(/tone/), "f");
    expect(onChange).toHaveBeenCalledWith({ user_name: "Al", tone: "f" });
  });

  it("displays the arg description when present", () => {
    render(
      <PromptArgsForm
        args={{}}
        schema={[arg("user_name", true, "The user to greet")]}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByText("The user to greet")).toBeInTheDocument();
  });

  it("marks required inputs with aria-required", () => {
    render(
      <PromptArgsForm
        args={{}}
        schema={[arg("user_name", true), arg("tone")]}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByLabelText(/user_name/)).toHaveAttribute("aria-required", "true");
    expect(screen.getByLabelText(/tone/)).toHaveAttribute("aria-required", "false");
  });
});
