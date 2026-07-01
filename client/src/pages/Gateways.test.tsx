import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import { renderWithProviders } from "@/test/test-utils";
import { Gateways } from "./Gateways";
import { useQuery } from "@/hooks/useQuery";
import { deleteVirtualServer } from "@/api/virtualServers";
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

vi.mock("@/api/virtualServers", () => ({
  deleteVirtualServer: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
  },
}));

const mockUseQuery = vi.mocked(useQuery);
const mockDeleteVirtualServer = vi.mocked(deleteVirtualServer);
const mockToastError = vi.mocked(toast.error);

describe("Gateways", () => {
  beforeEach(() => {
    mockNavigate.mockClear();
    mockToastError.mockClear();
    mockDeleteVirtualServer.mockReset();
    mockDeleteVirtualServer.mockResolvedValue(undefined);
    mockUseQuery.mockReturnValue({
      data: { servers: [] },
      error: null,
      isLoading: false,
      execute: vi.fn(),
      refetch: vi.fn().mockResolvedValue({ servers: [] }),
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

  it("renders a loading state when servers are loading", () => {
    mockUseQuery.mockReturnValue({
      data: undefined,
      error: null,
      isLoading: true,
      execute: vi.fn(),
      refetch: vi.fn(),
    });

    renderWithProviders(<Gateways />);

    expect(screen.getAllByRole("status")[0]).toBeInTheDocument();
    expect(screen.getByText("Loading virtual servers, please wait...")).toBeInTheDocument();
  });

  it("renders the virtual server layout when servers exist", async () => {
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

    await user.click(screen.getByRole("button", { name: "Actions for GH repo tasks" }));

    expect(await screen.findByRole("menuitem", { name: "View details" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Deactivate" })).not.toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Delete" })).not.toHaveAttribute("data-disabled");
  });

  it("navigates to the create-server form with edit details when edit is clicked", async () => {
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
      data: { servers: [mockServer] },
      error: null,
      isLoading: false,
      execute: vi.fn(),
      refetch: vi.fn(),
    });

    renderWithProviders(<Gateways />);

    await user.click(screen.getByRole("button", { name: "Actions for GH repo tasks" }));
    await user.click(await screen.findByRole("menuitem", { name: "Edit server" }));

    expect(mockNavigate).toHaveBeenCalledWith("/app/gateways/create-server?editServerId=gateway-1");
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

  it("opens virtual server details from the actions menu", async () => {
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
    expect(viewDetails).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Delete" })).not.toHaveAttribute("data-disabled");

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
    const detailsPanel = screen.getByRole("region", { name: "GH repo tasks details" });
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
    expect(detailsPanel).toHaveAttribute("data-state", "closed");
    expect(detailsPanel).toHaveAttribute("aria-hidden", "true");
    await user.click(screen.getByRole("button", { name: "Actions for GH repo tasks" }));
    await user.click(await screen.findByRole("menuitem", { name: "View details" }));

    expect(screen.getAllByText("github://repo/{owner}/{repo}").length).toBeGreaterThan(0);
    expect(screen.getAllByText("summarize_pull_request").length).toBeGreaterThan(0);
  });

  it("confirms and deletes a virtual server", async () => {
    const user = userEvent.setup();
    const refetch = vi.fn().mockResolvedValue({ servers: [] });
    const mockServer: VirtualServer = {
      id: "gateway/1?mode=delete",
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
      refetch,
    });

    renderWithProviders(<Gateways />);

    await user.click(screen.getByRole("button", { name: "Actions for GH repo tasks" }));
    await user.click(await screen.findByRole("menuitem", { name: "Delete" }));

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Delete virtual server")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Are you sure you want to delete GH repo tasks? This action cannot be undone.",
      ),
    ).toBeInTheDocument();
    expect(mockDeleteVirtualServer).not.toHaveBeenCalled();

    await user.click(await screen.findByRole("button", { name: "Delete" }));

    expect(mockDeleteVirtualServer).toHaveBeenCalledWith("gateway/1?mode=delete");
    await waitFor(() => expect(refetch).toHaveBeenCalledOnce());
    expect(screen.getByRole("status")).toHaveTextContent("GH repo tasks deleted.");
    await waitFor(() => expect(screen.queryByText("GH repo tasks")).not.toBeInTheDocument());
  });

  it("logs an error if refetch fails after a successful deletion", async () => {
    const user = userEvent.setup();
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const mockServer = {
      id: "gateway-1",
      name: "GH repo tasks",
      description: "",
      icon: "",
      createdAt: "",
      updatedAt: "",
      enabled: true,
      associatedTools: [],
      associatedToolIds: [],
      associatedResources: [],
      associatedPrompts: [],
      associatedA2aAgents: [],
      metrics: null,
      tags: [],
      createdBy: "",
      createdFromIp: "",
      createdVia: "",
      createdUserAgent: "",
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
      visibility: "team" as const,
      oauthEnabled: false,
      oauthConfig: null,
    };

    const mockRefetch = vi.fn().mockRejectedValue(new Error("refetch failed"));

    mockUseQuery.mockReturnValue({
      data: { servers: [mockServer] },
      error: null,
      isLoading: false,
      execute: vi.fn(),
      refetch: mockRefetch,
    });
    mockDeleteVirtualServer.mockResolvedValue(undefined);

    renderWithProviders(<Gateways />);

    await user.click(screen.getByRole("button", { name: "Actions for GH repo tasks" }));
    await user.click(await screen.findByRole("menuitem", { name: "Delete" }));
    await user.click(await screen.findByRole("button", { name: "Delete" }));

    expect(mockDeleteVirtualServer).toHaveBeenCalledWith("gateway-1");
    expect(mockRefetch).toHaveBeenCalled();
    expect(consoleSpy).toHaveBeenCalledWith(
      "Failed to refresh virtual servers after deletion:",
      "Network error. Please check your connection and try again.",
    );

    consoleSpy.mockRestore();
  });

  it("shows delete progress and blocks repeated delete requests while pending", async () => {
    const user = userEvent.setup();
    let resolveDelete!: () => void;
    const deletePromise = new Promise<void>((resolve) => {
      resolveDelete = resolve;
    });
    const refetch = vi.fn().mockResolvedValue({ servers: [] });
    const mockServer: VirtualServer = {
      id: "gateway-pending",
      name: "Pending server",
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

    mockDeleteVirtualServer.mockReturnValue(deletePromise);
    mockUseQuery.mockReturnValue({
      data: { servers: [mockServer] },
      error: null,
      isLoading: false,
      execute: vi.fn(),
      refetch,
    });

    renderWithProviders(<Gateways />);

    await user.click(screen.getByRole("button", { name: "Actions for Pending server" }));
    await user.click(await screen.findByRole("menuitem", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));

    const deletingButton = screen.getByRole("button", { name: /Deleting/i });
    expect(deletingButton).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(mockDeleteVirtualServer).toHaveBeenCalledOnce();

    await user.click(deletingButton);
    expect(mockDeleteVirtualServer).toHaveBeenCalledOnce();

    resolveDelete();
    await waitFor(() => expect(refetch).toHaveBeenCalledOnce());
  });

  it("shows delete failures in a toast without rendering a page alert", async () => {
    const user = userEvent.setup();
    const refetch = vi.fn();
    const mockServer: VirtualServer = {
      id: "gateway-error",
      name: "Error server",
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

    mockDeleteVirtualServer.mockRejectedValue(new Error("HTTP 403: Forbidden"));
    mockUseQuery.mockReturnValue({
      data: { servers: [mockServer] },
      error: null,
      isLoading: false,
      execute: vi.fn(),
      refetch,
    });

    renderWithProviders(<Gateways />);

    await user.click(screen.getByRole("button", { name: "Actions for Error server" }));
    await user.click(await screen.findByRole("menuitem", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() =>
      expect(mockToastError).toHaveBeenCalledWith("Error deleting virtual server", {
        description: "You don't have permission to perform this action.",
      }),
    );
    expect(screen.getByText("Error server")).toBeInTheDocument();
    expect(screen.queryByText("Error deleting virtual server")).not.toBeInTheDocument();
    expect(refetch).not.toHaveBeenCalled();
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

  it("handles query failures for tools, resources, and prompts gracefully", async () => {
    const user = userEvent.setup();
    const mockServer: VirtualServer = {
      id: "gateway-1",
      name: "Test Server",
      description: "Test server",
      icon: "",
      createdAt: "2026-04-16T13:23:12Z",
      updatedAt: "2026-04-16T13:23:12Z",
      enabled: true,
      associatedTools: [],
      associatedToolIds: ["tool1"],
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

    mockUseQuery.mockImplementation((path) => {
      if (path === "/servers/gateway-1") {
        return {
          data: mockServer,
          error: null,
          isLoading: false,
          execute: vi.fn(),
          refetch: vi.fn(),
        };
      }

      if (path === "/servers/gateway-1/tools?include_inactive=true") {
        return {
          data: null,
          error: { message: "Failed to fetch tools" },
          isLoading: false,
          execute: vi.fn(),
          refetch: vi.fn(),
        };
      }

      if (path === "/servers/gateway-1/resources?include_inactive=true") {
        return {
          data: null,
          error: { message: "Failed to fetch resources" },
          isLoading: false,
          execute: vi.fn(),
          refetch: vi.fn(),
        };
      }

      if (path === "/servers/gateway-1/prompts?include_inactive=true") {
        return {
          data: null,
          error: { message: "Failed to fetch prompts" },
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

    await user.click(screen.getByRole("button", { name: "Actions for Test Server" }));
    await user.click(await screen.findByRole("menuitem", { name: "View details" }));

    expect(screen.getByText("Virtual server details")).toBeInTheDocument();
    expect(screen.queryByText("Failed to fetch tools")).not.toBeInTheDocument();
    expect(screen.queryByText("Failed to fetch resources")).not.toBeInTheDocument();
    expect(screen.queryByText("Failed to fetch prompts")).not.toBeInTheDocument();
  });

  it("renders an error message when the servers query fails and there are no servers", () => {
    mockUseQuery.mockReturnValue({
      data: null,
      error: new Error("Failed to fetch servers"),
      isLoading: false,
      execute: vi.fn(),
      refetch: vi.fn(),
    });

    renderWithProviders(<Gateways />);

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Error loading virtual servers" })).toBeInTheDocument();
    expect(screen.getByText("Failed to fetch servers")).toBeInTheDocument();
  });

  it("renders an error message when the servers query fails and there are existing servers", () => {
    const mockServer: VirtualServer = {
      id: "gateway-1",
      name: "Test Server",
      description: "Test server",
      icon: "",
      createdAt: "2026-04-16T13:23:12Z",
      updatedAt: "2026-04-16T13:23:12Z",
      enabled: true,
      associatedTools: [],
      associatedToolIds: ["tool1"],
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
      error: new Error("Failed to fetch servers"),
      isLoading: false,
      execute: vi.fn(),
      refetch: vi.fn(),
    });

    renderWithProviders(<Gateways />);

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Error loading virtual servers" })).toBeInTheDocument();
    expect(screen.getByText("Failed to fetch servers")).toBeInTheDocument();
    expect(screen.getByText(mockServer.name)).toBeInTheDocument();
  });
});
