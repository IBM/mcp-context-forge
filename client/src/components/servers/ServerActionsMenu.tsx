import { MoreVertical } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "../ui/dropdown-menu";
import { Button } from "../ui/button";
import type { MCPServer } from "../../types/server";

interface ServerActionsMenuProps {
  server: MCPServer;
  onEdit: (id: string) => void;
  onDelete: (id: string) => void;
  onTest: (id: string) => void;
  onViewDetails?: (id: string) => void;
  onToggleEnabled?: (id: string, enabled: boolean) => void;
}

export function ServerActionsMenu({
  server,
  onEdit,
  onDelete,
  onTest,
  onViewDetails,
  onToggleEnabled,
}: ServerActionsMenuProps) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="h-8 w-8 p-0"
          aria-label={`Actions for ${server.name}`}
          aria-haspopup="menu"
        >
          <MoreVertical className="h-4 w-4" aria-hidden="true" />
          <span className="sr-only">Open menu for {server.name}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" role="menu">
        {onViewDetails && (
          <DropdownMenuItem onClick={() => onViewDetails(server.id)} role="menuitem">
            View Details
          </DropdownMenuItem>
        )}
        <DropdownMenuItem onClick={() => onEdit(server.id)} role="menuitem">
          Edit
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => onTest(server.id)} role="menuitem">
          Test Connection
        </DropdownMenuItem>
        {onToggleEnabled && (
          <DropdownMenuItem
            onClick={() => onToggleEnabled(server.id, !server.enabled)}
            role="menuitem"
          >
            {server.enabled ? "Deactivate" : "Activate"}
          </DropdownMenuItem>
        )}
        <DropdownMenuItem
          onClick={() => onDelete(server.id)}
          className="text-red-600 dark:text-red-400"
          role="menuitem"
        >
          Delete
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
