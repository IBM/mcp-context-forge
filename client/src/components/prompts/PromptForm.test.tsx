import type { ComponentProps } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "@/api/client";
import { useAuthContext } from "@/auth/AuthContext";
import { renderWithProviders } from "@/test/test-utils";
import { PromptForm } from "./PromptForm";

vi.mock("@/api/client", () => ({
  api: {
    post: vi.fn(),
    put: vi.fn(),
  },
}));

vi.mock("@/auth/AuthContext", () => ({
  useAuthContext: vi.fn(),
}));

const mockPost = vi.mocked(api.post);
const mockPut = vi.mocked(api.put);
const mockUseAuthContext = vi.mocked(useAuthContext);

function renderPromptForm(props?: {
  onToggle?: () => void;
  onSuccess?: () => void;
  prompt?: ComponentProps<typeof PromptForm>["prompt"];
}) {
  return renderWithProviders(
    <PromptForm
      isOpen={true}
      onToggle={props?.onToggle ?? vi.fn()}
      onSuccess={props?.onSuccess ?? vi.fn()}
      prompt={props?.prompt}
    />,
  );
}

const editablePrompt = {
  id: "prompt-1",
  name: "existing_prompt",
  originalName: "existing_prompt",
  customName: "existing_prompt",
  customNameSlug: "existing-prompt",
  displayName: "Existing prompt",
  description: "An existing prompt",
  template: "Hello {{ name }}",
  arguments: [],
  createdAt: "2024-01-01T00:00:00Z",
  updatedAt: "2024-01-01T00:00:00Z",
  enabled: true,
  tags: ["greeting"],
  visibility: "public",
} as unknown as NonNullable<ComponentProps<typeof PromptForm>["prompt"]>;

async function fillRequiredFields() {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText(/name/i), "Greeting prompt");
  fireEvent.change(screen.getByLabelText(/template/i), {
    target: { value: "Hello {{ name }}" },
  });
  return user;
}

