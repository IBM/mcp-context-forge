import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Wrench } from "lucide-react";
import { http, HttpResponse } from "msw";
import { SourceSelection } from "@/components/gateways/SourceSelection";
import type { ActionCard } from "@/components/gateways/types";
import { server } from "@/test/mocks/server";
import { renderWithProviders } from "@/test/test-utils";

const actionCards: ActionCard[] = [
  {
    icon: Wrench,
    title: "MCP server",
    description: "Register an MCP server",
    buttonText: "Connect",
    onAction: vi.fn(),
  },
];

describe("SourceSelection", () => {
  it("lazy-loads selectable MCP servers and hides sources already in the virtual server", async () => {
    const user = userEvent.setup();
    let gatewaysRequestCount = 0;
    server.use(
      http.get("*/gateways", () => {
        gatewaysRequestCount += 1;
        return HttpResponse.json({
          gateways: [
            {
              id: "already-attached",
              name: "already-attached",
              url: "http://localhost:9000",
              transport: "SSE",
              enabled: true,
              reachable: true,
              visibility: "public",
              tool_count: 2,
              resource_count: 1,
              prompt_count: 0,
              created_at: "2024-01-01T00:00:00Z",
              updated_at: "2024-01-01T00:00:00Z",
            },
            {
              id: "github-notify",
              name: "github-notify",
              url: "http://localhost:9001",
              transport: "SSE",
              enabled: true,
              reachable: true,
              visibility: "public",
              tool_count: 5,
              resource_count: 2,
              prompt_count: 1,
              created_at: "2024-01-01T00:00:00Z",
              updated_at: "2024-01-01T00:00:00Z",
            },
          ],
        });
      }),
    );

    renderWithProviders(
      <SourceSelection
        actionCards={actionCards}
        associatedMCPServerIds={["already-attached"]}
        createServerActions={{
          onBack: vi.fn(),
          onSkip: vi.fn(),
        }}
      />,
    );

    expect(gatewaysRequestCount).toBe(0);

    await user.click(
      screen.getByRole("button", {
        name: "Add tools, resources, and prompts from connected sources",
      }),
    );

    expect(await screen.findByText("github-notify")).toBeInTheDocument();
    expect(screen.queryByText("already-attached")).not.toBeInTheDocument();
    expect(gatewaysRequestCount).toBe(1);

    const githubCheckbox = screen.getByRole("checkbox", { name: "Select github-notify" });
    expect(githubCheckbox).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Skip for now" })).toBeInTheDocument();

    await user.click(githubCheckbox);

    expect(githubCheckbox).toBeChecked();
    expect(screen.getByRole("button", { name: "Submit" })).toBeInTheDocument();

    await user.click(githubCheckbox);

    expect(githubCheckbox).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Skip for now" })).toBeInTheDocument();
  });

  it("shows an empty message when no MCP servers are available", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("*/gateways", () =>
        HttpResponse.json({
          gateways: [],
        }),
      ),
    );

    renderWithProviders(
      <SourceSelection
        actionCards={actionCards}
        createServerActions={{
          onBack: vi.fn(),
          onSkip: vi.fn(),
        }}
      />,
    );

    await user.click(
      screen.getByRole("button", {
        name: "Add tools, resources, and prompts from connected sources",
      }),
    );

    expect(await screen.findByText("No MCP servers found.")).toBeInTheDocument();
  });

  it("shows an alert when MCP server loading fails", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("*/gateways", () =>
        HttpResponse.json({ detail: "Gateway list failed" }, { status: 500 }),
      ),
    );

    renderWithProviders(
      <SourceSelection
        actionCards={actionCards}
        createServerActions={{
          onBack: vi.fn(),
          onSkip: vi.fn(),
        }}
      />,
    );

    await user.click(
      screen.getByRole("button", {
        name: "Add tools, resources, and prompts from connected sources",
      }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("HTTP 500");
  });
});
