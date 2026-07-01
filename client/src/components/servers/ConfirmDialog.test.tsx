import { describe, it, expect, vi } from "vitest";
import { renderWithProviders } from "@/test/test-utils";
import { screen, fireEvent } from "@testing-library/react";
import { ConfirmDialog } from "./ConfirmDialog";

// Mock useIntl in Loading (used inside ConfirmDialog via Loading)
vi.mock("react-intl", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-intl")>();
  return {
    ...actual,
    useIntl: () => ({
      formatMessage: ({ id }: { id: string }) => id,
    }),
  };
});

const defaultProps = {
  open: true,
  onOpenChange: vi.fn(),
  title: "Delete Server",
  description: "Are you sure you want to delete this server?",
  onConfirm: vi.fn(),
};

describe("ConfirmDialog", () => {
  it("renders the dialog when open is true", () => {
    renderWithProviders(<ConfirmDialog {...defaultProps} />);
    expect(screen.getByText("Delete Server")).toBeTruthy();
    expect(screen.getByText("Are you sure you want to delete this server?")).toBeTruthy();
  });

  it("renders default confirm and cancel labels", () => {
    renderWithProviders(<ConfirmDialog {...defaultProps} />);
    expect(screen.getByText("Confirm")).toBeTruthy();
    expect(screen.getByText("Cancel")).toBeTruthy();
  });

  it("renders custom confirm label", () => {
    renderWithProviders(<ConfirmDialog {...defaultProps} confirmLabel="Yes, delete" />);
    expect(screen.getByText("Yes, delete")).toBeTruthy();
  });

  it("renders custom cancel label", () => {
    renderWithProviders(<ConfirmDialog {...defaultProps} cancelLabel="Go back" />);
    expect(screen.getByText("Go back")).toBeTruthy();
  });

  it("calls onConfirm when Confirm button is clicked", () => {
    const onConfirm = vi.fn();
    const onOpenChange = vi.fn();
    renderWithProviders(
      <ConfirmDialog {...defaultProps} onConfirm={onConfirm} onOpenChange={onOpenChange} />
    );
    fireEvent.click(screen.getByText("Confirm"));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("calls onOpenChange(false) when Confirm clicked with closeOnConfirm=true (default)", () => {
    const onOpenChange = vi.fn();
    renderWithProviders(
      <ConfirmDialog {...defaultProps} onOpenChange={onOpenChange} closeOnConfirm={true} />
    );
    fireEvent.click(screen.getByText("Confirm"));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("does NOT call onOpenChange when Confirm clicked with closeOnConfirm=false", () => {
    const onOpenChange = vi.fn();
    renderWithProviders(
      <ConfirmDialog {...defaultProps} onOpenChange={onOpenChange} closeOnConfirm={false} />
    );
    fireEvent.click(screen.getByText("Confirm"));
    expect(onOpenChange).not.toHaveBeenCalled();
  });

  it("calls onOpenChange(false) when Cancel is clicked", () => {
    const onOpenChange = vi.fn();
    renderWithProviders(
      <ConfirmDialog {...defaultProps} onOpenChange={onOpenChange} />
    );
    fireEvent.click(screen.getByText("Cancel"));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("does not call onOpenChange when Cancel is clicked during loading", () => {
    const onOpenChange = vi.fn();
    renderWithProviders(
      <ConfirmDialog {...defaultProps} onOpenChange={onOpenChange} isLoading={true} />
    );
    fireEvent.click(screen.getByText("Cancel"));
    expect(onOpenChange).not.toHaveBeenCalled();
  });

  it("shows loading indicator when isLoading is true", () => {
    renderWithProviders(
      <ConfirmDialog {...defaultProps} isLoading={true} confirmLabel="Delete" />
    );
    // role="status" from Loading component
    expect(screen.getByRole("status")).toBeTruthy();
  });

  it("shows loadingLabel when isLoading and loadingLabel provided", () => {
    renderWithProviders(
      <ConfirmDialog
        {...defaultProps}
        isLoading={true}
        confirmLabel="Confirm"
        loadingLabel="Deleting..."
      />
    );
    expect(screen.getByText("Deleting...")).toBeTruthy();
  });

  it("disables both buttons when isLoading is true", () => {
    renderWithProviders(
      <ConfirmDialog {...defaultProps} isLoading={true} />
    );
    const buttons = screen.getAllByRole("button");
    // Filter to Cancel and Confirm buttons (dialog may have close button too)
    const cancelBtn = buttons.find((b) => b.textContent?.includes("Cancel"));
    const confirmBtn = buttons.find((b) => b.hasAttribute("aria-busy"));
    expect(cancelBtn).toBeDisabled();
    expect(confirmBtn).toBeDisabled();
  });

  it("renders with destructive variant", () => {
    renderWithProviders(
      <ConfirmDialog {...defaultProps} variant="destructive" />
    );
    // Dialog still renders; variant mainly affects button styling
    expect(screen.getByText("Confirm")).toBeTruthy();
  });

  it("does not render dialog content when open is false", () => {
    renderWithProviders(
      <ConfirmDialog {...defaultProps} open={false} />
    );
    expect(screen.queryByText("Delete Server")).toBeNull();
  });
});
