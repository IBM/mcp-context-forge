import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useQuery } from "@/hooks/useQuery";
import { renderWithProviders } from "@/test/test-utils";
import { Dashboard } from "./Dashboard";

const mockNavigate = vi.fn();
let mockPath = "/app/";

vi.mock("@/router", () => ({
  useRouter: () => ({ navigate: mockNavigate, path: mockPath, params: {} }),
}));

const mockHasPermission = vi.fn((_perm: string) => true);
let mockPermissionsLoading = false;
vi.mock("@/auth/useAuth", () => ({
  useAuth: () => ({ hasPermission: mockHasPermission, permissionsLoading: mockPermissionsLoading }),
}));

// Trivial stubs so exercising the system/mcp views doesn't pull in their heavy
// data-fetching children (which are covered by their own tests).
vi.mock("@/components/dashboard/SystemView", () => ({ SystemView: () => <div>system view</div> }));
vi.mock("@/components/dashboard/McpHealthCard", () => ({
  McpHealthCard: () => <div>mcp health card</div>,
}));

vi.mock("@/hooks/useQuery", () => ({
  useQuery: vi.fn(),
}));

// These tests cover onboarding + home-state rendering, not the mini-card
// statuses. Stub the status hook so they don't need auth/health/reachability
// wiring; systemHealth is threaded down to (the stubbed) McpHealthCard.
vi.mock("@/hooks/useMiniCardStatuses", () => ({
  useMiniCardStatuses: () => {
    const offline = { kind: "dot", tone: "muted", labelId: "dashboard.home.status.offline" };
    return {
      statuses: {
        system: offline,
        activity: { kind: "activity", errors: 0, warnings: 0 },
        mcp: offline,
        a2a: offline,
        rest: offline,
        grpc: offline,
      },
      headlineCondition: {},
      systemHealth: {
        data: undefined,
        error: null,
        isLoading: false,
        execute: vi.fn(),
        refetch: vi.fn(),
        setData: vi.fn(),
      },
    };
  },
}));

const mockUseQuery = vi.mocked(useQuery);

