import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { createElement, type ComponentType } from "react";
import { server } from "@/test/mocks/server";
import { renderWithProviders } from "@/test/test-utils";
import { createVirtualServer, updateVirtualServer } from "@/api/virtualServers";
import { ApiError } from "@/api/client";
import { CreateServer } from "./CreateServer";

interface MockCreateServerFormProps {
  onSuccess: (details: Record<string, unknown> | null) => void;
  initialValues?: Record<string, unknown>;
  title?: string;
  submitLabel?: string;
  submitError?: string | null;
}

interface MockSourceSelectionProps {
  createServerActions: {
    onSkip: () => Promise<void>;
  };
}

const componentMockState = vi.hoisted(() => ({
  mockForm: false,
  capturedProps: null as MockCreateServerFormProps | null,
  mockSourceSelection: false,
  capturedSourceSelectionProps: null as MockSourceSelectionProps | null,
}));

const routerMock = vi.hoisted(() => ({
  navigate: vi.fn(),
  path: "/app/gateways/create-server",
}));

vi.mock("@/components/gateways/CreateServerForm", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    CreateServerForm: (props: MockCreateServerFormProps) => {
      if (componentMockState.mockForm) {
        componentMockState.capturedProps = props;
        return <div data-testid="mock-create-server-form" />;
      }
      return createElement(
        actual.CreateServerForm as ComponentType<MockCreateServerFormProps>,
        props,
      );
    },
  };
});

