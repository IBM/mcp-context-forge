import { useState, useRef, useEffect } from "react";
import {
  Copy,
  Globe,
  Lock,
  Shield,
  TriangleAlert,
  Check,
  Activity,
  CircleSlash,
  CircleDashed,
} from "lucide-react";
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
import { ServerActionsMenu } from "./ServerActionsMenu";
import type { MCPServer, ServerStatus } from "../../types/server";
import { Loading } from "../ui/loading";

function formatLastSeen(lastSeen?: string): string {
  if (!lastSeen) return "Never used";

  const date = new Date(lastSeen);
  if (Number.isNaN(date.getTime())) return "Never used";

  return date
    .toLocaleString("sv-SE", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    })
    .replace(" ", "T");
}

function getLastSeenValue(server: MCPServer): string | undefined {
  return server.lastSeen;
}

function getToolCount(server: MCPServer): number {
  return server.toolCount ?? 0;
}

function getResourceCount(server: MCPServer): number {
  return server.resourceCount ?? 0;
}

function getPromptCount(server: MCPServer): number {
  return server.promptCount ?? 0;
}

function getServerStatus(server: MCPServer): ServerStatus {
  if (!server.enabled) return "draft";
  if (!server.reachable) {
    // Had a successful connection before → regression worth flagging
    return server.lastSeen ? "warning" : "offline";
  }

  return "active";
}

function getVisibilityConfig(visibility: MCPServer["visibility"]) {
  switch (visibility) {
    case "private":
      return { label: "Private", Icon: Lock };
    case "team":
      return { label: "Team", Icon: Shield };
    default:
      return { label: "Public", Icon: Globe };
  }
}

function getStatusConfig(status: ServerStatus) {
  switch (status) {
    case "active":
      return {
        label: "Active",
        Icon: Activity,
        className: "text-emerald-400",
      };
    case "warning":
      return {
        label: "Warning",
        Icon: TriangleAlert,
        className: "text-amber-400",
      };
    case "offline":
      return {
        label: "Offline",
        Icon: CircleSlash,
        className: "text-neutral-500",
      };
    default:
      return {
        label: "Draft",
        Icon: CircleDashed,
        className: "text-neutral-500",
      };
  }
}

const COPY_FEEDBACK_DURATION_MS = 1500;

interface ServersTableProps {
  servers: MCPServer[];
  isLoading: boolean;
  onEdit: (id: string) => void;
  onDelete: (id: string) => void;
  onTest: (id: string) => void;
  onViewDetails?: (id: string) => void;
}

