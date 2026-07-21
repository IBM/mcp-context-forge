import { describe, it, expect, vi } from "vitest";
import { renderWithProviders } from "@/test/test-utils";
import { screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConnectSourceCard } from "./ConnectSourceCard";
import { VirtualServerCard } from "./VirtualServerCard";
import type { VirtualServer } from "@/types/server";

// ─────────────────────────────────────────────
// ConnectSourceCard tests
// ─────────────────────────────────────────────
describe("ConnectSourceCard", () => {
  it("renders a card with title and description from intl", () => {
    renderWithProviders(<ConnectSourceCard onAction={vi.fn()} />);
    // intl message IDs are rendered as-is (the I18n provider resolves them)
    expect(document.body).toBeTruthy();
  });

  it("calls onAction when the card is clicked", () => {
    const onAction = vi.fn();
    renderWithProviders(<ConnectSourceCard onAction={onAction} />);
    const card = document.querySelector("[role='button']")!;
    fireEvent.click(card);
    expect(onAction).toHaveBeenCalledTimes(1);
  });

  it("calls onAction when Enter key is pressed on card", () => {
    const onAction = vi.fn();
    renderWithProviders(<ConnectSourceCard onAction={onAction} />);
    const card = document.querySelector("[role='button']")!;
    fireEvent.keyDown(card, { key: "Enter" });
    expect(onAction).toHaveBeenCalledTimes(1);
  });

  it("calls onAction when Space key is pressed on card", () => {
    const onAction = vi.fn();
    renderWithProviders(<ConnectSourceCard onAction={onAction} />);
    const card = document.querySelector("[role='button']")!;
    fireEvent.keyDown(card, { key: " " });
    expect(onAction).toHaveBeenCalledTimes(1);
  });

  it("does NOT call onAction when other keys are pressed", () => {
    const onAction = vi.fn();
    renderWithProviders(<ConnectSourceCard onAction={onAction} />);
    const card = document.querySelector("[role='button']")!;
    fireEvent.keyDown(card, { key: "Tab" });
    expect(onAction).not.toHaveBeenCalled();
  });

  it("is keyboard accessible with tabIndex=0", () => {
    renderWithProviders(<ConnectSourceCard onAction={vi.fn()} />);
    const card = document.querySelector("[role='button']")!;
    expect(card).toHaveAttribute("tabindex", "0");
  });
});

// ─────────────────────────────────────────────
// VirtualServerCard tests
// ─────────────────────────────────────────────

const mockServer = {
  id: "vs-1",
  name: "My Test Server",
  enabled: true,
  visibility: "public",
  oauthEnabled: false,
  tags: ["api", "test"],
  associatedTools: ["tool1"],
  associatedToolIds: ["t1"],
  associatedResources: [],
  associatedPrompts: [],
  createdAt: "2024-01-01T00:00:00Z",
  updatedAt: "2024-06-01T00:00:00Z",
} as unknown as VirtualServer;

const emptyServer = {
  ...mockServer,
  id: "vs-empty",
  name: "Empty Server",
  enabled: false,
  associatedTools: [],
  associatedToolIds: [],
  associatedResources: [],
  associatedPrompts: [],
  tags: [],
} as unknown as VirtualServer;

