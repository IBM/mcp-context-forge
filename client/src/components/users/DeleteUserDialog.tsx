import { useIntl } from "react-intl";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

interface DeleteUserDialogProps {
  isOpen: boolean;
  userEmail: string;
  userName: string;
  onConfirm: () => void;
  onCancel: () => void;
  isDeleting?: boolean;
}

export function DeleteUserDialog({
  isOpen,
  userEmail,
  userName,
  onConfirm,
  onCancel,
  isDeleting = false,
}: DeleteUserDialogProps) {
  const intl = useIntl();

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onCancel()}>
      <DialogContent role="alertdialog" aria-busy={isDeleting}>
        <DialogHeader>
          <DialogTitle>{intl.formatMessage({ id: "users.delete.dialog.title" })}</DialogTitle>
          <DialogDescription id="delete-user-description">
            {intl.formatMessage(
              { id: "users.delete.dialog.description" },
              { name: userName, email: userEmail },
            )}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel} disabled={isDeleting}>
            {intl.formatMessage({ id: "users.delete.dialog.cancel" })}
          </Button>
          <Button
            variant="destructive"
            onClick={onConfirm}
            disabled={isDeleting}
            aria-describedby="delete-user-description"
            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
          >
            {isDeleting
              ? intl.formatMessage({ id: "users.delete.dialog.deleting" })
              : intl.formatMessage({ id: "users.delete.dialog.confirm" })}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
