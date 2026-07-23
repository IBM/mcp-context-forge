import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Bot, Code2, Grid3x3, Wrench } from "lucide-react";
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

function buildFourActionCards() {
  const mcpAction = vi.fn();
  const aiAction = vi.fn();
  const restAction = vi.fn();
  const grpcAction = vi.fn();
  const cards: ActionCard[] = [
    {
      icon: Wrench,
      title: "MCP server",
      description: "Register an MCP server",
      buttonText: "Connect",
      onAction: mcpAction,
    },
    {
      icon: Bot,
      title: "AI agent",
      description: "Add an agent over A2A, OpenAI, or Anthropic protocols",
      buttonText: "Connect",
      onAction: aiAction,
    },
    {
      icon: Code2,
      title: "REST API",
      description: "Wrap an HTTP endpoint as an MCP tool",
      buttonText: "Connect",
      onAction: restAction,
      disabled: true,
      disabledReason: "Coming soon",
    },
    {
      icon: Grid3x3,
      title: "gRPC",
      description: "Translate a gRPC endpoint as an MCP tool.",
      buttonText: "Connect",
      onAction: grpcAction,
      disabled: true,
      disabledReason: "Coming soon",
    },
  ];
  return { cards, mcpAction, aiAction, restAction, grpcAction };
}

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

  it("shows the connect button only on the initially selected card", () => {
    const { cards } = buildFourActionCards();

    renderWithProviders(<SourceSelection actionCards={cards} />);

    expect(screen.getAllByRole("button", { name: "Connect" })).toHaveLength(1);
  });

  it("moves the connect button when a different enabled card is selected", async () => {
    const user = userEvent.setup();
    const { cards, aiAction } = buildFourActionCards();

    renderWithProviders(<SourceSelection actionCards={cards} />);

    await user.click(screen.getByTestId("action-card-AI agent"));
    expect(screen.getAllByRole("button", { name: "Connect" })).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: "Connect" }));
    expect(aiAction).toHaveBeenCalledTimes(1);
  });

  it("keeps disabled cards non-interactive and free of a connect button", async () => {
    const user = userEvent.setup();
    const { cards, restAction, grpcAction } = buildFourActionCards();

    renderWithProviders(<SourceSelection actionCards={cards} />);

    const restCard = screen.getByTestId("action-card-REST API");
    const grpcCard = screen.getByTestId("action-card-gRPC");

    expect(restCard).toHaveAttribute("aria-disabled", "true");
    expect(grpcCard).toHaveAttribute("aria-disabled", "true");
    expect(restCard).toHaveAccessibleName(/Coming soon/i);
    expect(grpcCard).toHaveAccessibleName(/Coming soon/i);
    expect(screen.queryByText("Coming soon")).not.toBeInTheDocument();

    await user.click(restCard);
    await user.click(grpcCard);

    expect(restAction).not.toHaveBeenCalled();
    expect(grpcAction).not.toHaveBeenCalled();
    expect(screen.getAllByRole("button", { name: "Connect" })).toHaveLength(1);
  });
});
