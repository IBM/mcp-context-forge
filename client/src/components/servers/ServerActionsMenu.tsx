import { MoreVertical, Edit, Trash2, TestTube } from "lucide-react";
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
}

export function ServerActionsMenu({ server, onEdit, onDelete, onTest }: ServerActionsMenuProps) {
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
        <DropdownMenuItem onClick={() => onEdit(server.id)} role="menuitem">
          <Edit className="mr-2 h-4 w-4" aria-hidden="true" />
          Edit
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => onTest(server.id)} role="menuitem">
          <TestTube className="mr-2 h-4 w-4" aria-hidden="true" />
          Test Connection
        </DropdownMenuItem>
        <DropdownMenuItem
          onClick={() => onDelete(server.id)}
          className="text-red-600 dark:text-red-400"
          role="menuitem"
        >
          <Trash2 className="mr-2 h-4 w-4" aria-hidden="true" />
          Delete
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
