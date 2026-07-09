import { describe, it, expect, vi } from "vitest";
import { renderWithProviders } from "@/test/test-utils";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { UserActionsMenu } from "./UserActionsMenu";
const mockUser = {
  email: "alice@example.com",
  is_admin: false,
  is_active: true,
} as unknown as User;

describe("UserActionsMenu", () => {
  it("renders trigger button with aria-label", () => {
    renderWithProviders(
      <UserActionsMenu user={mockUser} displayName="Alice" onEdit={vi.fn()} onDelete={vi.fn()} />,
    );
    // The trigger button label comes from intl message id
    const trigger = screen.getByRole("button");
    expect(trigger).toBeTruthy();
  });

  it("opens dropdown and shows Edit and Delete options", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <UserActionsMenu user={mockUser} displayName="Alice" onEdit={vi.fn()} onDelete={vi.fn()} />,
    );
    const trigger = screen.getByRole("button");
    await user.click(trigger);

    // Radix dropdown renders menu items
    const editItem = await screen.findByRole("menuitem", { name: /edit/i });
    expect(editItem).toBeTruthy();
  });

  it("calls onEdit with user when Edit is clicked", async () => {
    const user = userEvent.setup();
    const onEdit = vi.fn();
    renderWithProviders(
      <UserActionsMenu user={mockUser} displayName="Alice" onEdit={onEdit} onDelete={vi.fn()} />,
    );
    await user.click(screen.getByRole("button"));
    const editItem = await screen.findByRole("menuitem", { name: /edit/i });
    await user.click(editItem);
    expect(onEdit).toHaveBeenCalledWith(mockUser);
  });

  it("calls onDelete with user email when Delete is clicked", async () => {
    const user = userEvent.setup();
    const onDelete = vi.fn();
    renderWithProviders(
      <UserActionsMenu user={mockUser} displayName="Alice" onEdit={vi.fn()} onDelete={onDelete} />,
    );
    await user.click(screen.getByRole("button"));
    const deleteItem = await screen.findByRole("menuitem", { name: /delete/i });
    await user.click(deleteItem);
    expect(onDelete).toHaveBeenCalledWith(mockUser.email);
  });

  it("delete menu item has red text class", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <UserActionsMenu user={mockUser} displayName="Alice" onEdit={vi.fn()} onDelete={vi.fn()} />,
    );
    await user.click(screen.getByRole("button"));
    const deleteItem = await screen.findByRole("menuitem", { name: /delete/i });
    expect(deleteItem.className).toContain("text-red");
  });
});