vi.mock("@/components/gateways/SourceSelection", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    SourceSelection: (props: MockSourceSelectionProps) => {
      if (componentMockState.mockSourceSelection) {
        componentMockState.capturedSourceSelectionProps = props;
        return <div data-testid="mock-source-selection" />;
      }
      return createElement(
        actual.SourceSelection as ComponentType<MockSourceSelectionProps>,
        props,
      );
    },
  };
});

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
    componentMockState.mockForm = false;
    componentMockState.capturedProps = null;
    componentMockState.mockSourceSelection = false;
    componentMockState.capturedSourceSelectionProps = null;
    routerMock.path = "/app/gateways/create-server";
    mockNavigate.mockClear();
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
    expect(screen.getByRole("radio", { name: /Public/ })).toBeChecked();
    expect(screen.getByRole("switch", { name: /Require OAuth/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Optional configuration" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Tags")).not.toBeInTheDocument();
  });

  it("renders stored edit details and updates the virtual server", async () => {
    componentMockState.mockForm = true;
    routerMock.path = "/app/gateways/create-server?editServerId=gateway-1";
    server.use(
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
    );

    renderWithProviders(<CreateServer />);

    expect(await screen.findByTestId("mock-create-server-form")).toBeInTheDocument();
    await waitFor(() => {
      expect(componentMockState.capturedProps?.title).toBe("Edit server");
      expect(componentMockState.capturedProps?.submitLabel).toBe("Submit");
      expect(componentMockState.capturedProps?.initialValues).toMatchObject({
        name: "GH repo tasks",
        description: "Test server",
        visibility: "team",
        oauthEnabled: false,
        tags: ["team", "enabled"],
        teamId: "team-1",
      });
    });

    // Wait a tick to ensure the useEffect that sets selectedComponents has run
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    await act(async () => {
      componentMockState.capturedProps?.onSuccess({
        name: "Updated GH repo tasks",
        description: "Updated server",
        visibility: "public",
        oauthEnabled: false,
        tags: ["updated"],
      });
    });

    await waitFor(() => {
      expect(mockUpdateVirtualServer).toHaveBeenCalledWith(
        "gateway-1",
        expect.objectContaining({
          name: "Updated GH repo tasks",
          description: "Updated server",
          visibility: "public",
          oauthEnabled: false,
          tags: ["updated"],
          associatedTools: ["existing-tool-id"],
          associatedResources: ["existing-resource-id"],
          associatedPrompts: ["existing-prompt-id"],
        }),
      );
    });
    expect(mockCreateVirtualServer).not.toHaveBeenCalled();
    expect(mockNavigate).toHaveBeenCalledWith("/app/gateways");
  });

  it("shows an error when edit server details cannot be loaded", async () => {
    routerMock.path = "/app/gateways/create-server?editServerId=missing-server";
    server.use(
      http.get("*/servers/missing-server", () =>
        HttpResponse.json({ detail: "Virtual server not found" }, { status: 404 }),
      ),
    );

    renderWithProviders(<CreateServer />);

    expect(await screen.findByRole("alert")).toHaveTextContent("HTTP 404");
    expect(screen.queryByRole("heading", { name: "Edit server" })).not.toBeInTheDocument();
  });

  it("shows an error when updating an edited virtual server fails", async () => {
    componentMockState.mockForm = true;
    routerMock.path = "/app/gateways/create-server?editServerId=gateway-1";
    mockUpdateVirtualServer.mockRejectedValueOnce(new Error("Update failed"));
    server.use(
      http.get("*/servers/gateway-1", () =>
        HttpResponse.json({
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
          visibility: "public",
          oauthEnabled: false,
          oauthConfig: null,
        }),
      ),
    );

    renderWithProviders(<CreateServer />);

    expect(await screen.findByTestId("mock-create-server-form")).toBeInTheDocument();
    await act(async () => {
      componentMockState.capturedProps?.onSuccess({
        name: "GH repo tasks",
        description: "Test server",
        visibility: "public",
        oauthEnabled: false,
        tags: [],
      });
    });

    await waitFor(() => {
      expect(componentMockState.capturedProps?.submitError).toBe("Update failed");
    });
    expect(mockUpdateVirtualServer).toHaveBeenCalledOnce();
    expect(mockCreateVirtualServer).not.toHaveBeenCalled();
    expect(mockNavigate).not.toHaveBeenCalledWith("/app/gateways");
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
    const toolCursors: Array<string | null> = [];
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
      http.get("*/tools", ({ request }) => {
        const url = new URL(request.url);
        const gatewayId = url.searchParams.get("gateway_id");
        const cursor = url.searchParams.get("cursor");
        toolCursors.push(cursor);
        return HttpResponse.json({
          tools:
            gatewayId === "github-notify" && !cursor
              ? [{ id: "tool-alpha", name: "alpha-tool" }]
              : gatewayId === "github-notify" && cursor === "tools-page-2"
                ? [{ id: "tool-beta", name: "beta-tool" }]
                : [],
          nextCursor: gatewayId === "github-notify" && !cursor ? "tools-page-2" : null,
        });
      }),
      http.get("*/resources", ({ request }) => {
        const gatewayId = new URL(request.url).searchParams.get("gateway_id");
        return HttpResponse.json({
          resources:
            gatewayId === "github-notify" ? [{ id: "resource-alpha", name: "alpha-resource" }] : [],
        });
      }),
      http.get("*/prompts", ({ request }) => {
        const gatewayId = new URL(request.url).searchParams.get("gateway_id");
        return HttpResponse.json({
          prompts:
            gatewayId === "github-notify" ? [{ id: "prompt-alpha", name: "alpha-prompt" }] : [],
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

    await user.click(screen.getByRole("checkbox", { name: "Select github-notify" }));
    expect(screen.getByRole("button", { name: "Submit" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Submit" }));
    await waitFor(() => {
      expect(toolCursors).toEqual([null, "tools-page-2"]);
      expect(mockCreateVirtualServer).toHaveBeenCalledWith({
        name: "Research server",
        visibility: "public",
        oauthEnabled: false,
        associatedTools: ["tool-alpha", "tool-beta"],
        associatedResources: ["resource-alpha"],
        associatedPrompts: ["prompt-alpha"],
        associatedMCPServerIds: ["github-notify"],
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

  it("shows ApiError message when body contains message", async () => {
    const user = userEvent.setup();
    const apiError = new ApiError(400, { message: "Api message error" }, "");
    mockCreateVirtualServer.mockRejectedValueOnce(apiError);
    renderWithProviders(<CreateServer />);

    await user.type(screen.getByLabelText(/Name/), "Research server");
    await user.click(screen.getByRole("button", { name: /Continue/ }));
    await screen.findByRole("heading", { name: "Connect a source" });
    await user.click(screen.getByRole("button", { name: "Skip for now" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Api message error");
  });

  it("shows ApiError message when body contains detail as string", async () => {
    const user = userEvent.setup();
    const apiError = new ApiError(400, { detail: "Api detail string error" }, "");
    mockCreateVirtualServer.mockRejectedValueOnce(apiError);
    renderWithProviders(<CreateServer />);

    await user.type(screen.getByLabelText(/Name/), "Research server");
    await user.click(screen.getByRole("button", { name: /Continue/ }));
    await screen.findByRole("heading", { name: "Connect a source" });
    await user.click(screen.getByRole("button", { name: "Skip for now" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Api detail string error");
  });

  it("shows ApiError message when body contains detail as array of validation errors", async () => {
    const user = userEvent.setup();
    const apiError = new ApiError(400, { detail: [{ msg: "Msg 1" }, "String msg 2"] }, "");
    mockCreateVirtualServer.mockRejectedValueOnce(apiError);
    renderWithProviders(<CreateServer />);

    await user.type(screen.getByLabelText(/Name/), "Research server");
    await user.click(screen.getByRole("button", { name: /Continue/ }));
    await screen.findByRole("heading", { name: "Connect a source" });
    await user.click(screen.getByRole("button", { name: "Skip for now" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Msg 1; String msg 2");
  });

  it("shows fallback message when error is arbitrary object", async () => {
    const user = userEvent.setup();
    mockCreateVirtualServer.mockRejectedValueOnce({ raw: "some raw error" });
    renderWithProviders(<CreateServer />);

    await user.type(screen.getByLabelText(/Name/), "Research server");
    await user.click(screen.getByRole("button", { name: /Continue/ }));
    await screen.findByRole("heading", { name: "Connect a source" });
    await user.click(screen.getByRole("button", { name: "Skip for now" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Unable to create server. Please try again.",
    );
  });

  it("should set step back to details if handleSkipForNow is called and serverDetails is null", async () => {
    componentMockState.mockForm = true;
    componentMockState.mockSourceSelection = true;
    try {
      renderWithProviders(<CreateServer />);

      // Step 1: Trigger success on the form with null details
      act(() => {
        componentMockState.capturedProps?.onSuccess(null);
      });

      // Now step should be sources, and SourceSelection should render
      expect(screen.getByTestId("mock-source-selection")).toBeInTheDocument();

      // Step 2: Trigger onSkip from SourceSelection
      await act(async () => {
        await componentMockState.capturedSourceSelectionProps?.createServerActions.onSkip();
      });

      // Step should set back to details, rendering CreateServerForm again
      expect(screen.getByTestId("mock-create-server-form")).toBeInTheDocument();
    } finally {
      componentMockState.mockForm = false;
      componentMockState.mockSourceSelection = false;
    }
  });
});
