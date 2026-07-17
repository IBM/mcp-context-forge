import { describe, it, expect, beforeEach, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { renderWithProviders } from "@/test/test-utils";
import { useAuthContext } from "@/auth/AuthContext";
import { Prompts } from "./Prompts";

vi.mock("@/auth/AuthContext", () => ({
  useAuthContext: vi.fn(),
}));

const mockUseAuthContext = vi.mocked(useAuthContext);
import type { PromptRead } from "@/generated/types";

type Prompt = NonNullable<PromptRead>;

function createMockPrompt(overrides: Partial<Prompt> = {}): Prompt {
  return {
    id: "prompt-1",
    name: "summarize",
    originalName: "summarize_document",
    customName: "summarize_document",
    customNameSlug: "summarize_document",
    displayName: "Summarize document",
    gatewayId: "gateway-1",
    gatewaySlug: "gateway-1",
    description: "Summarizes uploaded documents.",
    template: "Summarize: {{topic}}",
    tags: [{ id: "tag-summary", label: "summary" }],
    arguments: [{ name: "topic", required: true }],
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:00Z",
    enabled: true,
    ...overrides,
  };
}

function getPromptCard(label: string): HTMLElement {
  const card = screen.getByText(label).closest('[data-slot="card"]');
  expect(card).toBeInTheDocument();
  return card as HTMLElement;
}

describe("Prompts", () => {
  beforeEach(() => {
    server.resetHandlers();
    mockUseAuthContext.mockReturnValue({ selectedTeamId: null } as ReturnType<
      typeof useAuthContext
    >);
  });

  it("renders the add prompts card", async () => {
    server.use(http.get("/prompts", () => HttpResponse.json([])));

    renderWithProviders(<Prompts />);

    await waitFor(() => {
      expect(screen.getByText("Add prompts")).toBeInTheDocument();
    });

    expect(
      screen.getByText(/Connect a MCP server to load prompts automatically/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /More options for/i })).not.toBeInTheDocument();
  });

  it("renders the add prompts card when the response object has no prompts", async () => {
    server.use(http.get("/prompts", () => HttpResponse.json({})));

    renderWithProviders(<Prompts />);

    expect(await screen.findByRole("button", { name: "Add prompts" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /More options for/i })).not.toBeInTheDocument();
  });

  it("shows the prompt form when the add card is clicked", async () => {
    const user = userEvent.setup();
    server.use(http.get("/prompts", () => HttpResponse.json([])));

    renderWithProviders(<Prompts />);

    const addPromptsButton = await screen.findByRole("button", { name: "Add prompts" });
    await user.click(addPromptsButton);

    expect(screen.getByRole("heading", { name: "Add prompt" })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByLabelText(/name/i)).toHaveFocus();
    });
  });

  it("shows the prompt form when the add card is activated by keyboard", async () => {
    const user = userEvent.setup();
    server.use(http.get("/prompts", () => HttpResponse.json([])));

    renderWithProviders(<Prompts />);

    const addPromptsButton = await screen.findByRole("button", { name: "Add prompts" });
    addPromptsButton.focus();
    await user.keyboard("{Enter}");

    expect(screen.getByRole("heading", { name: "Add prompt" })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByLabelText(/name/i)).toHaveFocus();
    });
  });

  it("ignores non-activation keys on the add prompts card", async () => {
    const user = userEvent.setup();
    server.use(http.get("/prompts", () => HttpResponse.json([])));

    renderWithProviders(<Prompts />);

    const addPromptsButton = await screen.findByRole("button", { name: "Add prompts" });
    addPromptsButton.focus();
    await user.keyboard("a");

    expect(screen.queryByRole("heading", { name: "Add prompt" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add prompts" })).toBeInTheDocument();
  });

  it("returns to the prompt grid when the form is canceled", async () => {
    const user = userEvent.setup();
    server.use(http.get("/prompts", () => HttpResponse.json([])));

    renderWithProviders(<Prompts />);

    await user.click(await screen.findByRole("button", { name: "Add prompts" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    const addPromptsButton = screen.getByRole("button", { name: "Add prompts" });
    expect(addPromptsButton).toBeInTheDocument();
    await waitFor(() => {
      expect(addPromptsButton).toHaveFocus();
    });
  });

  it("hides the prompt form and refetches prompts after a successful create", async () => {
    const user = userEvent.setup();
    let promptListRequests = 0;
    server.use(
      http.get("/prompts", () => {
        promptListRequests += 1;
        return HttpResponse.json([]);
      }),
      http.post("/prompts", () =>
        HttpResponse.json({
          id: "prompt-1",
          name: "Greeting prompt",
        }),
      ),
    );

    renderWithProviders(<Prompts />);

    const addPromptsButton = await screen.findByRole("button", { name: "Add prompts" });
    await user.click(addPromptsButton);
    await user.type(screen.getByLabelText(/name/i), "Greeting prompt");
    fireEvent.change(screen.getByLabelText(/template/i), {
      target: { value: "Hello {{ name }}" },
    });
    await user.click(screen.getByRole("button", { name: "Add prompt" }));

    await waitFor(() => {
      expect(screen.queryByRole("heading", { name: "Add prompt" })).not.toBeInTheDocument();
    });
    const addPromptsButtonAfterSubmit = screen.getByRole("button", { name: "Add prompts" });
    expect(addPromptsButtonAfterSubmit).toBeInTheDocument();
    await waitFor(() => {
      expect(addPromptsButtonAfterSubmit).toHaveFocus();
    });
    expect(promptListRequests).toBeGreaterThan(1);
  });

  it("renders array prompt responses as REST prompt badges with description tooltips", async () => {
    server.use(
      http.get("/prompts", () =>
        HttpResponse.json([
          {
            id: "prompt-1",
            name: "summary_prompt",
            displayName: "Summarize document",
            originalName: "summary_original",
            description: "Turns long text into a short summary.",
            tags: [{ id: "tag-1", label: "summary" }],
            arguments: [{ name: "content", required: true }],
          },
        ]),
      ),
    );

    renderWithProviders(<Prompts />);

    expect(await screen.findByText("REST prompts")).toBeInTheDocument();
    const restCard = getPromptCard("REST prompts");
    expect(within(restCard).getByText("Summarize document")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "More options for REST prompts" }),
    ).toBeInTheDocument();

    const describedTrigger = within(restCard).getByText("Summarize document").closest("button");
    expect(describedTrigger).not.toBeNull();
    describedTrigger?.focus();
    expect(await screen.findByRole("tooltip")).toHaveTextContent(
      "Turns long text into a short summary.",
    );
  });

  it("renders loading state", () => {
    server.use(
      http.get("/prompts", async () => {
        await new Promise(() => {});
        return HttpResponse.json([]);
      }),
    );

    renderWithProviders(<Prompts />);

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByText("Loading prompts, please wait...")).toBeInTheDocument();
  });

  it("groups prompts from the same MCP server into one card with prompt-name badges", async () => {
    const user = userEvent.setup();
    const prompts: Prompt[] = [
      createMockPrompt({
        id: "prompt-display-name",
        name: "summarize",
        displayName: "Summarize document",
        originalName: "summarize_document",
        gatewayId: "gw-github",
        gatewaySlug: "gh-repo-tasks",
      }),
      createMockPrompt({
        id: "prompt-original-name",
        name: "translate",
        displayName: "",
        originalName: "translate_text",
        gatewayId: "gw-github",
        gatewaySlug: "gh-repo-tasks",
      }),
    ];

    server.use(http.get("/prompts", () => HttpResponse.json(prompts)));

    renderWithProviders(<Prompts />);

    await waitFor(() => {
      expect(screen.getByText("gh-repo-tasks")).toBeInTheDocument();
    });

    // A single group card holds both prompts as name badges.
    const groupCard = getPromptCard("gh-repo-tasks");
    expect(within(groupCard).getByText("Summarize document")).toBeInTheDocument();
    expect(within(groupCard).getByText("translate_text")).toBeInTheDocument();

    // Only one "More options" trigger for the whole group.
    expect(screen.getAllByRole("button", { name: /More options for/i })).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: "More options for gh-repo-tasks" }));
    expect(await screen.findByRole("menuitem", { name: "View details" })).toBeInTheDocument();
  });

  it("collapses gateway-less prompts into a single REST prompts card", async () => {
    const prompts: Prompt[] = [
      createMockPrompt({
        id: "prompt-local",
        name: "doc_processor",
        displayName: "doc-processor",
        originalName: "doc_processor",
        gatewayId: null,
        gatewaySlug: null,
      }),
      createMockPrompt({
        id: "prompt-fallback",
        name: "fallback_prompt",
        displayName: undefined,
        originalName: undefined,
        gatewayId: null,
        gatewaySlug: null,
        description: "   ",
        tags: undefined,
        arguments: undefined,
      }),
    ];

    server.use(http.get("/prompts", () => HttpResponse.json(prompts)));

    renderWithProviders(<Prompts />);

    await waitFor(() => {
      expect(screen.getByText("REST prompts")).toBeInTheDocument();
    });

    // Both gateway-less prompts share one card, shown as name badges.
    const restCard = getPromptCard("REST prompts");
    expect(within(restCard).getByText("doc-processor")).toBeInTheDocument();
    expect(within(restCard).getByText("fallback_prompt")).toBeInTheDocument();

    // A single "More options" trigger for the whole REST group.
    expect(screen.getAllByRole("button", { name: /More options for/i })).toHaveLength(1);
  });

  it("truncates a large group to a +N overflow badge and uses descriptions as badge tooltips", async () => {
    // 10 prompts in one gateway group: 8 visible + a "+2" overflow badge.
    const prompts: Prompt[] = Array.from({ length: 10 }, (_, i) =>
      createMockPrompt({
        id: `prompt-${i}`,
        name: `prompt_${i}`,
        displayName: `Prompt ${i}`,
        originalName: `prompt_${i}`,
        gatewayId: "gw-bulk",
        gatewaySlug: "bulk-gateway",
        description: i === 0 ? "First prompt description." : "None",
      }),
    );

    server.use(http.get("/prompts", () => HttpResponse.json(prompts)));

    renderWithProviders(<Prompts />);

    await waitFor(() => {
      expect(screen.getByText("bulk-gateway")).toBeInTheDocument();
    });

    const card = getPromptCard("bulk-gateway");
    expect(within(card).getByText("Prompt 0")).toBeInTheDocument();
    expect(within(card).getByText("Prompt 7")).toBeInTheDocument();
    // 9th and 10th prompts are hidden behind the overflow badge.
    expect(within(card).queryByText("Prompt 8")).not.toBeInTheDocument();
    expect(within(card).getByText("+2")).toBeInTheDocument();

    // A real description becomes an accessible tooltip; filtered "None" descriptions do not.
    const describedTrigger = within(card).getByText("Prompt 0").closest("button");
    expect(describedTrigger).not.toBeNull();
    // Radix opens the tooltip on focus, giving keyboard users the description.
    fireEvent.focus(describedTrigger as HTMLElement);

    await waitFor(async () => {
      const tooltip = await screen.findByRole("tooltip");
      expect(tooltip).toHaveTextContent("First prompt description.");
    });

    // "Prompt 1" has description "None", so it renders as a plain tag with no tooltip trigger.
    expect(within(card).getByText("Prompt 1").closest("button")).toBeNull();
  });

  it("renders error state when prompts fail to load", async () => {
    server.use(http.get("/prompts", () => HttpResponse.json({ detail: "Nope" }, { status: 500 })));

    renderWithProviders(<Prompts />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });

    expect(screen.getByText("Error loading prompts")).toBeInTheDocument();
    expect(screen.getByText("HTTP 500")).toBeInTheDocument();
  });

  it("shows a newly added tag in the details drawer (patches cache, no full refetch)", async () => {
    const user = userEvent.setup();
    const prompt = createMockPrompt({
      id: "prompt-1",
      gatewaySlug: "gh-repo-tasks",
      tags: [{ id: "summary", label: "summary" }],
    });

    let promptsListCalls = 0;
    server.use(
      http.get("/prompts", () => {
        promptsListCalls += 1;
        return HttpResponse.json([prompt]);
      }),
      http.put("/prompts/:id", () =>
        HttpResponse.json({
          ...prompt,
          tags: [
            { id: "summary", label: "summary" },
            { id: "alerts", label: "alerts" },
          ],
        }),
      ),
    );

    renderWithProviders(<Prompts />);

    await waitFor(() => expect(screen.getByText("Summarize document")).toBeInTheDocument());
    const listCallsAfterLoad = promptsListCalls;

    // Open the details drawer for the group.
    await user.click(screen.getByRole("button", { name: /More options for/i }));
    await user.click(await screen.findByRole("menuitem", { name: "View details" }));

    const drawer = await screen.findByRole("region", { name: /prompt details/i });
    expect(within(drawer).getByText("summary")).toBeInTheDocument();
    expect(within(drawer).queryByText("alerts")).not.toBeInTheDocument();

    // Add a tag through the inline editor.
    await user.click(within(drawer).getByRole("button", { name: "Add tags" }));
    await user.type(
      within(drawer).getByPlaceholderText("Add tags separated with commas"),
      "alerts",
    );
    await user.click(within(drawer).getByRole("button", { name: "Add" }));

    // The new tag renders in the drawer from the patched cache...
    expect(await within(drawer).findByText("alerts")).toBeInTheDocument();
    // ...without re-fetching the whole prompts catalog.
    expect(promptsListCalls).toBe(listCallsAfterLoad);
  });
});
