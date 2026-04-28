import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/test-utils";
import { Gateways } from "./Gateways";

// Mock the router
const mockNavigate = vi.fn();
vi.mock("@/router", () => ({
  useRouter: () => ({
    navigate: mockNavigate,
    path: "/app/gateways",
    params: {},
  }),
}));

describe("Gateways", () => {
  beforeEach(() => {
    mockNavigate.mockClear();
  });

  it("renders the page title and all four action cards", () => {
    renderWithProviders(<Gateways />);
    expect(screen.getByText("Connect a source")).toBeInTheDocument();
    expect(screen.getByText("MCP server")).toBeInTheDocument();
    expect(screen.getByText("AI agent")).toBeInTheDocument();
    expect(screen.getByText("REST API")).toBeInTheDocument();
    expect(screen.getByText("gRPC")).toBeInTheDocument();
    expect(
      screen.getByText("Register an endpoint implementing the Model Context Protocol"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Add an agent over A2A, OpenAI, or Anthropic protocols"),
    ).toBeInTheDocument();
    expect(screen.getByText("Wrap a HTTP endpoint as a MCP tool")).toBeInTheDocument();
    expect(screen.getByText("Translate a gRPC endpoint as a MCP tool.")).toBeInTheDocument();
  });

  it("renders MCP server connect button that opens modal", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Gateways />);

    // The MCP server card should have a Connect button
    const buttons = screen.getAllByRole("button", { name: /\+ Connect/i });
    expect(buttons.length).toBeGreaterThanOrEqual(4);

    // Click the first button (MCP server)
    await user.click(buttons[0]!);

    // Wait for the modal to appear and check for dialog
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();

    // Check for the modal content - look for the description text which is unique
    expect(await screen.findByText("Create a new MCP server connection.")).toBeInTheDocument();
  });

  it("navigates to agents page when AI agent card button is clicked", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Gateways />);

    const buttons = screen.getAllByRole("button", { name: /\+ Connect/i });
    // The AI agent button should be the second one (index 1)
    await user.click(buttons[1]!);

    expect(mockNavigate).toHaveBeenCalledWith("/app/agents");
  });

  it("logs message when REST API card button is clicked (not yet implemented)", async () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const user = userEvent.setup();
    renderWithProviders(<Gateways />);

    const buttons = screen.getAllByRole("button", { name: /\+ Connect/i });
    // The REST API button should be the third one (index 2)
    await user.click(buttons[2]!);

    expect(consoleSpy).toHaveBeenCalledWith("REST API gateway creation not yet implemented");
    consoleSpy.mockRestore();
  });

  it("logs message when gRPC card button is clicked (not yet implemented)", async () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const user = userEvent.setup();
    renderWithProviders(<Gateways />);

    const buttons = screen.getAllByRole("button", { name: /\+ Connect/i });
    // The gRPC button should be the fourth one (index 3)
    await user.click(buttons[3]!);

    expect(consoleSpy).toHaveBeenCalledWith("gRPC gateway creation not yet implemented");
    consoleSpy.mockRestore();
  });
});