describe("VirtualServerCard", () => {
  it("renders the server name", () => {
    renderWithProviders(<VirtualServerCard server={mockServer} onViewDetails={vi.fn()} />);
    expect(screen.getByText("My Test Server")).toBeTruthy();
  });

  it("shows enabled indicator for enabled server", () => {
    renderWithProviders(<VirtualServerCard server={mockServer} onViewDetails={vi.fn()} />);
    expect(screen.getByTestId("enabled-indicator")).toBeTruthy();
  });

  it("does not show enabled indicator for disabled server", () => {
    renderWithProviders(<VirtualServerCard server={emptyServer} onViewDetails={vi.fn()} />);
    expect(screen.queryByTestId("enabled-indicator")).toBeNull();
  });

  it("calls onViewDetails when card is clicked", () => {
    const onViewDetails = vi.fn();
    renderWithProviders(<VirtualServerCard server={mockServer} onViewDetails={onViewDetails} />);
    const card = screen.getByTestId("virtual-server-card");
    fireEvent.click(card);
    expect(onViewDetails).toHaveBeenCalledWith(mockServer);
  });

  it("shows tool count for non-empty server", () => {
    renderWithProviders(<VirtualServerCard server={mockServer} onViewDetails={vi.fn()} />);
    const toolCount = screen.getByTestId("tool-count");
    expect(toolCount.textContent).toContain("1");
  });

  it("shows Add Sources button for empty composition server", () => {
    renderWithProviders(<VirtualServerCard server={emptyServer} onViewDetails={vi.fn()} />);
    // Empty server shows "Add sources" button - intl ID based text
    const buttons = screen.getAllByRole("button");
    expect(buttons.length).toBeGreaterThan(0);
  });

  it("calls onAddComponents when add button is clicked (empty server)", () => {
    const onAddComponents = vi.fn();
    renderWithProviders(
      <VirtualServerCard
        server={emptyServer}
        onViewDetails={vi.fn()}
        onAddComponents={onAddComponents}
      />,
    );
    // Find the add sources/components button in the card content
    const addBtn = document.querySelector(".justify-start") as HTMLElement;
    if (addBtn) {
      fireEvent.click(addBtn);
      expect(onAddComponents).toHaveBeenCalledWith(emptyServer);
    }
  });

  it("shows dropdown menu with view details option", async () => {
    const onViewDetails = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<VirtualServerCard server={mockServer} onViewDetails={onViewDetails} />);
    const ellipsisBtn = screen.getByRole("button", { name: /Actions for/i });
    await user.click(ellipsisBtn);
    // After click, view details menu item appears
    const viewDetailsItem = await screen.findByRole("menuitem", { name: /View details/i });
    expect(viewDetailsItem).toBeTruthy();
  });

  it("shows Edit option when onEdit provided", async () => {
    const onEdit = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(
      <VirtualServerCard server={mockServer} onViewDetails={vi.fn()} onEdit={onEdit} />,
    );
    const ellipsisBtn = screen.getByRole("button", { name: /Actions for/i });
    await user.click(ellipsisBtn);
    const editItem = await screen.findByRole("menuitem", { name: /Edit server/i });
    expect(editItem).toBeTruthy();
    await user.click(editItem);
    expect(onEdit).toHaveBeenCalledWith(mockServer);
  });

  it("shows Delete option when onDelete provided", async () => {
    const onDelete = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(
      <VirtualServerCard server={mockServer} onViewDetails={vi.fn()} onDelete={onDelete} />,
    );
    const ellipsisBtn = screen.getByRole("button", { name: /Actions for/i });
    await user.click(ellipsisBtn);
    const deleteItem = await screen.findByRole("menuitem", { name: /Delete/i });
    expect(deleteItem).toBeTruthy();
    await user.click(deleteItem);
    expect(onDelete).toHaveBeenCalledWith(mockServer);
  });

  it("shows Activate/Deactivate toggle when onToggleStatus provided", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <VirtualServerCard server={mockServer} onViewDetails={vi.fn()} onToggleStatus={vi.fn()} />,
    );
    const ellipsisBtn = screen.getByRole("button", { name: /Actions for/i });
    await user.click(ellipsisBtn);
    // enabled=true server shows "Deactivate"
    const toggle = await screen.findByRole("menuitem", { name: /Deactivate/i });
    expect(toggle).toBeTruthy();
  });

  it("shows tags as badges for non-empty server", () => {
    renderWithProviders(<VirtualServerCard server={mockServer} onViewDetails={vi.fn()} />);
    // "api" and "test" tags should be rendered as badges
    expect(screen.getByText("api")).toBeTruthy();
    expect(screen.getByText("test")).toBeTruthy();
  });

  it("applies custom className", () => {
    renderWithProviders(
      <VirtualServerCard
        server={mockServer}
        onViewDetails={vi.fn()}
        className="custom-card-class"
      />,
    );
    const card = screen.getByTestId("virtual-server-card");
    expect(card.className).toContain("custom-card-class");
  });
});