export function ServersTable({ servers, isLoading, onEdit, onDelete, onTest, onViewDetails }: ServersTableProps) {
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const timeoutRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        window.clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  const handleCopy = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setCopiedId(value);

      if (timeoutRef.current) {
        window.clearTimeout(timeoutRef.current);
      }

      timeoutRef.current = window.setTimeout(() => {
        setCopiedId((current) => (current === value ? null : current));
        timeoutRef.current = null;
      }, COPY_FEEDBACK_DURATION_MS);
    } catch (error) {
      console.error("Failed to copy server id:", error);
    }
  };

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
    <div className="overflow-hidden bg-white dark:bg-neutral-950/60">
      <Table className="min-w-full border-separate border-spacing-y-1.5">
        <TableCaption className="sr-only">List of MCP servers with status and actions</TableCaption>
        <TableHeader className="bg-white dark:bg-transparent">
          <TableRow className="border-none hover:bg-transparent">
            <TableHead className="h-12 px-4 text-xs font-medium text-neutral-600 dark:text-neutral-400">
              Name
            </TableHead>
            <TableHead className="h-12 px-4 text-xs font-medium text-neutral-600 dark:text-neutral-400">
              Components
            </TableHead>
            <TableHead className="h-12 px-4 text-xs font-medium text-neutral-600 dark:text-neutral-400">
              Last response
            </TableHead>
            <TableHead className="h-12 px-4 text-xs font-medium text-neutral-600 dark:text-neutral-400">
              UUID
            </TableHead>
            <TableHead className="h-12 px-4 text-xs font-medium text-neutral-600 dark:text-neutral-400">
              Visibility
            </TableHead>
            <TableHead className="h-12 px-4 text-xs font-medium text-neutral-600 dark:text-neutral-400">
              Status
            </TableHead>
            <TableHead className="h-12 px-4 text-xs font-medium text-neutral-600 dark:text-neutral-400 text-right">
              Actions
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {servers.map((server) => {
            const resourcesCount = getResourceCount(server);
            const promptsCount = getPromptCount(server);
            const toolCount = getToolCount(server);
            const lastSeen = getLastSeenValue(server);
            const status = getServerStatus(server);
            const visibility = getVisibilityConfig(server.visibility);
            const statusConfig = getStatusConfig(status);
            const VisibilityIcon = visibility.Icon;
            const StatusIcon = statusConfig.Icon;

            return (
              <TableRow
                key={server.id}
                className="bg-neutral-50 dark:bg-neutral-800 hover:bg-neutral-100 dark:hover:bg-neutral-700/60 [&>td:first-child]:rounded-l-lg [&>td:last-child]:rounded-r-lg"
              >
                <TableCell className="px-4 py-2.5">
                  <div className="flex items-center gap-3">
                    <ServerIcon name={server.name} size="md" />
                    <span className="font-medium text-neutral-900 dark:text-neutral-100">
                      {server.name}
                    </span>
                  </div>
                </TableCell>
                <TableCell className="px-4 py-2.5">
                  <div className="flex flex-wrap items-center gap-2 text-xs text-neutral-600 dark:text-neutral-400">
                    <span>{toolCount} tools</span>
                    <span>•</span>
                    <span>{resourcesCount} resources</span>
                    <span>•</span>
                    <span>{promptsCount} prompts</span>
                  </div>
                </TableCell>
                <TableCell className="px-4 py-2.5 text-xs text-neutral-600 dark:text-neutral-400">
                  {formatLastSeen(lastSeen)}
                </TableCell>
                <TableCell className="px-4 py-2.5">
                  <button
                    type="button"
                    onClick={() => handleCopy(server.id)}
                    className="inline-flex items-center gap-2 text-xs text-neutral-600 dark:text-neutral-400 transition hover:text-neutral-900 dark:hover:text-neutral-200"
                    aria-label={`Copy UUID for ${server.name}`}
                  >
                    <span className="max-w-[180px] truncate">{server.id}</span>
                    {copiedId === server.id ? (
                      <>
                        <Check className="h-3.5 w-3.5 text-emerald-400" aria-hidden="true" />
                        <span className="sr-only">Copied!</span>
                      </>
                    ) : (
                      <Copy className="h-3.5 w-3.5" aria-hidden="true" />
                    )}
                  </button>
                </TableCell>
                <TableCell className="px-4 py-2.5">
                  <div className="inline-flex items-center gap-1.5 text-xs text-neutral-600 dark:text-neutral-400">
                    <VisibilityIcon className="h-3.5 w-3.5" aria-hidden="true" focusable="false" />
                    <span>{visibility.label}</span>
                  </div>
                </TableCell>
                <TableCell className="px-4 py-2.5">
                  <div
                    className={`inline-flex items-center gap-1.5 text-xs ${statusConfig.className}`}
                  >
                    <StatusIcon className="h-3.5 w-3.5" />
                    <span className="text-neutral-600 dark:text-neutral-400">
                      {statusConfig.label}
                    </span>
                  </div>
                </TableCell>
                <TableCell className="px-4 py-2.5 text-right">
                  <ServerActionsMenu
                    server={server}
                    onEdit={onEdit}
                    onDelete={onDelete}
                    onTest={onTest}
                    onViewDetails={onViewDetails}
                  />
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
