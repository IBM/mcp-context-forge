import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { renderWithProviders } from "@/test/test-utils";
import { createVirtualServer, updateVirtualServer } from "@/api/virtualServers";
import { ApiError } from "@/api/client";
import { CreateServer } from "./CreateServer";

interface MockCreateServerFormProps {
  onSuccess: (details: Record<string, unknown> | null) => void;
}

interface MockSourceSelectionProps {
  createServerActions: {
    onSkip: () => Promise<void>;
  };
}

let mockForm = false;
let capturedProps: MockCreateServerFormProps | null = null;
let mockSourceSelection = false;
let capturedSourceSelectionProps: MockSourceSelectionProps | null = null;

vi.mock("@/components/gateways/CreateServerForm", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    CreateServerForm: (props: MockCreateServerFormProps) => {
      if (mockForm) {
        capturedProps = props;
        return <div data-testid="mock-create-server-form" />;
      }
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      return (actual.CreateServerForm as any)(props);
    },
  };
});

vi.mock("@/components/gateways/SourceSelection", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    SourceSelection: (props: MockSourceSelectionProps) => {
      if (mockSourceSelection) {
        capturedSourceSelectionProps = props;
        return <div data-testid="mock-source-selection" />;
      }
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      return (actual.SourceSelection as any)(props);
    },
  };
});

const mockNavigate = vi.fn();

let mockPath = "/app/gateways/create-server";

vi.mock("@/router", () => ({
  useRouter: () => ({
    navigate: mockNavigate,
    get path() {
      return mockPath;
    },
    params: {},
  }),
}));

vi.mock("@/api/virtualServers", () => ({
  createVirtualServer: vi.fn(),
  updateVirtualServer: vi.fn(),
}));

const mockCreateVirtualServer = vi.mocked(createVirtualServer);
const mockUpdateVirtualServer = vi.mocked(updateVirtualServer);

