import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { renderWithProviders } from "@/test/test-utils";
import { createVirtualServer, updateVirtualServer } from "@/api/virtualServers";
import { CreateServer } from "./CreateServer";

const routerMock = vi.hoisted(() => ({
  navigate: vi.fn(),
  path: "/app/gateways/create-server",
}));

vi.mock("@/router", () => ({
  useRouter: () => ({
    navigate: routerMock.navigate,
    path: routerMock.path,
    params: {},
  }),
}));

vi.mock("@/api/virtualServers", () => ({
  createVirtualServer: vi.fn(),
  updateVirtualServer: vi.fn(),
}));

const mockCreateVirtualServer = vi.mocked(createVirtualServer);
const mockUpdateVirtualServer = vi.mocked(updateVirtualServer);
const mockNavigate = routerMock.navigate;

describe("CreateServer", () => {
  beforeEach(() => {
    mockNavigate.mockClear();
    routerMock.path = "/app/gateways/create-server";
    mockCreateVirtualServer.mockReset();
    mockUpdateVirtualServer.mockReset();
    mockCreateVirtualServer.mockResolvedValue({
      id: "server-1",
      name: "Research server",
    } as Awaited<ReturnType<typeof createVirtualServer>>);
    mockUpdateVirtualServer.mockResolvedValue({
      id: "server-1",
      name: "Research server",
    } as Awaited<ReturnType<typeof updateVirtualServer>>);
  });

  it("renders accessible form fields", () => {
    renderWithProviders(<CreateServer />);

    expect(screen.getByRole("heading", { name: "Create server" })).toBeInTheDocument();
    expect(screen.getByLabelText(/Name/)).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Server Name")).toHaveValue("");
    expect(screen.getByRole("radio", { name: /Team/ })).toBeChecked();
    expect(screen.getByRole("switch", { name: /Require OAuth/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Optional configuration" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Tags")).not.toBeInTheDocument();
  });

  it("renders stored edit details and updates selected MCP server associations", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("*/gateways", () =>
        HttpResponse.json({
          gateways: [
            {
              id: "mcp-connected",
              name: "connected-source",
              url: "http://localhost:9000",
              transport: "SSE",
              enabled: true,
              reachable: true,
              visibility: "public",
              tool_count: 3,
              resource_count: 1,
              prompt_count: 2,
              created_at: "2024-01-01T00:00:00Z",
              updated_at: "2024-01-01T00:00:00Z",
            },
            {
              id: "mcp-available",
              name: "available-source",
              url: "http://localhost:9001",
              transport: "SSE",
              enabled: true,
              reachable: true,
              visibility: "public",
              tool_count: 2,
              resource_count: 1,
              prompt_count: 1,
              created_at: "2024-01-01T00:00:00Z",
              updated_at: "2024-01-01T00:00:00Z",
            },
          ],
        }),
      ),
      http.get("*/servers/gateway-1", () =>
        HttpResponse.json({
          id: "gateway-1",
          name: "GH repo tasks",
          description: "Test server",
          icon: "",
          createdAt: "2026-04-16T13:23:12Z",
          updatedAt: "2026-04-16T13:23:12Z",
          enabled: true,
          associatedTools: ["existing-tool"],
          associatedToolIds: ["existing-tool-id"],
          associatedResources: ["existing-resource-id"],
          associatedPrompts: ["existing-prompt-id"],
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
        }),
      ),
      http.get("*/servers/gateway-1/tools", () =>
        HttpResponse.json({
          tools: [
            {
              id: "existing-tool-id",
              name: "existing-tool",
              originalName: "existing-tool",
            },
          ],
        }),
      ),
      http.get("*/servers/gateway-1/resources", () =>
        HttpResponse.json({
          resources: [
            {
              id: "existing-resource-id",
              name: "existing-resource",
              uri: "mcp://existing-resource",
            },
          ],
        }),
      ),
      http.get("*/servers/gateway-1/prompts", () =>
        HttpResponse.json({
          prompts: [
            {
              id: "existing-prompt-id",
              name: "existing-prompt",
              originalName: "existing-prompt",
            },
          ],
        }),
      ),
      http.get("*/tools", ({ request }) => {
        const gatewayId = new URL(request.url).searchParams.get("gateway_id");
        if (gatewayId === "mcp-connected") {
          return HttpResponse.json([
            {
              id: "existing-tool-id",
              name: "existing-tool",
              originalName: "existing-tool",
              gateway_id: "mcp-connected",
            },
          ]);
        }
        if (gatewayId !== "mcp-available") return HttpResponse.json([]);
        return HttpResponse.json([
          {
            id: "available-tool-id",
            name: "available-tool",
            originalName: "available-tool",
            gateway_id: "mcp-available",
          },
        ]);
      }),
      http.get("*/resources", ({ request }) => {
        const gatewayId = new URL(request.url).searchParams.get("gateway_id");
        if (gatewayId === "mcp-connected") {
          return HttpResponse.json([
            {
              id: "existing-resource-id",
              name: "existing-resource",
              uri: "mcp://existing-resource",
              gateway_id: "mcp-connected",
            },
          ]);
        }
        if (gatewayId !== "mcp-available") return HttpResponse.json([]);
        return HttpResponse.json([
          {
            id: "available-resource-id",
            name: "available-resource",
            uri: "mcp://available-resource",
            gateway_id: "mcp-available",
          },
        ]);
      }),
      http.get("*/prompts", ({ request }) => {
        const gatewayId = new URL(request.url).searchParams.get("gateway_id");
        if (gatewayId === "mcp-connected") {
          return HttpResponse.json([
            {
              id: "existing-prompt-id",
              name: "existing-prompt",
              originalName: "existing-prompt",
              gateway_id: "mcp-connected",
            },
          ]);
        }
        if (gatewayId !== "mcp-available") return HttpResponse.json([]);
        return HttpResponse.json([
          {
            id: "available-prompt-id",
            name: "available-prompt",
            originalName: "available-prompt",
            gateway_id: "mcp-available",
          },
        ]);
      }),
    );
    routerMock.path = "/app/gateways/create-server?editServerId=gateway-1";

    renderWithProviders(<CreateServer />);

    expect(await screen.findByRole("heading", { name: "Edit server" })).toBeInTheDocument();
    expect(screen.getByLabelText(/Name/)).toHaveValue("GH repo tasks");
    expect(screen.getByLabelText("Tags")).toHaveValue("team, enabled");
    expect(screen.getByLabelText("Virtual server description")).toHaveValue("Test server");
    expect(screen.getByRole("button", { name: "Submit" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Continue" })).not.toBeInTheDocument();
    const mcpServersSection = screen.getByRole("region", { name: "MCP server" });
    await within(mcpServersSection).findByText("connected-source");
    expect(within(mcpServersSection).getByText("available-source")).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Connected MCP servers" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Available MCP servers" }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /connected-source/ }));
    const existingToolCheckbox = await screen.findByRole("checkbox", {
      name: "Select existing-tool",
    });
    const existingResourceCheckbox = await screen.findByRole("checkbox", {
      name: "Select existing-resource",
    });
    const existingPromptCheckbox = await screen.findByRole("checkbox", {
      name: "Select existing-prompt",
    });
    expect(existingToolCheckbox).toBeChecked();
    expect(existingResourceCheckbox).toBeChecked();
    expect(existingPromptCheckbox).toBeChecked();
    await user.click(existingToolCheckbox);
    await user.click(existingResourceCheckbox);
    await user.click(existingPromptCheckbox);

    await user.click(screen.getByRole("button", { name: /available-source/ }));
    const availableToolCheckbox = await screen.findByRole("checkbox", {
      name: "Select available-tool",
    });
    const availableResourceCheckbox = await screen.findByRole("checkbox", {
      name: "Select available-resource",
    });
    const availablePromptCheckbox = await screen.findByRole("checkbox", {
      name: "Select available-prompt",
    });
    expect(availableToolCheckbox).not.toBeChecked();
    expect(availableResourceCheckbox).not.toBeChecked();
    expect(availablePromptCheckbox).not.toBeChecked();
    await user.click(availableToolCheckbox);
    await user.click(availableResourceCheckbox);
    await user.click(availablePromptCheckbox);

    const nameInput = screen.getByLabelText(/Name/);
    await user.clear(nameInput);
    await user.type(nameInput, "Updated GH repo tasks");
    await user.click(screen.getByRole("button", { name: "Submit" }));

    await waitFor(() => {
      expect(mockUpdateVirtualServer).toHaveBeenCalledWith(
        "gateway-1",
        expect.objectContaining({
          name: "Updated GH repo tasks",
          description: "Test server",
          tags: ["team", "enabled"],
          visibility: "team",
          oauthEnabled: false,
          associatedTools: ["available-tool-id"],
          associatedResources: ["available-resource-id"],
          associatedPrompts: ["available-prompt-id"],
        }),
      );
    });
    expect(mockCreateVirtualServer).not.toHaveBeenCalled();
    expect(mockNavigate).toHaveBeenCalledWith("/app/gateways");
  });

  it("shows optional configuration fields when expanded", async () => {
    const user = userEvent.setup();
    renderWithProviders(<CreateServer />);

    await user.click(screen.getByRole("button", { name: "Optional configuration" }));

    expect(screen.getByRole("button", { name: "Optional configuration" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.getByLabelText("Tags")).toBeInTheDocument();
    expect(screen.getByLabelText("Virtual server description")).toBeInTheDocument();
  });

  it("opens source selection actions without creating a virtual server", async () => {
    const user = userEvent.setup();
    renderWithProviders(<CreateServer />);

    await user.click(screen.getByRole("button", { name: "Optional configuration" }));
    await user.clear(screen.getByLabelText(/Name/));
    await user.type(screen.getByLabelText(/Name/), "Research server");
    await user.type(screen.getByLabelText("Tags"), "research, tools, research");
    await user.type(
      screen.getByLabelText("Virtual server description"),
      "A composed endpoint for research tools.",
    );
    await user.click(screen.getByRole("radio", { name: /Private/ }));
    await user.click(screen.getByRole("switch", { name: /Require OAuth/i }));
    await user.click(screen.getByRole("button", { name: /Continue/ }));

    expect(screen.getByRole("heading", { name: "Connect a source" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Back" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Add tools, resources, and prompts from connected sources",
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Skip for now" })).toBeInTheDocument();
    expect(screen.getByText(/Server details completed for Research server/i)).toBeInTheDocument();
    expect(mockCreateVirtualServer).not.toHaveBeenCalled();
    expect(mockNavigate).not.toHaveBeenCalledWith("/app/gateways");
  });

  it("supports source selection actions after continuing from details", async () => {
    const user = userEvent.setup();
    let gatewaysRequestCount = 0;
    server.use(
      http.get("*/gateways", () => {
        gatewaysRequestCount += 1;
        return HttpResponse.json({
          gateways: [
            {
              id: "github-notify",
              name: "github-notify",
              url: "http://localhost:9000",
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

    renderWithProviders(<CreateServer />);

    await user.type(screen.getByLabelText(/Name/), "Research server");
    await user.click(screen.getByRole("button", { name: /Continue/ }));
    await screen.findByRole("heading", { name: "Connect a source" });
    expect(gatewaysRequestCount).toBe(0);

    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByRole("heading", { name: "Create server" })).toBeInTheDocument();
    expect(screen.getByLabelText(/Name/)).toHaveValue("Research server");

    await user.click(screen.getByRole("button", { name: /Continue/ }));
    await screen.findByRole("heading", { name: "Connect a source" });

    await user.click(
      screen.getByRole("button", {
        name: "Add tools, resources, and prompts from connected sources",
      }),
    );
    expect(await screen.findByText("github-notify")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(gatewaysRequestCount).toBe(1);
    expect(mockNavigate).not.toHaveBeenCalledWith("/app/tools");

    await user.click(screen.getByRole("button", { name: "Skip for now" }));
    await waitFor(() => {
      expect(mockCreateVirtualServer).toHaveBeenCalledWith({
        name: "Research server",
        visibility: "team",
        oauthEnabled: false,
        associatedMCPServerIds: [],
      });
    });
    expect(mockNavigate).toHaveBeenCalledWith("/app/gateways");
  });

  it("creates a virtual server with optional details when skipping source selection", async () => {
    const user = userEvent.setup();
    renderWithProviders(<CreateServer />);

    await user.click(screen.getByRole("button", { name: "Optional configuration" }));
    await user.type(screen.getByLabelText(/Name/), "Research server");
    await user.type(screen.getByLabelText("Tags"), "research, tools");
    await user.type(
      screen.getByLabelText("Virtual server description"),
      "A composed endpoint for research tools.",
    );
    await user.click(screen.getByRole("radio", { name: /Private/ }));
    await user.click(screen.getByRole("switch", { name: /Require OAuth/i }));
    await user.click(screen.getByRole("button", { name: /Continue/ }));
    await screen.findByRole("heading", { name: "Connect a source" });

    await user.click(screen.getByRole("button", { name: "Skip for now" }));

    await waitFor(() => {
      expect(mockCreateVirtualServer).toHaveBeenCalledWith({
        name: "Research server",
        visibility: "private",
        oauthEnabled: true,
        tags: ["research", "tools"],
        description: "A composed endpoint for research tools.",
        associatedMCPServerIds: [],
      });
    });
    expect(mockNavigate).toHaveBeenCalledWith("/app/gateways");
  });

  it("shows an error when skip creation fails", async () => {
    const user = userEvent.setup();
    mockCreateVirtualServer.mockRejectedValueOnce(new Error("Create failed"));
    renderWithProviders(<CreateServer />);

    await user.type(screen.getByLabelText(/Name/), "Research server");
    await user.click(screen.getByRole("button", { name: /Continue/ }));
    await screen.findByRole("heading", { name: "Connect a source" });
    await user.click(screen.getByRole("button", { name: "Skip for now" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Create failed");
    expect(mockNavigate).not.toHaveBeenCalledWith("/app/gateways");
  });

  it("opens the MCP server connection form from the post-create source selection", async () => {
    const user = userEvent.setup();
    renderWithProviders(<CreateServer />);

    await user.type(screen.getByLabelText(/Name/), "Research server");
    await user.click(screen.getByRole("button", { name: /Continue/ }));
    await screen.findByRole("heading", { name: "Connect a source" });

    await user.click(screen.getAllByRole("button", { name: "+ Connect" })[0]!);

    expect(mockNavigate).toHaveBeenCalledWith("/app/servers?openForm=true");
  });

  it("shows validation errors before submit", async () => {
    const user = userEvent.setup();
    renderWithProviders(<CreateServer />);

    await user.click(screen.getByRole("button", { name: /Continue/ }));

    expect(await screen.findByText("Server name is required.")).toBeInTheDocument();
  });
});
