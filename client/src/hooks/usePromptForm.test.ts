import { createElement, type FormEvent, type ReactNode } from "react";
import { IntlProvider } from "react-intl";
import { act, renderHook as rtlRenderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/api/client";
import { useAuthContext } from "@/auth/AuthContext";
import enMessages from "@/i18n/locales/en-US";
import { usePromptForm } from "./usePromptForm";

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

const wrapper = ({ children }: { children: ReactNode }) =>
  createElement(
    IntlProvider,
    { locale: "en", defaultLocale: "en", messages: enMessages },
    children,
  );

const renderHook = <Result, Props>(render: (initialProps: Props) => Result) =>
  rtlRenderHook(render, { wrapper });

const fakeSubmit = (e?: Partial<FormEvent<HTMLFormElement>>) =>
  ({ preventDefault: vi.fn(), ...e }) as FormEvent<HTMLFormElement>;

function mockAuth(selectedTeamId: string | null = null) {
  mockUseAuthContext.mockReturnValue({
    selectedTeamId,
    user: null,
    isAuthenticated: true,
    isLoading: false,
    login: vi.fn(),
    logout: vi.fn(),
    setSelectedTeamId: vi.fn(),
  });
}

describe("usePromptForm", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockPost.mockReset();
    mockPut.mockReset();
    mockAuth();
  });

  it("initializes with empty fields and no errors", () => {
    const { result } = renderHook(() => usePromptForm());

    expect(result.current.name).toBe("");
    expect(result.current.visibility).toBe("public");
    expect(result.current.teamId).toBeUndefined();
    expect(result.current.template).toBe("");
    expect(result.current.arguments).toBe("");
    expect(result.current.description).toBe("");
    expect(result.current.tags).toBe("");
    expect(result.current.errors).toEqual({});
    expect(result.current.isSubmitting).toBe(false);
    expect(result.current.isValid).toBe(false);
  });

  it("sets zod validation errors for required fields", () => {
    const { result } = renderHook(() => usePromptForm());

    let valid: boolean;
    act(() => {
      valid = result.current.validateForm();
    });

    expect(valid!).toBe(false);
    expect(result.current.errors.name).toBe("Name is required");
    expect(result.current.errors.template).toBe("Template is required");
  });

  it("validates argument JSON with the zod schema", () => {
    const { result } = renderHook(() => usePromptForm());

    act(() => {
      result.current.setName("Greeting prompt");
      result.current.setTemplate("Hello {{ name }}");
      result.current.setArguments("{}");
    });

    act(() => {
      result.current.validateForm();
    });

    expect(result.current.errors.arguments).toBe("Arguments must be a JSON array");

    act(() => {
      result.current.setArguments("{");
    });

    expect(result.current.errors.arguments).toBe("Invalid JSON format");

    act(() => {
      result.current.setArguments("[]");
    });

    expect(result.current.errors.arguments).toBeUndefined();
  });

  it("returns true when required fields are filled", () => {
    const { result } = renderHook(() => usePromptForm());

    act(() => {
      result.current.setName("Greeting prompt");
      result.current.setTemplate("Hello {{ name }}");
    });

    let valid: boolean;
    act(() => {
      valid = result.current.validateForm();
    });

    expect(valid!).toBe(true);
    expect(result.current.errors).toEqual({});
  });

  it("sanitizes prompt metadata in the API payload", () => {
    const { result } = renderHook(() => usePromptForm());

    act(() => {
      result.current.setName(" Greeting\x0B prompt ");
      result.current.setTemplate("Hello {{ name }}");
      result.current.setDescription("desc\x1Fription");
      result.current.setTags(" greeting , ex\x00ample ");
    });

    const data = result.current.getFormData();
    expect(data.prompt.name).toBe("Greeting prompt");
    expect(data.prompt.description).toBe("description");
    expect(data.prompt.tags).toEqual(["greeting", "example"]);
  });

  it("truncates description exceeding 500 characters in the API payload", () => {
    const { result } = renderHook(() => usePromptForm());

    act(() => {
      result.current.setName("Greeting prompt");
      result.current.setTemplate("Hello {{ name }}");
      result.current.setDescription("a".repeat(501));
    });

    expect(result.current.isValid).toBe(true);
    expect(result.current.getFormData().prompt.description).toHaveLength(500);
  });

  it("shows a team visibility error immediately when no team is selected", () => {
    const { result } = renderHook(() => usePromptForm());

    act(() => {
      result.current.setName("Team prompt");
      result.current.setTemplate("Hello {{ name }}");
      result.current.setVisibility("team");
    });

    expect(result.current.errors.visibility).toBe(
      "Team selection is required when visibility is set to team",
    );
    expect(result.current.teamId).toBeUndefined();
  });

  it("clears the team visibility error and exposes teamId when a team becomes selected", async () => {
    const { result, rerender } = renderHook(() => usePromptForm());

    act(() => {
      result.current.setVisibility("team");
    });

    expect(result.current.errors.visibility).toBeDefined();

    mockAuth("team-123");
    rerender();

    await waitFor(() => {
      expect(result.current.errors.visibility).toBeUndefined();
      expect(result.current.teamId).toBe("team-123");
    });
  });

  it("does not set a team visibility error when the sidebar already has a team selected", () => {
    mockAuth("team-123");
    const { result } = renderHook(() => usePromptForm());

    act(() => {
      result.current.setVisibility("team");
    });

    expect(result.current.errors.visibility).toBeUndefined();
    expect(result.current.teamId).toBe("team-123");
  });

  it("submits valid prompt data and calls onSuccess", async () => {
    mockAuth("team-123");
    mockPost.mockResolvedValue({ id: "prompt-1", name: "Team prompt" });
    const onSuccess = vi.fn();
    const { result } = renderHook(() => usePromptForm());

    act(() => {
      result.current.setName("Team prompt");
      result.current.setVisibility("team");
      result.current.setTemplate("Hello {{ name }}");
      result.current.setDescription("Greets a person");
      result.current.setTags("greeting, example");
    });

    await act(async () => {
      await result.current.handleSubmit(fakeSubmit(), onSuccess);
    });

    expect(mockPost).toHaveBeenCalledWith(
      "/prompts",
      {
        prompt: {
          name: "Team prompt",
          description: "Greets a person",
          template: "Hello {{ name }}",
          arguments: [],
          tags: ["greeting", "example"],
          visibility: "team",
          teamId: "team-123",
        },
        team_id: "team-123",
        visibility: "team",
      },
      expect.objectContaining({ signal: expect.any(Object) }),
    );
    expect(onSuccess).toHaveBeenCalled();
    expect(result.current.name).toBe("");
    expect(result.current.visibility).toBe("public");
    expect(result.current.template).toBe("");
    expect(result.current.description).toBe("");
    expect(result.current.tags).toBe("");
  });

  it("does not include a selected team in the API payload for public prompts", async () => {
    mockAuth("team-123");
    mockPost.mockResolvedValue({ id: "prompt-1", name: "Public prompt" });
    const { result } = renderHook(() => usePromptForm());

    act(() => {
      result.current.setName("Public prompt");
      result.current.setTemplate("Hello {{ name }}");
    });

    await act(async () => {
      await result.current.handleSubmit(fakeSubmit());
    });

    expect(mockPost).toHaveBeenCalledWith(
      "/prompts",
      expect.objectContaining({
        prompt: expect.objectContaining({
          teamId: null,
          visibility: "public",
        }),
        team_id: null,
        visibility: "public",
      }),
      expect.objectContaining({ signal: expect.any(Object) }),
    );
  });

  it("maps API team_id field errors onto visibility", async () => {
    mockAuth("team-123");
    const error = new Error("HTTP 422") as Error & {
      body?: { field?: string; message?: string };
    };
    error.body = { field: "team_id", message: "Team is not available" };
    mockPost.mockRejectedValue(error);
    const { result } = renderHook(() => usePromptForm());

    act(() => {
      result.current.setName("Team prompt");
      result.current.setVisibility("team");
      result.current.setTemplate("Hello {{ name }}");
    });

    await waitFor(() => {
      expect(result.current.isValid).toBe(true);
    });

    await act(async () => {
      await result.current.handleSubmit(fakeSubmit());
    });

    expect(mockPost).toHaveBeenCalled();
    await waitFor(() => {
      expect(result.current.errors.visibility).toBe("Team is not available");
    });
  });

  it.each([
    ["description", "Description rejected"],
    ["tags", "Tags rejected"],
    ["unknown_field", "Unknown field rejected"],
  ])("falls back to a submit error for %s API field errors", async (field, message) => {
    const error = new Error("HTTP 422") as Error & {
      body?: { field?: string; message?: string };
    };
    error.body = { field, message };
    mockPost.mockRejectedValue(error);
    const { result } = renderHook(() => usePromptForm());

    act(() => {
      result.current.setName("Public prompt");
      result.current.setTemplate("Hello {{ name }}");
    });

    await act(async () => {
      await result.current.handleSubmit(fakeSubmit());
    });

    expect(result.current.errors.submit).toBe(message);
  });

  it("clears submit errors when fields change", async () => {
    mockPost.mockRejectedValue(new Error("Network failed"));
    const { result } = renderHook(() => usePromptForm());

    act(() => {
      result.current.setName("Public prompt");
      result.current.setTemplate("Hello {{ name }}");
    });

    await act(async () => {
      await result.current.handleSubmit(fakeSubmit());
    });

    expect(result.current.errors.submit).toBe("Failed to add prompt. Please try again.");

    act(() => {
      result.current.setName("Updated prompt");
    });

    await waitFor(() => {
      expect(result.current.errors.submit).toBeUndefined();
    });
  });

  it("prefills fields from initialValues in edit mode", () => {
    const { result } = renderHook(() =>
      usePromptForm({
        promptId: "prompt-1",
        initialValues: {
          name: "Existing prompt",
          visibility: "private",
          template: "Hello {{ name }}",
          arguments: "[]",
          description: "An existing prompt",
          tags: "greeting, example",
        },
      }),
    );

    expect(result.current.name).toBe("Existing prompt");
    expect(result.current.visibility).toBe("private");
    expect(result.current.template).toBe("Hello {{ name }}");
    expect(result.current.description).toBe("An existing prompt");
    expect(result.current.tags).toBe("greeting, example");
    expect(result.current.isValid).toBe(true);
  });

  it("requires the template by default (REST prompts)", () => {
    const { result } = renderHook(() => usePromptForm());

    act(() => {
      result.current.setName("Greeting prompt");
    });

    let valid: boolean;
    act(() => {
      valid = result.current.validateForm();
    });

    expect(valid!).toBe(false);
    expect(result.current.errors.template).toBe("Template is required");
  });

  it("allows an empty template when templateRequired is false (federated prompts)", () => {
    const { result } = renderHook(() =>
      usePromptForm({
        promptId: "prompt-1",
        templateRequired: false,
        initialValues: { name: "Federated prompt", template: "", visibility: "public" },
      }),
    );

    let valid: boolean;
    act(() => {
      valid = result.current.validateForm();
    });

    expect(valid!).toBe(true);
    expect(result.current.errors.template).toBeUndefined();
    expect(result.current.isValid).toBe(true);
  });

  it("updates an existing prompt via PUT and preserves the form in edit mode", async () => {
    mockPut.mockResolvedValue({ id: "prompt-1", name: "Existing prompt" });
    const onSuccess = vi.fn();
    const { result } = renderHook(() =>
      usePromptForm({
        promptId: "prompt-1",
        initialValues: {
          name: "Existing prompt",
          visibility: "public",
          template: "Hello {{ name }}",
        },
      }),
    );

    act(() => {
      result.current.setTemplate("Hello {{ name }}, welcome");
    });

    await act(async () => {
      await result.current.handleSubmit(fakeSubmit(), onSuccess);
    });

    expect(mockPost).not.toHaveBeenCalled();
    expect(mockPut).toHaveBeenCalledWith("/prompts/prompt-1", {
      name: "Existing prompt",
      description: null,
      template: "Hello {{ name }}, welcome",
      arguments: [],
      tags: null,
      teamId: null,
      visibility: "public",
    });
    expect(onSuccess).toHaveBeenCalled();
    // Edit mode does not reset the form back to its empty state.
    expect(result.current.name).toBe("Existing prompt");
    expect(result.current.template).toBe("Hello {{ name }}, welcome");
  });

  it("keeps the prompt's own team when editing a team prompt with no sidebar selection", async () => {
    mockAuth(null); // no team selected in the sidebar
    mockPut.mockResolvedValue({ id: "prompt-1", name: "Team prompt" });
    const { result } = renderHook(() =>
      usePromptForm({
        promptId: "prompt-1",
        initialValues: {
          name: "Team prompt",
          visibility: "team",
          template: "Hello {{ name }}",
          teamId: "team-original",
        },
      }),
    );

    // Valid despite no sidebar team, because the prompt's own team is kept.
    expect(result.current.teamId).toBe("team-original");
    expect(result.current.isValid).toBe(true);
    expect(result.current.errors.visibility).toBeUndefined();

    await act(async () => {
      await result.current.handleSubmit(fakeSubmit());
    });

    expect(mockPut).toHaveBeenCalledWith(
      "/prompts/prompt-1",
      expect.objectContaining({ visibility: "team", teamId: "team-original" }),
    );
  });

  it("preserves the prompt's team over a different selected sidebar team when editing", async () => {
    mockAuth("team-selected");
    mockPut.mockResolvedValue({ id: "prompt-1", name: "Team prompt" });
    const { result } = renderHook(() =>
      usePromptForm({
        promptId: "prompt-1",
        initialValues: {
          name: "Team prompt",
          visibility: "team",
          template: "Hello {{ name }}",
          teamId: "team-original",
        },
      }),
    );

    expect(result.current.teamId).toBe("team-original");

    await act(async () => {
      await result.current.handleSubmit(fakeSubmit());
    });

    expect(mockPut).toHaveBeenCalledWith(
      "/prompts/prompt-1",
      expect.objectContaining({ teamId: "team-original" }),
    );
  });

  it("falls back to the edit submit error when an update fails", async () => {
    mockPut.mockRejectedValue(new Error("Network failed"));
    const { result } = renderHook(() =>
      usePromptForm({
        promptId: "prompt-1",
        initialValues: {
          name: "Existing prompt",
          visibility: "public",
          template: "Hello {{ name }}",
        },
      }),
    );

    await act(async () => {
      await result.current.handleSubmit(fakeSubmit());
    });

    expect(result.current.errors.submit).toBe("Failed to update prompt. Please try again.");
  });

  it("clears submit errors when visibility changes", async () => {
    mockPost.mockRejectedValue(new Error("Network failed"));
    const { result } = renderHook(() => usePromptForm());

    act(() => {
      result.current.setName("Public prompt");
      result.current.setTemplate("Hello {{ name }}");
    });

    await act(async () => {
      await result.current.handleSubmit(fakeSubmit());
    });

    expect(result.current.errors.submit).toBe("Failed to add prompt. Please try again.");

    act(() => {
      result.current.setVisibility("private");
    });

    await waitFor(() => {
      expect(result.current.errors.submit).toBeUndefined();
    });
  });
});