describe("CreateServer", () => {
  beforeEach(() => {
    mockForm = false;
    capturedProps = null;
    mockSourceSelection = false;
    capturedSourceSelectionProps = null;
    mockPath = "/app/gateways/create-server";
    mockNavigate.mockClear();
    mockCreateVirtualServer.mockReset();
    mockCreateVirtualServer.mockResolvedValue({
      id: "server-1",
      name: "Research server",
    } as Awaited<ReturnType<typeof createVirtualServer>>);
    mockUpdateVirtualServer.mockReset();
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
    mockForm = true;
    mockSourceSelection = true;
    try {
      renderWithProviders(<CreateServer />);

      // Step 1: Trigger success on the form with null details
      act(() => {
        capturedProps?.onSuccess(null);
      });

      // Now step should be sources, and SourceSelection should render
      expect(screen.getByTestId("mock-source-selection")).toBeInTheDocument();

      // Step 2: Trigger onSkip from SourceSelection
      await act(async () => {
        await capturedSourceSelectionProps?.createServerActions.onSkip();
      });

      // Step should set back to details, rendering CreateServerForm again
      expect(screen.getByTestId("mock-create-server-form")).toBeInTheDocument();
    } finally {
      mockForm = false;
      mockSourceSelection = false;
    }
  });

  describe("Edit Mode", () => {
    it("renders loading state initially in edit mode", () => {
      mockPath = "/app/gateways/create-server?editServerId=gateway-1";
      
      let resolvePromise: (value: any) => void;
      server.use(
        http.get("*/servers/gateway-1", () => {
          return new Promise((resolve) => {
            resolvePromise = resolve;
          });
        })
      );
      
      renderWithProviders(<CreateServer />);
      expect(screen.getAllByRole("status").length).toBeGreaterThan(0);
      expect(screen.getByText("Loading...")).toBeInTheDocument();
    });

    it("renders error state when fetch fails in edit mode", async () => {
      mockPath = "/app/gateways/create-server?editServerId=gateway-1";
      server.use(
        http.get("*/servers/gateway-1", () => {
          return HttpResponse.json({ detail: "Not found" }, { status: 404 });
        })
      );

      renderWithProviders(<CreateServer />);
      
      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeInTheDocument();
      });
      // The default error behavior from msw mock uses a fallback if there's no message
    });

    it("renders the edit form when data is loaded successfully", async () => {
      mockPath = "/app/gateways/create-server?editServerId=gateway-1";
      server.use(
        http.get("*/servers/gateway-1", () => {
          return HttpResponse.json({
            id: "gateway-1",
            name: "Test Edit Server",
            visibility: "team",
            oauthEnabled: false,
            tags: ["prod", "test"],
            description: "A test server for editing",
          });
        }),
        http.get("*/gateways", () => {
          return HttpResponse.json({ gateways: [] }, { status: 200 });
        })
      );

      renderWithProviders(<CreateServer />);
      
      await waitFor(() => {
        // "Edit server" is the title in Edit mode
        expect(screen.getByRole("heading", { name: "Edit server" })).toBeInTheDocument();
      });

      expect(screen.getByDisplayValue("Test Edit Server")).toBeInTheDocument();
    });

    it("renders MCP servers section in edit mode and allows source selection", async () => {
      mockPath = "/app/gateways/create-server?editServerId=gateway-1";
      server.use(
        http.get("*/servers/gateway-1", () => {
          return HttpResponse.json({
            id: "gateway-1",
            name: "Test Edit Server",
            visibility: "team",
            oauthEnabled: false,
          });
        }),
        http.get("*/gateways", () => {
          return HttpResponse.json({
            gateways: [
              {
                id: "mcp-server-1",
                name: "MCP Server 1",
                enabled: true,
                reachable: true,
                toolCount: 1,
                resourceCount: 2,
                promptCount: 3,
              },
            ],
          });
        }),
        http.get("*/tools", () => {
          return HttpResponse.json({ tools: [{ id: "tool-1", name: "Test Tool" }] });
        }),
        http.get("*/resources", () => {
          return HttpResponse.json({ resources: [{ id: "resource-1", name: "Test Resource" }] });
        }),
        http.get("*/prompts", () => {
          return HttpResponse.json({ prompts: [{ id: "prompt-1", name: "Test Prompt" }] });
        })
      );

      renderWithProviders(<CreateServer />);
      
      await waitFor(() => {
        expect(screen.getByRole("heading", { name: "Edit server" })).toBeInTheDocument();
      });

      // It should display MCP servers section
      expect(screen.getByText("MCP server")).toBeInTheDocument();
      
      // Wait for MCP Server to be loaded and rendered
      await waitFor(() => {
        expect(screen.getByText("MCP Server 1")).toBeInTheDocument();
      });

      // Expand the accordion
      const trigger = screen.getByText("MCP Server 1");
      act(() => {
        trigger.click();
      });

      // Wait for components to load
      await waitFor(() => {
        expect(screen.getByText("Test Tool")).toBeInTheDocument();
        expect(screen.getByText("Test Resource")).toBeInTheDocument();
        expect(screen.getByText("Test Prompt")).toBeInTheDocument();
      });
      
      // Select a tool
      const toolCheckbox = screen.getByLabelText("Select Test Tool");
      act(() => {
        toolCheckbox.click();
      });

      // Deselect the tool to cover line 606 (else nextIds.delete)
      act(() => {
        toolCheckbox.click();
      });
    });

    it("renders warning alert when mcpServers fails to load", async () => {
      mockPath = "/app/gateways/create-server?editServerId=gateway-1";
      server.use(
        http.get("*/servers/gateway-1", () => {
          return HttpResponse.json({
            id: "gateway-1",
            name: "Test Edit Server",
            visibility: "team",
            oauthEnabled: false,
          });
        }),
        http.get("*/gateways", () => {
          return HttpResponse.error();
        })
      );

      renderWithProviders(<CreateServer />);

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeInTheDocument();
      });
    });

    it("renders fallback error message when editServerError has no message", async () => {
      mockPath = "/app/gateways/create-server?editServerId=gateway-1";
      server.use(
        http.get("*/servers/gateway-1", () => {
          return HttpResponse.json(null);
        }),
        http.get("*/gateways", () => {
          return HttpResponse.json({ gateways: [] });
        })
      );

      renderWithProviders(<CreateServer />);

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeInTheDocument();
      });

      expect(screen.getByText("Unable to update server. Please try again.")).toBeInTheDocument();
    });

    it("calls updateVirtualServer and navigates when form is successfully submitted in edit mode", async () => {
      mockPath = "/app/gateways/create-server?editServerId=gateway-1";
      server.use(
        http.get("*/servers/gateway-1", () => {
          return HttpResponse.json({
            id: "gateway-1",
            name: "Test Edit Server",
            visibility: "team",
            oauthEnabled: false,
          });
        }),
        http.get("*/gateways", () => {
          return HttpResponse.json({ gateways: [] });
        })
      );

      mockForm = true;
      try {
        renderWithProviders(<CreateServer />);

        await waitFor(() => {
          expect(screen.getByTestId("mock-create-server-form")).toBeInTheDocument();
        });

        act(() => {
          capturedProps?.onSuccess({ name: "Updated Name" });
        });

        await waitFor(() => {
          expect(mockUpdateVirtualServer).toHaveBeenCalledWith("gateway-1", {
            name: "Updated Name",
            associatedTools: [],
            associatedResources: [],
            associatedPrompts: [],
          });
        });
        expect(mockNavigate).toHaveBeenCalledWith("/app/gateways");
      } finally {
        mockForm = false;
      }
    });

    it("shows error when updateVirtualServer fails", async () => {
      mockPath = "/app/gateways/create-server?editServerId=gateway-1";
      server.use(
        http.get("*/servers/gateway-1", () => {
          return HttpResponse.json({
            id: "gateway-1",
            name: "Test Edit Server",
            visibility: "team",
            oauthEnabled: false,
          });
        }),
        http.get("*/gateways", () => {
          return HttpResponse.json({ gateways: [] });
        })
      );

      mockUpdateVirtualServer.mockRejectedValueOnce(new Error("Update failed error"));

      mockForm = true;
      try {
        renderWithProviders(<CreateServer />);

        await waitFor(() => {
          expect(screen.getByTestId("mock-create-server-form")).toBeInTheDocument();
        });

        act(() => {
          capturedProps?.onSuccess({ name: "Updated Name" });
        });

        await waitFor(() => {
          expect(mockUpdateVirtualServer).toHaveBeenCalledWith("gateway-1", {
            name: "Updated Name",
            associatedTools: [],
            associatedResources: [],
            associatedPrompts: [],
          });
        });
        // Error should be set on the CreateServerForm props
        // But since we use mockForm, we just verify it didn't navigate
        expect(mockNavigate).not.toHaveBeenCalledWith("/app/gateways");
      } finally {
        mockForm = false;
      }
    });

    it("displays a message when there are no connected MCP servers", async () => {
      mockPath = "/app/gateways/create-server?editServerId=gateway-1";
      server.use(
        http.get("*/servers/gateway-1", () => {
          return HttpResponse.json({
            id: "gateway-1",
            name: "Test Edit Server",
            visibility: "team",
            oauthEnabled: false,
          });
        }),
        http.get("*/gateways", () => {
          return HttpResponse.json({ gateways: [] });
        })
      );

      renderWithProviders(<CreateServer />);

      await waitFor(() => {
        expect(screen.getByRole("heading", { name: "Edit server" })).toBeInTheDocument();
      });

      expect(screen.getByText("MCP server")).toBeInTheDocument();
      expect(await screen.findByText("No MCP servers found.")).toBeInTheDocument();
    });
  });
});