describe("Dashboard", () => {
  beforeEach(() => {
    mockNavigate.mockClear();
    mockPath = "/app/";
    mockPermissionsLoading = false;
    mockHasPermission.mockReturnValue(true);
    mockUseQuery.mockReturnValue({
      data: { servers: [], gateways: [] },
      error: null,
      isLoading: false,
      execute: vi.fn(),
      refetch: vi.fn(),
      setData: vi.fn(),
    });
  });

  it("checks whether virtual and MCP servers exist", () => {
    renderWithProviders(<Dashboard />);

    expect(mockUseQuery).toHaveBeenCalledWith("/servers?limit=1&include_pagination=true");
    expect(mockUseQuery).toHaveBeenCalledWith(
      "/gateways?limit=1&include_inactive=true&include_pagination=true",
    );
  });

  it("uses the shared loader while dashboard sources are loading", () => {
    mockUseQuery.mockReturnValue({
      data: undefined,
      error: null,
      isLoading: true,
      execute: vi.fn(),
      refetch: vi.fn(),
      setData: vi.fn(),
    });

    renderWithProviders(<Dashboard />);

    expect(screen.getByRole("status", { name: "Loading..." })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Connect a source" })).not.toBeInTheDocument();
  });

  it("shows an error without showing onboarding when the request fails", () => {
    mockUseQuery.mockReturnValue({
      data: undefined,
      error: { message: "Unable to load virtual servers" },
      isLoading: false,
      execute: vi.fn(),
      refetch: vi.fn(),
      setData: vi.fn(),
    });

    renderWithProviders(<Dashboard />);

    expect(screen.getByRole("alert")).toHaveTextContent("Error loading dashboard sources");
    expect(screen.getByRole("alert")).toHaveTextContent("Unable to load virtual servers");
    expect(screen.queryByRole("heading", { name: "Connect a source" })).not.toBeInTheDocument();
  });

  it("shows source selection when no virtual or MCP server exists", () => {
    renderWithProviders(<Dashboard />);

    expect(screen.getByRole("heading", { name: "Connect a source" })).toBeInTheDocument();
    expect(screen.getByText("MCP server")).toBeInTheDocument();
    expect(screen.getByText("AI agent")).toBeInTheDocument();
    expect(screen.getByText("REST API")).toBeInTheDocument();
    expect(screen.getByText("gRPC")).toBeInTheDocument();
  });

  it("hides onboarding when a virtual server exists", () => {
    mockUseQuery.mockReturnValue({
      data: { servers: [{ id: "server-1" }], gateways: [] },
      error: null,
      isLoading: false,
      execute: vi.fn(),
      refetch: vi.fn(),
      setData: vi.fn(),
    });

    renderWithProviders(<Dashboard />);

    expect(screen.getByRole("heading", { name: "Up and running..." })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Connect a source" })).not.toBeInTheDocument();
  });

  it("hides source selection when an MCP server exists without a virtual server", () => {
    mockUseQuery.mockReturnValue({
      data: { servers: [], gateways: [{ id: "mcp-server-1" }] },
      error: null,
      isLoading: false,
      execute: vi.fn(),
      refetch: vi.fn(),
      setData: vi.fn(),
    });

    renderWithProviders(<Dashboard />);

    expect(screen.getByRole("heading", { name: "Up and running..." })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Connect a source" })).not.toBeInTheDocument();
  });

  it("opens the MCP server form from source selection", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Dashboard />);

    const mcpCard = screen.getByTestId("action-card-MCP server");
    await user.click(within(mcpCard).getByRole("button", { name: /connect/i }));

    expect(mockNavigate).toHaveBeenCalledWith("/app/servers?openForm=true");
  });
});

describe("Dashboard home views (non-default states)", () => {
  beforeEach(() => {
    mockNavigate.mockClear();
    mockPath = "/app/";
    mockPermissionsLoading = false;
    mockHasPermission.mockReturnValue(true);
    // Past onboarding: at least one MCP server exists.
    mockUseQuery.mockReturnValue({
      data: { servers: [], gateways: [{ id: "g1" }] },
      error: null,
      isLoading: false,
      execute: vi.fn(),
      refetch: vi.fn(),
      setData: vi.fn(),
    });
  });

  it("renders the source-specific placeholder for an ungated view", () => {
    mockPath = "/app/?view=a2a";
    renderWithProviders(<Dashboard />);
    expect(screen.getByText("No agent (A2A) sources have been added yet.")).toBeInTheDocument();
  });

  it("renders the System view when the caller is permitted", () => {
    mockPath = "/app/?view=system";
    renderWithProviders(<Dashboard />);
    expect(screen.getByText("system view")).toBeInTheDocument();
  });

  it("renders the MCP health card on the mcp view", () => {
    mockPath = "/app/?view=mcp";
    renderWithProviders(<Dashboard />);
    expect(screen.getByText("mcp health card")).toBeInTheDocument();
  });

  it("shows PermissionDenied for a gated view without permission", () => {
    mockPath = "/app/?view=system";
    mockHasPermission.mockReturnValue(false);
    renderWithProviders(<Dashboard />);
    expect(screen.getByText("You do not have permission to view this.")).toBeInTheDocument();
    expect(screen.queryByText("system view")).not.toBeInTheDocument();
  });

  it("shows a loading skeleton for a gated view while permissions load", () => {
    mockPath = "/app/?view=system";
    mockHasPermission.mockReturnValue(false);
    mockPermissionsLoading = true;
    const { container } = renderWithProviders(<Dashboard />);
    expect(container.querySelector('[data-slot="skeleton"]')).toBeInTheDocument();
    expect(screen.queryByText("You do not have permission to view this.")).not.toBeInTheDocument();
  });
});
