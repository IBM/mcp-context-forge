import { describe, it, expect, vi } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/test-utils";
import { VirtualServerCard } from "./VirtualServerCard";
import { ConnectSourceCard } from "./ConnectSourceCard";
import type { VirtualServer } from "@/types/server";

const makeServer = (overrides: Partial<VirtualServer> = {}) => ({
  id: "vs-1",
  name: "My Server",
  enabled: true,
  visibility: "team",
  oauthEnabled: false,
  tags: [],
  associatedTools: [],
  associatedResources: [],
  associatedPrompts: [],
  createdAt: "2024-01-01T00:00:00Z",
  updatedAt: "2024-06-01T00:00:00Z",
  ...overrides,
} as unknown as VirtualServer);

// ─── ConnectSourceCard ────────────────────────────────────────────────────────
describe("ConnectSourceCard", () => {
  it("renders create server card", () => {
    renderWithProviders(<ConnectSourceCard onAction={vi.fn()} />);
    // Check that some text from the card renders
    expect(document.querySelector("[role='button']")).toBeTruthy();
  });

  it("calls onAction when clicked", () => {
    const onAction = vi.fn();
    renderWithProviders(<ConnectSourceCard onAction={onAction} />);
    const card = document.querySelector("[role='button']") as HTMLElement;
    fireEvent.click(card);
    expect(onAction).toHaveBeenCalledTimes(1);
  });

  it("calls onAction when Enter key is pressed", () => {
    const onAction = vi.fn();
    renderWithProviders(<ConnectSourceCard onAction={onAction} />);
    const card = document.querySelector("[role='button']") as HTMLElement;
    fireEvent.keyDown(card, { key: "Enter" });
    expect(onAction).toHaveBeenCalledTimes(1);
  });

  it("calls onAction when Space key is pressed", () => {
    const onAction = vi.fn();
    renderWithProviders(<ConnectSourceCard onAction={onAction} />);
    const card = document.querySelector("[role='button']") as HTMLElement;
    fireEvent.keyDown(card, { key: " " });
    expect(onAction).toHaveBeenCalledTimes(1);
  });

  it("does not call onAction on other keys", () => {
    const onAction = vi.fn();
    renderWithProviders(<ConnectSourceCard onAction={onAction} />);
    const card = document.querySelector("[role='button']") as HTMLElement;
    fireEvent.keyDown(card, { key: "Escape" });
    expect(onAction).not.toHaveBeenCalled();
  });
});

