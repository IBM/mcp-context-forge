import { Edit, MoreVertical, Trash2 } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "../ui/dropdown-menu";
import { useIntl } from "react-intl";
import type { User } from "../../types/user";
import { Button } from "@/components/ui/button";

interface UserActionsMenuProps {
  user: User;
  displayName: string;
  onEdit: (user: User) => void;
  onDelete: (email: string) => void;
}

export function UserActionsMenu({ user, displayName, onEdit, onDelete }: UserActionsMenuProps) {
  const intl = useIntl();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="inline-flex h-5 w-5 items-center justify-center rounded-sm transition-colors hover:text-card-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label={intl.formatMessage(
            { id: "users.table.actions.label" },
            { name: displayName },
          )}
          aria-haspopup="menu"
        >
          <MoreVertical className="h-5 w-5" strokeWidth={1.25} aria-hidden="true" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" role="menu">
        <DropdownMenuItem onClick={() => onEdit(user)} role="menuitem">
          <Edit className="mr-2 h-4 w-4" aria-hidden="true" />
          {intl.formatMessage({ id: "users.table.actions.edit" })}
        </DropdownMenuItem>
        <DropdownMenuItem
          onClick={() => onDelete(user.email)}
          className="text-red-600 dark:text-red-400"
          role="menuitem"
        >
          <Trash2 className="mr-2 h-4 w-4" aria-hidden="true" />
          {intl.formatMessage({ id: "users.table.actions.delete" })}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
