import { describe, it, expect, beforeEach } from "vitest";
import { screen, waitFor, within, fireEvent } from "@testing-library/react";
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

    server.use(http.get("/prompts", () => HttpResponse.json({ prompts })));

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
      }),
    ];

    server.use(http.get("/prompts", () => HttpResponse.json({ prompts })));

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

    server.use(http.get("/prompts", () => HttpResponse.json({ prompts })));

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
});
