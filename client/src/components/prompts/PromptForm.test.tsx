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
  },
}));

vi.mock("@/auth/AuthContext", () => ({
  useAuthContext: vi.fn(),
}));

const mockPost = vi.mocked(api.post);
const mockUseAuthContext = vi.mocked(useAuthContext);

function renderPromptForm(props?: { onToggle?: () => void; onSuccess?: () => void }) {
  return renderWithProviders(
    <PromptForm
      isOpen={true}
      onToggle={props?.onToggle ?? vi.fn()}
      onSuccess={props?.onSuccess ?? vi.fn()}
    />,
  );
}

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
            team_id: null,
          },
          team_id: null,
          visibility: "public",
        },
        expect.objectContaining({ signal: expect.any(Object) }),
      );
    });
    expect(onSuccess).toHaveBeenCalled();
  });

  it("renders required field errors after submit", async () => {
    renderPromptForm();

    await userEvent.setup().click(screen.getByRole("button", { name: "Add prompt" }));

    expect(screen.getByText("Name is required")).toBeInTheDocument();
    expect(screen.getByText("Template is required")).toBeInTheDocument();
    expect(mockPost).not.toHaveBeenCalled();
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
