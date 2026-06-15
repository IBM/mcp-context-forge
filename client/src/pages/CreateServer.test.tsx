import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { screen, waitFor, fireEvent, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { renderWithProviders } from "@/test/test-utils";
import { createVirtualServer } from "@/api/virtualServers";
import { ApiError } from "@/api/client";
import { CreateServer } from "./CreateServer";

let mockForm = false;
let capturedProps: any = null;
let mockSourceSelection = false;
let capturedSourceSelectionProps: any = null;

vi.mock("@/components/gateways/CreateServerForm", async (importOriginal) => {
  const actual = (await importOriginal()) as any;
  return {
    ...actual,
    CreateServerForm: (props: any) => {
      if (mockForm) {
        capturedProps = props;
        return <div data-testid="mock-create-server-form" />;
      }
      return actual.CreateServerForm(props);
    },
  };
});

vi.mock("@/components/gateways/SourceSelection", async (importOriginal) => {
  const actual = (await importOriginal()) as any;
  return {
    ...actual,
    SourceSelection: (props: any) => {
      if (mockSourceSelection) {
        capturedSourceSelectionProps = props;
        return <div data-testid="mock-source-selection" />;
      }
      return actual.SourceSelection(props);
    },
  };
});

const mockNavigate = vi.fn();

vi.mock("@/router", () => ({
  useRouter: () => ({
    navigate: mockNavigate,
    path: "/app/gateways/create-server",
    params: {},
  }),
}));

vi.mock("@/api/virtualServers", () => ({
  createVirtualServer: vi.fn(),
}));

const mockCreateVirtualServer = vi.mocked(createVirtualServer);

describe("CreateServer", () => {
  beforeEach(() => {
    mockNavigate.mockClear();
    mockCreateVirtualServer.mockReset();
    mockCreateVirtualServer.mockResolvedValue({
      id: "server-1",
      name: "Research server",
    } as Awaited<ReturnType<typeof createVirtualServer>>);
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
    const apiError = new ApiError(
      { url: "", ok: false, status: 400, statusText: "Bad Request" },
      { message: "Api message error" },
    );
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
    const apiError = new ApiError(
      { url: "", ok: false, status: 400, statusText: "Bad Request" },
      { detail: "Api detail string error" },
    );
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
    const apiError = new ApiError(
      { url: "", ok: false, status: 400, statusText: "Bad Request" },
      { detail: [{ msg: "Msg 1" }, "String msg 2"] },
    );
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
        capturedProps.onSuccess(null);
      });

      // Now step should be sources, and SourceSelection should render
      expect(screen.getByTestId("mock-source-selection")).toBeInTheDocument();

      // Step 2: Trigger onSkip from SourceSelection
      await act(async () => {
        capturedSourceSelectionProps.createServerActions.onSkip();
      });

      // Step should set back to details, rendering CreateServerForm again
      expect(screen.getByTestId("mock-create-server-form")).toBeInTheDocument();
    } finally {
      mockForm = false;
      mockSourceSelection = false;
    }
  });
});
