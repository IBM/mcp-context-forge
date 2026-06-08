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
    expect(screen.queryByRole("button", { name: "Back" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Skip for now" })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: "Add tools, resources, and prompts from connected sources",
      }),
    ).not.toBeInTheDocument();
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
      tags: [
        { id: "tag-team", label: "team" },
        { id: "tag-enabled", label: "enabled" },
      ],
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
    expect(screen.queryByRole("button", { name: "Create server" })).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Create server Make external sources/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("GH repo tasks")).toBeInTheDocument();
    expect(screen.getByText("6")).toBeInTheDocument();
    expect(screen.getByText("team")).toBeInTheDocument();
    expect(screen.queryByText("MCP server")).not.toBeInTheDocument();
  });

  it("renders empty virtual servers as full-width add-components rows", () => {
    const mockServer: VirtualServer = {
      id: "gateway-empty",
      name: "peach-thistle-shark",
      description: "",
      icon: "",
      createdAt: "2026-04-16T13:23:12Z",
      updatedAt: "2026-04-16T13:23:12Z",
      enabled: false,
      associatedTools: [],
      associatedToolIds: [],
      associatedResources: [],
      associatedPrompts: [],
      associatedA2aAgents: [],
      metrics: null,
      tags: [],
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
      data: { servers: [mockServer] },
      error: null,
      isLoading: false,
      execute: vi.fn(),
      refetch: vi.fn(),
    });

    renderWithProviders(<Gateways />);

    expect(screen.getByTestId("virtual-server-card")).toHaveClass("col-span-full");
    expect(screen.getByText("peach-thistle-shark")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add sources and components" })).toBeInTheDocument();
    expect(screen.queryByTestId("tool-count")).not.toBeInTheDocument();
    expect(screen.queryByTestId("last-updated")).not.toBeInTheDocument();
  });

  it("renders empty virtual servers after servers with components", () => {
    const emptyServer: VirtualServer = {
      id: "gateway-empty",
      name: "peach-thistle-shark",
      description: "",
      icon: "",
      createdAt: "2026-04-16T13:23:12Z",
      updatedAt: "2026-04-16T13:23:12Z",
      enabled: false,
      associatedTools: [],
      associatedToolIds: [],
      associatedResources: [],
      associatedPrompts: [],
      associatedA2aAgents: [],
      metrics: null,
      tags: [],
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
    const populatedServer: VirtualServer = {
      ...emptyServer,
      id: "gateway-populated",
      name: "GH repo tasks",
      enabled: true,
      associatedToolIds: ["tool-1"],
    };

    mockUseQuery.mockReturnValue({
      data: { servers: [emptyServer, populatedServer] },
      error: null,
      isLoading: false,
      execute: vi.fn(),
      refetch: vi.fn(),
    });

    renderWithProviders(<Gateways />);

    const renderedCards = screen.getAllByTestId("virtual-server-card");
    expect(renderedCards).toHaveLength(2);
    expect(renderedCards[0]).toHaveAttribute("data-server-name", "GH repo tasks");
    expect(renderedCards[1]).toHaveAttribute("data-server-name", "peach-thistle-shark");
    expect(renderedCards[1]).toHaveClass("col-span-full");
  });

  it("navigates to the create server UI when the create server card is clicked", async () => {
    const user = userEvent.setup();
    const mockServer: VirtualServer = {
      id: "gateway-1",
      name: "GH repo tasks",
      description: "Test server",
      icon: "",
      createdAt: "2026-04-16T13:23:12Z",
      updatedAt: "2026-04-16T13:23:12Z",
      enabled: true,
      associatedTools: [],
      associatedToolIds: [],
      associatedResources: [],
      associatedPrompts: [],
      associatedA2aAgents: [],
      metrics: null,
      tags: [],
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
      data: { servers: [mockServer] },
      error: null,
      isLoading: false,
      execute: vi.fn(),
      refetch: vi.fn(),
    });

    renderWithProviders(<Gateways />);

    await user.click(screen.getByRole("button", { name: /Create server Make external sources/i }));

    expect(mockNavigate).toHaveBeenCalledWith("/app/gateways/create-server");
  });

  it("navigates to the create server UI when empty server add-components row is clicked", async () => {
    const user = userEvent.setup();
    const mockServer: VirtualServer = {
      id: "gateway-empty",
      name: "peach-thistle-shark",
      description: "",
      icon: "",
      createdAt: "2026-04-16T13:23:12Z",
      updatedAt: "2026-04-16T13:23:12Z",
      enabled: false,
      associatedTools: [],
      associatedToolIds: [],
      associatedResources: [],
      associatedPrompts: [],
      associatedA2aAgents: [],
      metrics: null,
      tags: [],
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
      data: { servers: [mockServer] },
      error: null,
      isLoading: false,
      execute: vi.fn(),
      refetch: vi.fn(),
    });

    renderWithProviders(<Gateways />);

    await user.click(screen.getByRole("button", { name: "Add sources and components" }));

    expect(mockNavigate).toHaveBeenCalledWith("/app/gateways/create-server");
  });

  it("navigates to the create server UI when MCP server connect is clicked", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Gateways />);

    const buttons = screen.getAllByRole("button", { name: "+ Connect" });
    await user.click(buttons[0]!);

    expect(mockNavigate).toHaveBeenCalledWith("/app/gateways/create-server");
  });

  it("disables REST API and gRPC connect buttons until they are implemented", () => {
    renderWithProviders(<Gateways />);

    const buttons = screen.getAllByRole("button", { name: /\+ Connect/ });
    expect(buttons).toHaveLength(4);
    expect(buttons[0]).toBeEnabled();
    expect(buttons[1]).toBeEnabled();
    expect(buttons[2]).toBeDisabled();
    expect(buttons[3]).toBeDisabled();
  });

  it("does not navigate when a disabled connect button is clicked", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Gateways />);

    const buttons = screen.getAllByRole("button", { name: /\+ Connect/ });
    await user.click(buttons[2]!);

    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it("disables card-level selection on disabled action cards", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Gateways />);

    const restCard = screen.getByTestId("action-card-REST API");
    expect(restCard).toHaveAttribute("aria-disabled", "true");
    await user.click(restCard);
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it("opens virtual server details and keeps unfinished row actions disabled", async () => {
    const user = userEvent.setup();
    const mockServer: VirtualServer = {
      id: "gateway/1?mode=detail",
      name: "GH repo tasks",
      description: "Test server",
      icon: "",
      createdAt: "2026-04-16T13:23:12Z",
      updatedAt: "2026-04-16T13:23:12Z",
      enabled: true,
      associatedTools: [],
      associatedToolIds: [],
      associatedResources: [],
      associatedPrompts: [],
      associatedA2aAgents: [],
      metrics: null,
      tags: [],
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
    const detailServer: VirtualServer = {
      ...mockServer,
      description:
        "Virtual server endpoint: developer tooling server exposing file system utilities.",
      associatedTools: ["Get Repo Issues", "Create New Issue"],
      associatedToolIds: ["GITHUB_GET_REPO_ISSUES", "GITHUB_CREATE_ISSUE"],
      associatedResources: ["github://repo/{owner}/{repo}"],
      associatedPrompts: ["summarize_pull_request"],
      tags: [{ id: "tag-development", label: "development" }],
    };

    mockUseQuery.mockImplementation((path) => {
      if (path === "/servers/gateway%2F1%3Fmode%3Ddetail") {
        return {
          data: detailServer,
          error: null,
          isLoading: false,
          execute: vi.fn(),
          refetch: vi.fn(),
        };
      }

      if (path === "/servers/gateway%2F1%3Fmode%3Ddetail/tools?include_inactive=true") {
        return {
          data: [
            {
              id: "tool-gh-issues",
              name: "GITHUB_GET_REPO_ISSUES",
              title: "Get Repo Issues",
              originalName: "GITHUB_GET_REPO_ISSUES",
            },
            {
              id: "tool-create-issue",
              name: "GITHUB_CREATE_ISSUE",
              title: "Create New Issue",
              originalName: "GITHUB_CREATE_ISSUE",
            },
          ],
          error: null,
          isLoading: false,
          execute: vi.fn(),
          refetch: vi.fn(),
        };
      }

      if (path === "/servers/gateway%2F1%3Fmode%3Ddetail/resources?include_inactive=true") {
        return {
          data: [
            {
              id: "resource-gh-repo",
              name: "github repo",
              uri: "github://repo/{owner}/{repo}",
            },
          ],
          error: null,
          isLoading: false,
          execute: vi.fn(),
          refetch: vi.fn(),
        };
      }

      if (path === "/servers/gateway%2F1%3Fmode%3Ddetail/prompts?include_inactive=true") {
        return {
          data: [
            {
              id: "prompt-summarize-pr",
              name: "summarize_pull_request",
              originalName: "summarize_pull_request",
            },
          ],
          error: null,
          isLoading: false,
          execute: vi.fn(),
          refetch: vi.fn(),
        };
      }

      return {
        data: { servers: [mockServer] },
        error: null,
        isLoading: false,
        execute: vi.fn(),
        refetch: vi.fn(),
      };
    });

    renderWithProviders(<Gateways />);

    await user.click(screen.getByRole("button", { name: "Actions for GH repo tasks" }));

    const viewDetails = await screen.findByRole("menuitem", { name: "View details" });
    expect(viewDetails).not.toHaveAttribute("data-disabled");

    for (const label of ["Test connection", "Edit server", "Delete"]) {
      const item = await screen.findByRole("menuitem", { name: label });
      expect(item).toHaveAttribute("data-disabled");
    }

    await user.click(viewDetails);

    expect(mockUseQuery).toHaveBeenCalledWith("/servers/gateway%2F1%3Fmode%3Ddetail");
    expect(mockUseQuery).toHaveBeenCalledWith(
      "/servers/gateway%2F1%3Fmode%3Ddetail/tools?include_inactive=true",
      { enabled: true },
    );
    expect(mockUseQuery).toHaveBeenCalledWith(
      "/servers/gateway%2F1%3Fmode%3Ddetail/resources?include_inactive=true",
      { enabled: true },
    );
    expect(mockUseQuery).toHaveBeenCalledWith(
      "/servers/gateway%2F1%3Fmode%3Ddetail/prompts?include_inactive=true",
      { enabled: true },
    );
    expect(mockUseQuery).not.toHaveBeenCalledWith(
      expect.stringContaining("virtual_server_id"),
      expect.anything(),
    );
    expect(mockUseQuery).not.toHaveBeenCalledWith("/servers/__pending__", expect.anything());
    expect(screen.getByText("Virtual server details")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Virtual server endpoint: developer tooling server exposing file system utilities.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Status")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText("Visibility")).toBeInTheDocument();
    expect(screen.getByText("Team")).toBeInTheDocument();
    expect(screen.getByText("Server ID")).toBeInTheDocument();
    expect(screen.getByLabelText("Copy URL")).toBeInTheDocument();
    expect(screen.getByText("Activity")).toBeInTheDocument();
    const drawerAddSourcesButton = screen.getByRole("button", { name: "Add source" });
    expect(drawerAddSourcesButton).toBeInTheDocument();
    await user.click(drawerAddSourcesButton);
    expect(mockNavigate).toHaveBeenCalledWith("/app/gateways/create-server");
    expect(screen.queryByRole("button", { name: "Add components" })).not.toBeInTheDocument();
    expect(screen.getByText("Get Repo Issues")).toBeInTheDocument();
    expect(screen.getByText("GITHUB_GET_REPO_ISSUES")).toBeInTheDocument();
    expect(screen.getAllByText("github://repo/{owner}/{repo}").length).toBeGreaterThan(0);
    expect(screen.getAllByText("summarize_pull_request").length).toBeGreaterThan(0);

    await user.click(screen.getByRole("tab", { name: "Tools" }));

    expect(screen.getByText("Create New Issue")).toBeInTheDocument();
    expect(screen.queryByText("github://repo/{owner}/{repo}")).not.toBeInTheDocument();
    expect(screen.queryByText("summarize_pull_request")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Close virtual server details" }));
    await user.click(screen.getByRole("button", { name: "Actions for GH repo tasks" }));
    await user.click(await screen.findByRole("menuitem", { name: "View details" }));

    expect(screen.getAllByText("github://repo/{owner}/{repo}").length).toBeGreaterThan(0);
    expect(screen.getAllByText("summarize_pull_request").length).toBeGreaterThan(0);
  });

  it("renders virtual server card without crashing when array fields are missing", () => {
    const partialServer: VirtualServer = {
      id: "gateway-2",
      name: "Sparse server",
      description: "",
      icon: "",
      createdAt: "2026-04-16T13:23:12Z",
      updatedAt: "",
      enabled: false,
      visibility: "team",
      teamId: "team-1",
      team: "Test Team",
      ownerEmail: "admin@example.com",
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
      metrics: null,
      oauthEnabled: false,
      oauthConfig: null,
    };

    mockUseQuery.mockReturnValue({
      data: { servers: [partialServer] },
      error: null,
      isLoading: false,
      execute: vi.fn(),
      refetch: vi.fn(),
    });

    renderWithProviders(<Gateways />);

    expect(screen.getByText("Sparse server")).toBeInTheDocument();
    const card = screen.getByTestId("virtual-server-card");
    expect(card).toBeInTheDocument();
    expect(card).toHaveClass("col-span-full");
    expect(screen.getByRole("button", { name: "Add sources and components" })).toBeInTheDocument();
    expect(card.querySelector('[data-testid="tool-count"]')).not.toBeInTheDocument();
    expect(card.querySelector('[data-testid="resource-count"]')).not.toBeInTheDocument();
    expect(card.querySelector('[data-testid="prompt-count"]')).not.toBeInTheDocument();
  });
});
