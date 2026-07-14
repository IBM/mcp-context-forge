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
  it("renders nothing when the schema has no declared args", () => {
    const { container } = render(<PromptArgsForm args={{}} schema={[]} onChange={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("ignores null entries in the schema (orval emits them)", () => {
    const { container } = render(<PromptArgsForm args={{}} schema={[null]} onChange={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders one input per declared arg and marks required ones with an asterisk", () => {
    render(
      <PromptArgsForm
        args={{}}
        schema={[arg("user_name", true), arg("tone")]}
        onChange={vi.fn()}
      />,
    );
    const requiredInput = screen.getByLabelText(/user_name/);
    const optionalInput = screen.getByLabelText(/tone/);
    expect(requiredInput).toBeInTheDocument();
    expect(optionalInput).toBeInTheDocument();

    expect(requiredInput).toHaveAccessibleName(/user_name.*required/i);
    expect(optionalInput).toHaveAccessibleName(/^tone$/);

    expect(screen.queryByText("Optional")).not.toBeInTheDocument();
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

  it("uses the description as the placeholder (lowercased, no e.g. prefix) when no examples are present", () => {
    render(
      <PromptArgsForm
        args={{}}
        schema={[arg("user_name", true, "The user to greet")]}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByPlaceholderText("the user to greet")).toBeInTheDocument();
    expect(screen.queryByText("The user to greet")).not.toBeInTheDocument();
  });

  it("extracts only the e.g. portion of the description when present", () => {
    render(
      <PromptArgsForm
        args={{}}
        schema={[arg("document_type", true, "Kind of document - e.g. report, RFC, memo")]}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByPlaceholderText("e.g. report, RFC, memo")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/Kind of document/)).not.toBeInTheDocument();
  });

  it("stops at the matching close-paren when e.g. is inside a parenthetical", () => {
    render(
      <PromptArgsForm
        args={{}}
        schema={[arg("model_id", true, "Model ID (e.g. 'openai/gpt-oss-120b'). Required.")]}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByPlaceholderText("e.g. 'openai/gpt-oss-120b'")).toBeInTheDocument();
  });

  it("handles nested parens inside the parenthetical without truncating early", () => {
    render(
      <PromptArgsForm
        args={{}}
        schema={[arg("scope", true, "Filter scope (e.g. 'kind(pod)' or 'ns(default)')")]}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByPlaceholderText("e.g. 'kind(pod)' or 'ns(default)'")).toBeInTheDocument();
  });

  it("lowercases a leading capital E.g. so the placeholder reads as lowercase", () => {
    render(
      <PromptArgsForm
        args={{}}
        schema={[arg("audience", true, "E.g. executives, engineers")]}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByPlaceholderText("e.g. executives, engineers")).toBeInTheDocument();
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
