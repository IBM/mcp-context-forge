import { describe, it, expect, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { render } from "@testing-library/react";
import { ServerActionsMenu } from "./ServerActionsMenu";
import type { MCPServer } from "@/types/server";

const mockServer: MCPServer = {
  id: "test-server-123",
  name: "Test Server",
  url: "http://test.example.com",
  transport: "SSE",
  enabled: true,
  reachable: true,
  visibility: "public",
  toolCount: 5,
  createdAt: "2024-01-01T00:00:00Z",
  updatedAt: "2024-01-01T00:00:00Z",
};

describe("ServerActionsMenu", () => {
  it("renders actions menu button", () => {
    render(
      <ServerActionsMenu
        server={mockServer}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        onTest={vi.fn()}
      />,
    );

    const menuButton = screen.getByRole("button", { name: /actions for test server/i });
    expect(menuButton).toBeInTheDocument();
  });

  it("displays all menu items when opened", async () => {
    const user = userEvent.setup();

    render(
      <ServerActionsMenu
        server={mockServer}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        onTest={vi.fn()}
        onViewDetails={vi.fn()}
      />,
    );

    const menuButton = screen.getByRole("button", { name: /actions for test server/i });
    await user.click(menuButton);

    await waitFor(() => {
      expect(screen.getByRole("menuitem", { name: /view details/i })).toBeInTheDocument();
    });

    expect(screen.getByRole("menuitem", { name: /edit/i })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /test connection/i })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /delete/i })).toBeInTheDocument();
  });

  it("calls onViewDetails when View Details is clicked", async () => {
    const user = userEvent.setup();
    const onViewDetails = vi.fn();

    render(
      <ServerActionsMenu
        server={mockServer}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        onTest={vi.fn()}
        onViewDetails={onViewDetails}
      />,
    );

    const menuButton = screen.getByRole("button", { name: /actions for test server/i });
    await user.click(menuButton);

    const viewDetailsItem = await screen.findByRole("menuitem", { name: /view details/i });
    await user.click(viewDetailsItem);

    expect(onViewDetails).toHaveBeenCalledWith(mockServer.id);
    expect(onViewDetails).toHaveBeenCalledTimes(1);
  });

  it("does not display View Details when onViewDetails is not provided", async () => {
    const user = userEvent.setup();

    render(
      <ServerActionsMenu
        server={mockServer}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        onTest={vi.fn()}
      />,
    );

    const menuButton = screen.getByRole("button", { name: /actions for test server/i });
    await user.click(menuButton);

    await waitFor(() => {
      expect(screen.getByRole("menuitem", { name: /edit/i })).toBeInTheDocument();
    });

    // View Details should not be present when onViewDetails is undefined
    expect(screen.queryByRole("menuitem", { name: /view details/i })).not.toBeInTheDocument();
  });

  it("calls onEdit when Edit is clicked", async () => {
    const user = userEvent.setup();
    const onEdit = vi.fn();

    render(
      <ServerActionsMenu server={mockServer} onEdit={onEdit} onDelete={vi.fn()} onTest={vi.fn()} />,
    );

    const menuButton = screen.getByRole("button", { name: /actions for test server/i });
    await user.click(menuButton);

    const editItem = await screen.findByRole("menuitem", { name: /edit/i });
    await user.click(editItem);

    expect(onEdit).toHaveBeenCalledWith(mockServer.id);
    expect(onEdit).toHaveBeenCalledTimes(1);
  });

  it("calls onTest when Test Connection is clicked", async () => {
    const user = userEvent.setup();
    const onTest = vi.fn();

    render(
      <ServerActionsMenu server={mockServer} onEdit={vi.fn()} onDelete={vi.fn()} onTest={onTest} />,
    );

    const menuButton = screen.getByRole("button", { name: /actions for test server/i });
    await user.click(menuButton);

    const testItem = await screen.findByRole("menuitem", { name: /test connection/i });
    await user.click(testItem);

    expect(onTest).toHaveBeenCalledWith(mockServer.id);
    expect(onTest).toHaveBeenCalledTimes(1);
  });

  it("calls onDelete when Delete is clicked", async () => {
    const user = userEvent.setup();
    const onDelete = vi.fn();

    render(
      <ServerActionsMenu
        server={mockServer}
        onEdit={vi.fn()}
        onDelete={onDelete}
        onTest={vi.fn()}
      />,
    );

    const menuButton = screen.getByRole("button", { name: /actions for test server/i });
    await user.click(menuButton);

    const deleteItem = await screen.findByRole("menuitem", { name: /delete/i });
    await user.click(deleteItem);

    expect(onDelete).toHaveBeenCalledWith(mockServer.id);
    expect(onDelete).toHaveBeenCalledTimes(1);
  });

  it("displays View Details as first menu item", async () => {
    const user = userEvent.setup();

    render(
      <ServerActionsMenu
        server={mockServer}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        onTest={vi.fn()}
        onViewDetails={vi.fn()}
      />,
    );

    const menuButton = screen.getByRole("button", { name: /actions for test server/i });
    await user.click(menuButton);

    await waitFor(() => {
      const menuItems = screen.getAllByRole("menuitem");
      expect(menuItems[0]).toHaveTextContent(/view details/i);
    });
  });

  describe("Toggle Enabled functionality", () => {
    it("displays Deactivate option when server is enabled and onToggleEnabled is provided", async () => {
      const user = userEvent.setup();
      const onToggleEnabled = vi.fn();

      render(
        <ServerActionsMenu
          server={mockServer}
          onEdit={vi.fn()}
          onDelete={vi.fn()}
          onTest={vi.fn()}
          onToggleEnabled={onToggleEnabled}
        />,
      );

      const menuButton = screen.getByRole("button", { name: /actions for test server/i });
      await user.click(menuButton);

      const deactivateItem = await screen.findByRole("menuitem", { name: /deactivate/i });
      expect(deactivateItem).toBeInTheDocument();
    });

    it("displays Activate option when server is disabled and onToggleEnabled is provided", async () => {
      const user = userEvent.setup();
      const onToggleEnabled = vi.fn();
      const disabledServer = { ...mockServer, enabled: false };

      render(
        <ServerActionsMenu
          server={disabledServer}
          onEdit={vi.fn()}
          onDelete={vi.fn()}
          onTest={vi.fn()}
          onToggleEnabled={onToggleEnabled}
        />,
      );

      const menuButton = screen.getByRole("button", { name: /actions for test server/i });
      await user.click(menuButton);

      const activateItem = await screen.findByRole("menuitem", { name: /activate/i });
      expect(activateItem).toBeInTheDocument();
    });

    it("calls onToggleEnabled with false when Deactivate is clicked", async () => {
      const user = userEvent.setup();
      const onToggleEnabled = vi.fn();

      render(
        <ServerActionsMenu
          server={mockServer}
          onEdit={vi.fn()}
          onDelete={vi.fn()}
          onTest={vi.fn()}
          onToggleEnabled={onToggleEnabled}
        />,
      );

      const menuButton = screen.getByRole("button", { name: /actions for test server/i });
      await user.click(menuButton);

      const deactivateItem = await screen.findByRole("menuitem", { name: /deactivate/i });
      await user.click(deactivateItem);

      expect(onToggleEnabled).toHaveBeenCalledWith(mockServer.id, false);
      expect(onToggleEnabled).toHaveBeenCalledTimes(1);
    });

    it("calls onToggleEnabled with true when Activate is clicked", async () => {
      const user = userEvent.setup();
      const onToggleEnabled = vi.fn();
      const disabledServer = { ...mockServer, enabled: false };

      render(
        <ServerActionsMenu
          server={disabledServer}
          onEdit={vi.fn()}
          onDelete={vi.fn()}
          onTest={vi.fn()}
          onToggleEnabled={onToggleEnabled}
        />,
      );

      const menuButton = screen.getByRole("button", { name: /actions for test server/i });
      await user.click(menuButton);

      const activateItem = await screen.findByRole("menuitem", { name: /activate/i });
      await user.click(activateItem);

      expect(onToggleEnabled).toHaveBeenCalledWith(mockServer.id, true);
      expect(onToggleEnabled).toHaveBeenCalledTimes(1);
    });

    it("does not display toggle options when onToggleEnabled is not provided", async () => {
      const user = userEvent.setup();

      render(
        <ServerActionsMenu
          server={mockServer}
          onEdit={vi.fn()}
          onDelete={vi.fn()}
          onTest={vi.fn()}
        />,
      );

      const menuButton = screen.getByRole("button", { name: /actions for test server/i });
      await user.click(menuButton);

      await waitFor(() => {
        expect(screen.getByRole("menuitem", { name: /edit/i })).toBeInTheDocument();
      });

      expect(screen.queryByRole("menuitem", { name: /activate/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("menuitem", { name: /deactivate/i })).not.toBeInTheDocument();
    });
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ServerActionsMenu } from "./ServerActionsMenu";
import type { MCPServer } from "../../types/server";

describe("ServerActionsMenu", () => {
  const mockServer: MCPServer = {
    id: "test-server-1",
    name: "Test Server",
    command: "test-command",
    args: [],
    env: {},
    tags: [],
    status: "connected",
    auth: { type: "none" },
  };

  const mockOnEdit = vi.fn();
  const mockOnDelete = vi.fn();
  const mockOnTest = vi.fn();

  it("should render the actions menu trigger", () => {
    render(
      <ServerActionsMenu
        server={mockServer}
        onEdit={mockOnEdit}
        onDelete={mockOnDelete}
        onTest={mockOnTest}
      />,
    );
    expect(
      screen.getByRole("button", { name: `Actions for ${mockServer.name}` }),
    ).toBeInTheDocument();
  });

  it("should open menu and call actions correctly", async () => {
    const user = userEvent.setup();
    render(
      <ServerActionsMenu
        server={mockServer}
        onEdit={mockOnEdit}
        onDelete={mockOnDelete}
        onTest={mockOnTest}
      />,
    );

    // Open the menu
    const trigger = screen.getByRole("button", { name: `Actions for ${mockServer.name}` });
    await user.click(trigger);

    // Click Edit
    const editItem = await screen.findByText("Edit");
    await user.click(editItem);
    expect(mockOnEdit).toHaveBeenCalledWith("test-server-1");

    // Click Test Connection
    await user.click(trigger); // reopen menu
    const testItem = await screen.findByText("Test Connection");
    await user.click(testItem);
    expect(mockOnTest).toHaveBeenCalledWith("test-server-1");

    // Click Delete
    await user.click(trigger); // reopen menu
    const deleteItem = await screen.findByText("Delete");
    await user.click(deleteItem);
    expect(mockOnDelete).toHaveBeenCalledWith("test-server-1");
  });
});

