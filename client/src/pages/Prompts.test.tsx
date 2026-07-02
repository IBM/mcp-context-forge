import { describe, it, expect, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { renderWithProviders } from "@/test/test-utils";
import { RouterProvider } from "@/router";
import { Prompts } from "./Prompts";

function renderPrompts() {
  window.history.pushState({}, "", "/app/prompts");
  return renderWithProviders(
    <RouterProvider>
      <Prompts />
    </RouterProvider>,
  );
}

describe("Prompts", () => {
  beforeEach(() => {
    server.resetHandlers();
  });

  it("renders the add prompts card", async () => {
    server.use(http.get("/prompts", () => HttpResponse.json([])));

    renderPrompts();

    await waitFor(() => {
      expect(screen.getByText("Add prompts")).toBeInTheDocument();
    });

    expect(
      screen.getByText(/Connect a MCP server to load prompts automatically/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /More options for/i })).not.toBeInTheDocument();
  });

  it("exposes the add prompts card as a keyboard-accessible button", async () => {
    const user = userEvent.setup();
    server.use(http.get("/prompts", () => HttpResponse.json([])));

    renderPrompts();

    const addPromptsButton = await screen.findByRole("button", { name: "Add prompts" });
    addPromptsButton.focus();

    expect(addPromptsButton).toHaveFocus();

    await user.keyboard("{Enter}");

    expect(window.location.pathname).toBe("/app/prompts/add");
  });

  it("renders returned prompts as cards with descriptions and tags", async () => {
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

    renderPrompts();

    expect(await screen.findByText("Summarize document")).toBeInTheDocument();
    expect(screen.getByText("Turns long text into a short summary.")).toBeInTheDocument();
    expect(screen.getByText("summary")).toBeInTheDocument();
    expect(screen.getByText("content")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "More options for Summarize document" }),
    ).toBeInTheDocument();
  });

  it("renders loading state", () => {
    server.use(
      http.get("/prompts", async () => {
        await new Promise(() => {});
        return HttpResponse.json([]);
      }),
    );

    renderPrompts();

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByText("Loading prompts, please wait...")).toBeInTheDocument();
  });

  it("renders error state when prompts fail to load", async () => {
    server.use(http.get("/prompts", () => HttpResponse.json({ detail: "Nope" }, { status: 500 })));

    renderPrompts();

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });

    expect(screen.getByText("Error loading prompts")).toBeInTheDocument();
    expect(screen.getByText("HTTP 500")).toBeInTheDocument();
  });
});
