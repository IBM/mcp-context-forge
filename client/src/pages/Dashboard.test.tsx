import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useQuery } from "@/hooks/useQuery";
import { renderWithProviders } from "@/test/test-utils";
import { Dashboard } from "./Dashboard";

const mockNavigate = vi.fn();

vi.mock("@/router", () => ({
  useRouter: () => ({
    navigate: mockNavigate,
    path: "/app/",
    params: {},
  }),
}));

vi.mock("@/hooks/useQuery", () => ({
  useQuery: vi.fn(),
}));

const mockUseQuery = vi.mocked(useQuery);

describe("Dashboard", () => {
  beforeEach(() => {
    mockNavigate.mockClear();
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

    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
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

    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Connect a source" })).not.toBeInTheDocument();
  });

  it("opens the MCP server form from source selection", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Dashboard />);

    await user.click(screen.getAllByRole("button", { name: "+ Connect" })[0]!);

    expect(mockNavigate).toHaveBeenCalledWith("/app/servers?openForm=true");
  });
});
