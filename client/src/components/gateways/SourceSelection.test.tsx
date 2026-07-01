import { describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
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
            {
              id: "warning-server",
              name: "warning-server",
              url: "http://localhost:9002",
              transport: "SSE",
              enabled: true,
              reachable: false,
              lastSeen: "2024-01-01T00:00:00Z",
              visibility: "private",
              tool_count: 0,
              resource_count: 0,
              prompt_count: 0,
              created_at: "2024-01-01T00:00:00Z",
              updated_at: "2024-01-01T00:00:00Z",
            },
            {
              id: "offline-server",
              name: "offline-server",
              url: "http://localhost:9003",
              transport: "SSE",
              enabled: true,
              reachable: false,
              visibility: "team",
              tool_count: 0,
              resource_count: 0,
              prompt_count: 0,
              created_at: "2024-01-01T00:00:00Z",
              updated_at: "2024-01-01T00:00:00Z",
            },
            {
              id: "draft-server",
              name: "draft-server",
              url: "http://localhost:9004",
              transport: "SSE",
              enabled: false,
              reachable: false,
              visibility: "public",
              tool_count: 0,
              resource_count: 0,
              prompt_count: 0,
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

    await user.click(githubCheckbox);

    expect(githubCheckbox).toBeChecked();

    // Verification of helper mapping branches:
    // "warning-server" has warning status and private visibility
    expect(await screen.findByText("warning-server")).toBeInTheDocument();
    
    // "offline-server" has offline status and team visibility
    expect(await screen.findByText("offline-server")).toBeInTheDocument();
    
    // "draft-server" has inactive/draft status
    expect(await screen.findByText("draft-server")).toBeInTheDocument();
  });

  it("handles empty API response correctly", async () => {
    const user = userEvent.setup();
    server.use(http.get("*/gateways", () => HttpResponse.json({ gateways: [] })));

    renderWithProviders(
      <SourceSelection 
        actionCards={actionCards}
        createServerActions={{ onBack: vi.fn(), onSkip: vi.fn() }} 
      />
    );

    await user.click(
      screen.getByRole("button", {
        name: /Add components|connected sources/i,
      })
    );

    // Wait for the loading to finish and ensure no checkboxes are rendered
    await waitFor(() => {
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
    });
    
    // In empty state, no server checkboxes should be present
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("handles API error correctly", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("*/gateways", () => HttpResponse.json({ detail: "Server Error" }, { status: 500 }))
    );

    renderWithProviders(
      <SourceSelection 
        actionCards={actionCards} 
        createServerActions={{ onBack: vi.fn(), onSkip: vi.fn() }} 
      />
    );

    await user.click(
      screen.getByRole("button", {
        name: /Add components|connected sources/i,
      })
    );

    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});