// ─── VirtualServerCard ────────────────────────────────────────────────────────
describe("VirtualServerCard", () => {
  it("renders server name", () => {
    renderWithProviders(<VirtualServerCard server={makeServer()} onViewDetails={vi.fn()} />);
    expect(screen.getByText("My Server")).toBeTruthy();
  });

  it("calls onViewDetails when card is clicked", () => {
    const onViewDetails = vi.fn();
    renderWithProviders(<VirtualServerCard server={makeServer()} onViewDetails={onViewDetails} />);
    fireEvent.click(screen.getByTestId("virtual-server-card"));
    expect(onViewDetails).toHaveBeenCalledWith(expect.objectContaining({ id: "vs-1" }));
  });

  it("shows enabled indicator for enabled server", () => {
    renderWithProviders(
      <VirtualServerCard server={makeServer({ enabled: true })} onViewDetails={vi.fn()} />,
    );
    expect(screen.getByTestId("enabled-indicator")).toBeTruthy();
  });

  it("does not show enabled indicator for disabled server", () => {
    renderWithProviders(
      <VirtualServerCard server={makeServer({ enabled: false })} onViewDetails={vi.fn()} />,
    );
    expect(screen.queryByTestId("enabled-indicator")).toBeNull();
  });

  it("renders empty state with add components button when no tools/resources/prompts", () => {
    renderWithProviders(
      <VirtualServerCard
        server={makeServer({ associatedTools: [], associatedResources: [], associatedPrompts: [] })}
        onViewDetails={vi.fn()}
      />,
    );
    // Empty composition shows "Add sources" type button
    expect(screen.queryByTestId("tool-count")).toBeNull();
  });

  it("renders tool/resource/prompt counts when components exist", () => {
    renderWithProviders(
      <VirtualServerCard
        server={makeServer({
          associatedTools: ["t1", "t2"],
          associatedResources: ["r1"],
          associatedPrompts: [],
        })}
        onViewDetails={vi.fn()}
      />,
    );
    expect(screen.getByTestId("tool-count")).toBeTruthy();
    expect(screen.getByTestId("resource-count")).toBeTruthy();
    expect(screen.getByTestId("prompt-count")).toBeTruthy();
  });

  it("renders tags as badges when components exist", () => {
    renderWithProviders(
      <VirtualServerCard
        server={makeServer({ associatedTools: ["t1"], tags: ["api", "v2"] })}
        onViewDetails={vi.fn()}
      />,
    );
    expect(screen.getByText("api")).toBeTruthy();
    expect(screen.getByText("v2")).toBeTruthy();
  });

  it("renders last-updated timestamp when components exist", () => {
    renderWithProviders(
      <VirtualServerCard
        server={makeServer({ associatedTools: ["t1"] })}
        onViewDetails={vi.fn()}
      />,
    );
    expect(screen.getByTestId("last-updated")).toBeTruthy();
  });

  it("shows actions menu button", () => {
    renderWithProviders(<VirtualServerCard server={makeServer()} onViewDetails={vi.fn()} />);
    expect(screen.getByRole("button", { name: /Actions for/i })).toBeTruthy();
  });

  it("shows add-components button when server is empty and onAddComponents is provided", () => {
    const onAddComponents = vi.fn();
    renderWithProviders(
      <VirtualServerCard
        server={makeServer()}
        onViewDetails={vi.fn()}
        onAddComponents={onAddComponents}
      />,
    );
    // In empty state the "add components" button should be visible
    const btn = document.querySelector("button[type='button']");
    expect(btn).toBeTruthy();
  });

  it("shows Deactivate when server is enabled and onToggleStatus is provided", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <VirtualServerCard
        server={makeServer({ enabled: true })}
        onViewDetails={vi.fn()}
        onToggleStatus={vi.fn()}
      />,
    );
    // open dropdown
    const trigger = screen.getByRole("button", { name: /Actions for/i });
    await user.click(trigger);
    expect(screen.getByText("Deactivate")).toBeTruthy();
  });

  it("shows Activate when server is disabled and onToggleStatus is provided", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <VirtualServerCard
        server={makeServer({ enabled: false })}
        onViewDetails={vi.fn()}
        onToggleStatus={vi.fn()}
      />,
    );
    const trigger = screen.getByRole("button", { name: /Actions for/i });
    await user.click(trigger);
    expect(screen.getByText("Activate")).toBeTruthy();
  });

  it("calls onEdit from dropdown when provided", async () => {
    const user = userEvent.setup();
    const onEdit = vi.fn();
    renderWithProviders(
      <VirtualServerCard server={makeServer()} onViewDetails={vi.fn()} onEdit={onEdit} />,
    );
    const trigger = screen.getByRole("button", { name: /Actions for/i });
    await user.click(trigger);
    const editBtn = screen.getByText(/Edit/i);
    await user.click(editBtn);
    expect(onEdit).toHaveBeenCalledWith(expect.objectContaining({ id: "vs-1" }));
  });

  it("calls onDelete from dropdown when provided", async () => {
    const user = userEvent.setup();
    const onDelete = vi.fn();
    renderWithProviders(
      <VirtualServerCard server={makeServer()} onViewDetails={vi.fn()} onDelete={onDelete} />,
    );
    const trigger = screen.getByRole("button", { name: /Actions for/i });
    await user.click(trigger);
    const deleteBtn = screen.getByText(/Delete/i);
    await user.click(deleteBtn);
    expect(onDelete).toHaveBeenCalledWith(expect.objectContaining({ id: "vs-1" }));
  });

  it("does not render Edit or Delete menu items when callbacks not provided", async () => {
    const user = userEvent.setup();
    renderWithProviders(<VirtualServerCard server={makeServer()} onViewDetails={vi.fn()} />);
    const trigger = screen.getByRole("button", { name: /Actions for/i });
    await user.click(trigger);
    expect(screen.queryByText(/^Edit/)).toBeNull();
    expect(screen.queryByText(/^Delete/)).toBeNull();
  });

  it("applies custom className", () => {
    renderWithProviders(
      <VirtualServerCard server={makeServer()} onViewDetails={vi.fn()} className="custom-class" />,
    );
    expect(document.querySelector(".custom-class")).toBeTruthy();
  });

  it("shows upload button for non-empty server", () => {
    renderWithProviders(
      <VirtualServerCard
        server={makeServer({ associatedTools: ["t1"] })}
        onViewDetails={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: /Open.*coming soon/i })).toBeTruthy();
  });
});
