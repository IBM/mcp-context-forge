import { describe, it, expect, beforeEach } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { renderWithProviders } from "@/test/test-utils";
import { Prompts } from "./Prompts";
import type { Prompt } from "@/types/prompts";

function createMockPrompt(overrides: Partial<Prompt> = {}): Prompt {
  return {
    id: "prompt-1",
    name: "summarize",
    displayName: "Summarize document",
    originalName: "summarize_document",
    gatewayId: "gateway-1",
    gatewaySlug: "gateway-1",
    description: "Summarizes uploaded documents.",
    tags: [{ id: "tag-summary", label: "summary" }],
    arguments: [{ name: "topic", required: true }],
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

  it("renders populated prompt cards with label fallbacks, tag and argument badges, filtered descriptions, and actions", async () => {
    const user = userEvent.setup();
    const prompts: Prompt[] = [
      createMockPrompt({
        id: "prompt-display-name",
        name: "summarize",
        displayName: "Summarize document",
        originalName: "summarize_document",
        description: "Summarizes uploaded documents.",
        tags: [{ id: "tag-summary", label: "summary" }],
        arguments: [
          { name: "topic", required: true },
          { name: "tone", required: false },
        ],
      }),
      createMockPrompt({
        id: "prompt-original-name",
        name: "translate",
        displayName: "",
        originalName: "translate_text",
        description: "None",
        tags: [{ id: "tag-language", label: "language" }],
        arguments: [{ name: "locale", required: true }],
      }),
      createMockPrompt({
        id: "prompt-name",
        name: "fallback_prompt",
        displayName: undefined,
        originalName: undefined,
        description: "   ",
        tags: [],
        arguments: [],
      }),
    ];

    server.use(http.get("/prompts", () => HttpResponse.json({ prompts })));

    renderWithProviders(<Prompts />);

    await waitFor(() => {
      expect(screen.getByText("Summarize document")).toBeInTheDocument();
    });

    expect(screen.getByText("translate_text")).toBeInTheDocument();
    expect(screen.getByText("fallback_prompt")).toBeInTheDocument();
    expect(screen.getByText("Summarizes uploaded documents.")).toBeInTheDocument();
    expect(screen.queryByText("None")).not.toBeInTheDocument();

    const summarizeCard = getPromptCard("Summarize document");
    expect(within(summarizeCard).getByText("summary")).toBeInTheDocument();
    expect(within(summarizeCard).getByText("topic")).toBeInTheDocument();
    expect(within(summarizeCard).getByText("tone")).toBeInTheDocument();

    const originalNameCard = getPromptCard("translate_text");
    expect(within(originalNameCard).getByText("language")).toBeInTheDocument();
    expect(within(originalNameCard).getByText("locale")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "More options for Summarize document" }));
    expect(await screen.findByRole("menuitem", { name: "View details" })).toBeInTheDocument();
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
});
