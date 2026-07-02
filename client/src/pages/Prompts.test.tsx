import { describe, it, expect, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { renderWithProviders } from "@/test/test-utils";
import { Prompts } from "./Prompts";

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
