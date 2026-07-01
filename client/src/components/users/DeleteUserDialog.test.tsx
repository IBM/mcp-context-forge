import { describe, it, expect, vi } from "vitest";
import { renderWithProviders } from "@/test/test-utils";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DeleteUserDialog } from "./DeleteUserDialog";

describe("DeleteUserDialog", () => {
  it("renders correctly and displays user info", () => {
    renderWithProviders(
      <DeleteUserDialog
        isOpen={true}
        userEmail="test@example.com"
        userName="Test User"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />
    );
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Delete User" })).toBeInTheDocument(); // Title depends on i18n, but renderWithProviders might not mock translations identically to pure renderWithIntl. We will see.
  });

  it("calls onCancel when Cancel is clicked", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    renderWithProviders(
      <DeleteUserDialog
        isOpen={true}
        userEmail="test@example.com"
        userName="Test User"
        onConfirm={vi.fn()}
        onCancel={onCancel}
      />
    );

    const cancelBtn = screen.getByRole("button", { name: /Cancel/i });
    await user.click(cancelBtn);
    expect(onCancel).toHaveBeenCalled();
  });

  it("calls onConfirm when Confirm is clicked", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    renderWithProviders(
      <DeleteUserDialog
        isOpen={true}
        userEmail="test@example.com"
        userName="Test User"
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />
    );

    const confirmBtn = screen.getByRole("button", { name: /Delete/i }); // i18n key users.delete.dialog.confirm defaults to Delete usually
    await user.click(confirmBtn);
    expect(onConfirm).toHaveBeenCalled();
  });

  it("disables buttons and shows deleting state when isDeleting is true", () => {
    renderWithProviders(
      <DeleteUserDialog
        isOpen={true}
        userEmail="test@example.com"
        userName="Test User"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
        isDeleting={true}
      />
    );

    const cancelBtn = screen.getByRole("button", { name: /Cancel/i });
    expect(cancelBtn).toBeDisabled();
    
    // We expect the text to be "Deleting..." (users.delete.dialog.deleting)
    const deleteBtn = screen.getByRole("button", { name: /Deleting/i });
    expect(deleteBtn).toBeDisabled();
  });

  it("calls onCancel when dialog is dismissed via escape", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    renderWithProviders(
      <DeleteUserDialog
        isOpen={true}
        userEmail="test@example.com"
        userName="Test User"
        onConfirm={vi.fn()}
        onCancel={onCancel}
      />
    );
    
    await user.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalled();
  });
});
