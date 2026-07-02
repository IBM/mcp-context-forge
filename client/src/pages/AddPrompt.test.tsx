import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError } from "@/api/client";
import { promptsApi } from "@/api/prompts";
import { useAuthContext } from "@/auth/AuthContext";
import { RouterProvider } from "@/router";
import { renderWithProviders } from "@/test/test-utils";
import { AddPrompt } from "./AddPrompt";

vi.mock("@/api/prompts", () => ({
  promptsApi: {
    create: vi.fn(),
  },
}));

vi.mock("@/auth/AuthContext", () => ({
  useAuthContext: vi.fn(),
}));

const mockCreatePrompt = vi.mocked(promptsApi.create);
const mockUseAuthContext = vi.mocked(useAuthContext);

function renderAddPrompt() {
  window.history.pushState({}, "", "/app/prompts/add");
  return renderWithProviders(
    <RouterProvider>
      <AddPrompt />
    </RouterProvider>,
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

describe("AddPrompt", () => {
  beforeEach(() => {
    vi.clearAllMocks();
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

  it("submits valid prompt data and returns to the prompts page", async () => {
    mockUseAuthContext.mockReturnValue({
      selectedTeamId: "team-123",
      user: null,
      isAuthenticated: true,
      isLoading: false,
      login: vi.fn(),
      logout: vi.fn(),
      setSelectedTeamId: vi.fn(),
    });
    mockCreatePrompt.mockResolvedValue({
      id: "prompt-1",
      name: "Greeting prompt",
    });

    renderAddPrompt();
    const user = await fillRequiredFields();
    await user.click(screen.getByRole("button", { name: "Add Tool" }));

    await waitFor(() => {
      expect(mockCreatePrompt).toHaveBeenCalledWith({
        name: "Greeting prompt",
        visibility: "public",
        template: "Hello {{ name }}",
        arguments: "",
        description: "",
        tags: "",
        teamId: "team-123",
      });
    });
    expect(window.location.pathname).toBe("/app/prompts");
  });

  it("renders create failures inline in the form", async () => {
    mockCreatePrompt.mockRejectedValue(
      new ApiError(400, { detail: "Prompt name already exists" }, "HTTP 400"),
    );

    renderAddPrompt();
    const user = await fillRequiredFields();
    await user.click(screen.getByRole("button", { name: "Add Tool" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Prompt name already exists");
  });

  it("revalidates argument errors while the field is edited", async () => {
    renderAddPrompt();
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
