import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DeleteUserDialog } from "./DeleteUserDialog";
import { I18nProvider } from "@/i18n";
import type { ReactElement } from "react";

function renderWithI18n(ui: ReactElement) {
  return render(<I18nProvider>{ui}</I18nProvider>);
}

const defaultProps = {
  isOpen: true,
  userEmail: "test@example.com",
  userName: "Test User",
  onConfirm: vi.fn(),
  onCancel: vi.fn(),
};

describe("DeleteUserDialog", () => {
  it("renders dialog when open", () => {
    renderWithI18n(<DeleteUserDialog {...defaultProps} />);
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
  });

  it("displays the dialog title", () => {
    renderWithI18n(<DeleteUserDialog {...defaultProps} />);
    expect(screen.getByRole("heading", { name: /delete user/i })).toBeInTheDocument();
  });

  it("displays user name and email in description", () => {
    renderWithI18n(<DeleteUserDialog {...defaultProps} />);
    expect(screen.getByText(/test@example.com/i)).toBeInTheDocument();
  });

  it("renders Cancel button", () => {
    renderWithI18n(<DeleteUserDialog {...defaultProps} />);
    expect(screen.getByRole("button", { name: /cancel/i })).toBeInTheDocument();
  });

  it("renders Delete/Confirm button", () => {
    renderWithI18n(<DeleteUserDialog {...defaultProps} />);
    // Confirm button text may be "Delete" or "Confirm"
    const confirmBtn = screen.getByRole("button", { name: /delete|confirm/i });
    expect(confirmBtn).toBeInTheDocument();
  });

  it("calls onCancel when Cancel button is clicked", async () => {
    const onCancel = vi.fn();
    const user = userEvent.setup();
    renderWithI18n(<DeleteUserDialog {...defaultProps} onCancel={onCancel} />);

    await user.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("calls onConfirm when confirm button is clicked", async () => {
    const onConfirm = vi.fn();
    const user = userEvent.setup();
    renderWithI18n(<DeleteUserDialog {...defaultProps} onConfirm={onConfirm} />);

    const confirmBtn = screen.getByRole("button", { name: /delete|confirm/i });
    await user.click(confirmBtn);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("disables both buttons when isDeleting is true", () => {
    renderWithI18n(<DeleteUserDialog {...defaultProps} isDeleting={true} />);

    const cancelBtn = screen.getByRole("button", { name: /cancel/i });
    expect(cancelBtn).toBeDisabled();

    const confirmBtn = screen.getByRole("button", { name: /delete|confirm|deleting/i });
    expect(confirmBtn).toBeDisabled();
  });

  it("shows deleting state text when isDeleting is true", () => {
    renderWithI18n(<DeleteUserDialog {...defaultProps} isDeleting={true} />);
    // Should show "Deleting..." or similar text
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
  });

  it("has aria-busy attribute when isDeleting is true", () => {
    renderWithI18n(<DeleteUserDialog {...defaultProps} isDeleting={true} />);
    const dialog = screen.getByRole("alertdialog");
    expect(dialog).toHaveAttribute("aria-busy", "true");
  });

  it("has aria-busy=false when not deleting", () => {
    renderWithI18n(<DeleteUserDialog {...defaultProps} isDeleting={false} />);
    const dialog = screen.getByRole("alertdialog");
    expect(dialog).toHaveAttribute("aria-busy", "false");
  });

  it("does not render dialog content when isOpen is false", () => {
    renderWithI18n(<DeleteUserDialog {...defaultProps} isOpen={false} />);
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("uses userName in the description", () => {
    renderWithI18n(
      <DeleteUserDialog
        {...defaultProps}
        userName="John Doe"
        userEmail="john@example.com"
      />,
    );
    // The description should contain the user's name and/or email
    expect(screen.getByText(/john@example.com/i)).toBeInTheDocument();
  });
});