describe("PromptForm", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockPost.mockReset();
    mockPut.mockReset();
    mockUseAuthContext.mockReturnValue({
      selectedTeamId: null,
      user: null,
      isAuthenticated: true,
      isLoading: false,
      login: vi.fn(),
      logout: vi.fn(),
      setSelectedTeamId: vi.fn(),
    });
  });

  it("renders nothing when isOpen is false", () => {
    renderWithProviders(<PromptForm isOpen={false} onToggle={vi.fn()} onSuccess={vi.fn()} />);
    expect(screen.queryByLabelText(/name/i)).not.toBeInTheDocument();
  });

  it("renders an accessible description field label", () => {
    renderPromptForm();

    expect(screen.getByLabelText("Description")).toBeInTheDocument();
  });

  it("programmatically marks required fields", () => {
    renderPromptForm();

    expect(screen.getByLabelText(/name/i)).toHaveAttribute("aria-required", "true");
    expect(screen.getByRole("combobox", { name: /visibility/i })).toHaveAttribute(
      "aria-required",
      "true",
    );
    expect(screen.getByLabelText(/template/i)).toHaveAttribute("aria-required", "true");
    expect(screen.getByLabelText(/description/i)).not.toHaveAttribute("aria-required");
    expect(screen.getByLabelText(/arguments/i)).not.toHaveAttribute("aria-required");
    expect(screen.getByLabelText(/tags/i)).not.toHaveAttribute("aria-required");
  });

  it("submits valid prompt data and calls onSuccess", async () => {
    const onSuccess = vi.fn();
    mockUseAuthContext.mockReturnValue({
      selectedTeamId: "team-123",
      user: null,
      isAuthenticated: true,
      isLoading: false,
      login: vi.fn(),
      logout: vi.fn(),
      setSelectedTeamId: vi.fn(),
    });
    mockPost.mockResolvedValue({
      id: "prompt-1",
      name: "Greeting prompt",
    });

    renderPromptForm({ onSuccess });
    const user = await fillRequiredFields();
    fireEvent.blur(screen.getByLabelText(/template/i));
    fireEvent.change(screen.getByLabelText("Description"), {
      target: { value: "Greets a person" },
    });
    await user.type(screen.getByLabelText(/tags/i), "greeting, example");
    await user.click(screen.getByRole("button", { name: "Add prompt" }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(
        "/prompts",
        {
          prompt: {
            name: "Greeting prompt",
            description: "Greets a person",
            template: "Hello {{ name }}",
            arguments: [],
            tags: ["greeting", "example"],
            visibility: "public",
            teamId: null,
          },
          team_id: null,
          visibility: "public",
        },
        expect.objectContaining({ signal: expect.any(Object) }),
      );
    });
    expect(onSuccess).toHaveBeenCalled();
  });

  it("disables the submit button when required fields are empty", () => {
    renderPromptForm();

    expect(screen.getByRole("button", { name: "Add prompt" })).toBeDisabled();
    expect(mockPost).not.toHaveBeenCalled();
  });

  it("enables the submit button once all required fields are filled", async () => {
    renderPromptForm();
    await fillRequiredFields();

    expect(screen.getByRole("button", { name: "Add prompt" })).toBeEnabled();
  });

  it("requires an active team when visibility is set to team", async () => {
    renderPromptForm();
    const user = await fillRequiredFields();

    await user.click(screen.getByRole("combobox", { name: /visibility/i }));
    await user.click(screen.getByRole("option", { name: /^Team$/i }));

    expect(
      screen.getByText("Please select a team using the team switcher in the sidebar"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Team selection is required when visibility is set to team"),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Add prompt" }));

    expect(mockPost).not.toHaveBeenCalled();
  });

  it("explains that team prompts use the currently selected sidebar team", async () => {
    mockUseAuthContext.mockReturnValue({
      selectedTeamId: "team-123",
      user: null,
      isAuthenticated: true,
      isLoading: false,
      login: vi.fn(),
      logout: vi.fn(),
      setSelectedTeamId: vi.fn(),
    });

    renderPromptForm();
    const user = userEvent.setup();

    await user.click(screen.getByRole("combobox", { name: /visibility/i }));
    await user.click(screen.getByRole("option", { name: /^Team$/i }));

    expect(
      screen.getByText("This prompt will be scoped to your currently selected team"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Team selection is required when visibility is set to team"),
    ).not.toBeInTheDocument();
  });

  it("calls onToggle when cancel is clicked", async () => {
    const onToggle = vi.fn();
    renderPromptForm({ onToggle });

    await userEvent.setup().click(screen.getByRole("button", { name: /cancel/i }));

    expect(onToggle).toHaveBeenCalled();
  });

  it("renders create failures inline in the form", async () => {
    const error = new Error("HTTP 400") as Error & { body?: unknown; status?: number };
    error.status = 400;
    error.body = { detail: "Prompt name already exists" };
    mockPost.mockRejectedValue(error);

    renderPromptForm();
    const user = await fillRequiredFields();
    await user.click(screen.getByRole("button", { name: "Add prompt" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Prompt name already exists");
  });

  it("renders in edit mode with prefilled values and updates via PUT", async () => {
    mockPut.mockResolvedValue({ id: "prompt-1", name: "existing_prompt" });
    const onSuccess = vi.fn();

    renderPromptForm({ prompt: editablePrompt, onSuccess });

    expect(screen.getByRole("heading", { name: "Edit prompt" })).toBeInTheDocument();
    expect(screen.getByLabelText(/name/i)).toHaveValue("existing_prompt");
    expect(screen.getByLabelText(/template/i)).toHaveValue("Hello {{ name }}");

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => {
      expect(mockPut).toHaveBeenCalledWith(
        "/prompts/prompt-1",
        expect.objectContaining({
          name: "existing_prompt",
          template: "Hello {{ name }}",
          visibility: "public",
        }),
      );
    });
    expect(mockPost).not.toHaveBeenCalled();
    expect(onSuccess).toHaveBeenCalled();
  });

  it("does not require the template when editing a federated prompt", async () => {
    mockPut.mockResolvedValue({ id: "prompt-2", name: "federated_prompt" });
    const federatedPrompt = {
      ...editablePrompt,
      id: "prompt-2",
      name: "federated_prompt",
      template: "",
      gatewayId: "gw-hugging-face",
      gatewaySlug: "hugging-face",
    } as unknown as NonNullable<ComponentProps<typeof PromptForm>["prompt"]>;

    renderPromptForm({ prompt: federatedPrompt });

    // The template field is optional: no aria-required, no required asterisk.
    expect(screen.getByLabelText(/template/i)).toHaveAttribute("aria-required", "false");

    // With an empty template the form still submits (federated prompts have none).
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => {
      expect(mockPut).toHaveBeenCalledWith(
        "/prompts/prompt-2",
        expect.objectContaining({ name: "federated_prompt", template: "" }),
      );
    });
  });

  it("revalidates argument errors while the field is edited", async () => {
    renderPromptForm();
    const argumentsField = screen.getByLabelText(/arguments/i);

    fireEvent.change(argumentsField, { target: { value: "{}" } });
    fireEvent.blur(argumentsField);

    expect(screen.getByText("Arguments must be a JSON array")).toBeInTheDocument();

    fireEvent.change(argumentsField, { target: { value: "{" } });

    expect(screen.getByText("Invalid JSON format")).toBeInTheDocument();

    fireEvent.change(argumentsField, { target: { value: "[]" } });

    await waitFor(() => {
      expect(screen.queryByText("Invalid JSON format")).not.toBeInTheDocument();
    });
  });
});
