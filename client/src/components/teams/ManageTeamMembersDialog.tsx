import { useCallback } from "react";
import { useIntl } from "react-intl";
import { Plus, Trash2, Users } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../ui/dialog";
import { Button } from "../ui/button";
import { Combobox } from "../ui/combobox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../ui/select";
import { AVAILABLE_ROLES, useTeamMembersForm } from "@/hooks/useTeamMembersForm";

interface ManageTeamMembersDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  teamId: string;
  teamName: string;
  onSuccess?: () => void;
}

export function ManageTeamMembersDialog({
  open,
  onOpenChange,
  teamId,
  teamName,
  onSuccess,
}: ManageTeamMembersDialogProps) {
  const intl = useIntl();
  const {
    members,
    memberOptions,
    isLoading,
    isSaving,
    addRow,
    removeRow,
    changeEmail,
    changeRole,
    save,
  } = useTeamMembersForm({
    open,
    teamId,
    onSuccess,
    onClose: () => onOpenChange(false),
  });

  const handleCancel = useCallback(() => {
    if (!isSaving) {
      onOpenChange(false);
    }
  }, [isSaving, onOpenChange]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded bg-yellow-500">
              <Users className="h-4 w-4 text-black" />
            </div>
            {intl.formatMessage({ id: "teams.members.dialog.title" })}
          </DialogTitle>
          <DialogDescription>
            {intl.formatMessage({ id: "teams.members.dialog.description" }, { teamName })}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {isLoading ? (
            <div
              role="status"
              aria-live="polite"
              aria-busy="true"
              className="flex items-center justify-center py-8"
            >
              <span className="sr-only">
                {intl.formatMessage({ id: "teams.members.loading.sr" })}
              </span>
              <div className="h-8 w-8 animate-spin rounded-full border-4 border-border border-t-primary" />
            </div>
          ) : (
            <>
              <div className="space-y-2">
                {members.length > 0 && (
                  <div className="flex items-center gap-2">
                    <div className="flex-1 text-sm font-medium text-foreground">
                      {intl.formatMessage({ id: "common.name" })}
                    </div>
                    <div className="w-32 text-sm font-medium text-foreground">
                      {intl.formatMessage({ id: "common.role" })}
                    </div>
                    <div className="w-[88px]" aria-hidden="true" />
                  </div>
                )}
                {members.map((member) => (
                  <div key={member.id} className="flex items-center gap-2">
                    <div className="flex-1">
                      <Combobox
                        options={memberOptions}
                        value={member.email}
                        onValueChange={(v) => changeEmail(member.id, v)}
                        placeholder={intl.formatMessage({
                          id: "teams.members.email.placeholder",
                        })}
                        searchPlaceholder={intl.formatMessage({
                          id: "teams.members.email.placeholder",
                        })}
                        emptyText={intl.formatMessage({
                          id: "teams.members.email.placeholder",
                        })}
                        allowCustomValue={false}
                        disabled={member.isExisting || isSaving}
                        className="h-9"
                      />
                    </div>
                    <div className="w-32">
                      <Select
                        value={member.role}
                        onValueChange={(value) => changeRole(member.id, value)}
                        disabled={isSaving}
                      >
                        <SelectTrigger className="h-9 w-full">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {AVAILABLE_ROLES.map((role) => (
                            <SelectItem key={role} value={role}>
                              {role}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-9 w-[88px] gap-1.5 px-2 text-red-600 hover:text-red-700 hover:bg-red-50 dark:hover:bg-red-950"
                      onClick={() => removeRow(member.id)}
                      disabled={isSaving}
                      aria-label={intl.formatMessage(
                        { id: "teams.members.remove.aria" },
                        { email: member.email },
                      )}
                    >
                      <Trash2 className="h-4 w-4" />
                      {intl.formatMessage({ id: "common.button.remove" })}
                    </Button>
                  </div>
                ))}
              </div>

              <Button variant="outline" size="sm" onClick={addRow} disabled={isSaving}>
                <Plus className="h-4 w-4 mr-2" />
                {intl.formatMessage({ id: "teams.members.add" })}
              </Button>
            </>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={handleCancel} disabled={isSaving}>
            {intl.formatMessage({ id: "common.button.cancel" })}
          </Button>
          <Button onClick={save} disabled={isLoading || isSaving}>
            {intl.formatMessage({
              id: isSaving ? "common.button.saving" : "common.button.save",
            })}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
