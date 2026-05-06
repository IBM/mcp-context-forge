import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/test-utils";
import { Gateways } from "./Gateways";
import { useQuery } from "@/hooks/useQuery";
import type { VirtualServer } from "@/types/server";

// Mock the router
const mockNavigate = vi.fn();
vi.mock("@/router", () => ({
  useRouter: () => ({
    navigate: mockNavigate,
    path: "/app/gateways",
    params: {},
  }),
}));

vi.mock("@/hooks/useQuery", () => ({
  useQuery: vi.fn(),
}));

const mockUseQuery = vi.mocked(useQuery);

describe("Gateways", () => {
  beforeEach(() => {
    mockNavigate.mockClear();
    mockUseQuery.mockReturnValue({
      data: { servers: [] },
      error: null,
      isLoading: false,
      execute: vi.fn(),
      refetch: vi.fn(),
    });
  });

  it("requests the servers list on page load", () => {
    renderWithProviders(<Gateways />);

    expect(mockUseQuery).toHaveBeenCalledWith("/servers?limit=12&include_pagination=true");
  });

  it("renders the source selection when no virtual servers exist", () => {
    renderWithProviders(<Gateways />);

    expect(screen.getByRole("heading", { name: "Connect a source" })).toBeInTheDocument();
    expect(screen.getByText("MCP server")).toBeInTheDocument();
    expect(screen.getByText("AI agent")).toBeInTheDocument();
    expect(screen.getByText("REST API")).toBeInTheDocument();
    expect(screen.getByText("gRPC")).toBeInTheDocument();
    expect(
      screen.getByText("Register an endpoint implementing the Model Context Protocol"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Virtual servers" })).not.toBeInTheDocument();
  });

  it("renders the virtual server layout when servers exist", () => {
    const mockServer: VirtualServer = {
      id: "gateway-1",
      name: "GH repo tasks",
      description: "Test server",
      icon: "",
      createdAt: "2026-04-16T13:23:12Z",
      updatedAt: "2026-04-16T13:23:12Z",
      enabled: true,
      associatedTools: [],
      associatedToolIds: ["tool1", "tool2", "tool3", "tool4", "tool5", "tool6"],
      associatedResources: [],
      associatedPrompts: [],
      associatedA2aAgents: [],
      metrics: null,
      tags: ["team", "enabled"],
      createdBy: "admin@example.com",
      createdFromIp: "127.0.0.1",
      createdVia: "ui",
      createdUserAgent: "Mozilla/5.0",
      modifiedBy: null,
      modifiedFromIp: null,
      modifiedVia: null,
      modifiedUserAgent: null,
      importBatchId: null,
      federationSource: null,
      version: 1,
      teamId: "team-1",
      team: "Test Team",
      ownerEmail: "admin@example.com",
      visibility: "team",
      oauthEnabled: false,
      oauthConfig: null,
    };

    mockUseQuery.mockReturnValue({
      data: {
        servers: [mockServer],
      },
      error: null,
      isLoading: false,
      execute: vi.fn(),
      refetch: vi.fn(),
    });

    renderWithProviders(<Gateways />);

    expect(screen.getByRole("heading", { name: "Virtual servers" })).toBeInTheDocument();
    expect(screen.getByText("GH repo tasks")).toBeInTheDocument();
    expect(screen.getByText("6")).toBeInTheDocument();
    expect(screen.getByText("team")).toBeInTheDocument();
    expect(screen.queryByText("MCP server")).not.toBeInTheDocument();
  });

  it("navigates to servers page with open parameter when MCP server connect is clicked", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Gateways />);

    const buttons = screen.getAllByRole("button", { name: "+ Connect" });
    await user.click(buttons[0]!);

    expect(mockNavigate).toHaveBeenCalledWith("/app/servers?openForm=true");
  });
});
