import { useCallback } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../ui/dialog";
import { Button } from "../ui/button";
import { Loading } from "../ui/loading";

interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: "default" | "destructive";
  onConfirm: () => void | Promise<void>;
  isLoading?: boolean;
  loadingLabel?: string;
  closeOnConfirm?: boolean;
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  variant = "default",
  onConfirm,
  isLoading = false,
  loadingLabel,
  closeOnConfirm = true,
}: ConfirmDialogProps) {
  const handleOpenChange = useCallback(
    (nextOpen: boolean) => {
      if (isLoading && !nextOpen) return;
      onOpenChange(nextOpen);
    },
    [isLoading, onOpenChange],
  );

  const handleCancel = useCallback(() => {
    if (isLoading) return;
    onOpenChange(false);
  }, [isLoading, onOpenChange]);

  const handleConfirm = useCallback(() => {
    void onConfirm();
    if (closeOnConfirm && !isLoading) {
      onOpenChange(false);
    }
  }, [closeOnConfirm, isLoading, onConfirm, onOpenChange]);

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={handleCancel} disabled={isLoading}>
            {cancelLabel}
          </Button>
          <Button
            variant={variant}
            onClick={handleConfirm}
            disabled={isLoading}
            aria-busy={isLoading}
          >
            {isLoading && <Loading variant="inline" />}
            {isLoading ? (loadingLabel ?? confirmLabel) : confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
