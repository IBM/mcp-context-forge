import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../ui/table";
import { ServerIcon } from "./ServerIcon";
import { ServerStatusBadge } from "./ServerStatusBadge";
import { ServerActionsMenu } from "./ServerActionsMenu";
import type { MCPServer } from "../../types/server";
import { Loading } from "../ui/loading";

function formatLastResponse(lastSeen?: string): string {
  if (!lastSeen) return "Never used";

  const date = new Date(lastSeen);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);

  if (diffMins < 1) return "Just now";
  if (diffMins < 60) return `${diffMins} min ago`;

  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours} hour${diffHours > 1 ? "s" : ""} ago`;

  return date.toLocaleDateString("en-US", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

interface ServersTableProps {
  servers: MCPServer[];
  isLoading: boolean;
  onEdit: (id: string) => void;
  onDelete: (id: string) => void;
  onTest: (id: string) => void;
}

export function ServersTable({ servers, isLoading, onEdit, onDelete, onTest }: ServersTableProps) {
  if (isLoading) {
    return (
      <div
        className="flex items-center justify-center py-12"
        role="status"
        aria-live="polite"
        aria-busy="true"
      >
        <Loading />
        <span className="sr-only">Loading servers, please wait...</span>
      </div>
    );
  }

  return (
    <Table>
      <TableCaption className="sr-only">List of MCP servers with status and actions</TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead>Name</TableHead>
          <TableHead>Components</TableHead>
          <TableHead>Last response</TableHead>
          <TableHead>Status</TableHead>
          <TableHead className="w-[50px]">Actions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {servers.map((server) => (
          <TableRow key={server.id} className="hover:bg-gray-50 dark:hover:bg-gray-800">
            <TableCell>
              <div className="flex items-center gap-3">
                <ServerIcon name={server.name} />
                <span className="font-medium text-gray-900 dark:text-gray-100">{server.name}</span>
              </div>
            </TableCell>
            <TableCell className="text-gray-600 dark:text-gray-400">
              {server.tool_count} tools
            </TableCell>
            <TableCell className="text-gray-600 dark:text-gray-400">
              {formatLastResponse(server.last_seen)}
            </TableCell>
            <TableCell>
              <ServerStatusBadge server={server} />
            </TableCell>
            <TableCell>
              <ServerActionsMenu
                server={server}
                onEdit={onEdit}
                onDelete={onDelete}
                onTest={onTest}
              />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
