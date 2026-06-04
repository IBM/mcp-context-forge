import { memo } from "react";
import { CheckCircle2, XCircle, AlertCircle, FileText } from "lucide-react";
import { Badge } from "../ui/badge";
import type { MCPServer, ServerStatus } from "../../types/server";

// Warning threshold: 5 minutes in milliseconds
const WARNING_THRESHOLD_MS = 5 * 60 * 1000;

function getServerStatus(server: MCPServer): ServerStatus {
  if (!server.enabled) return "draft";
  if (!server.reachable) return "offline";

  // Warning: if lastSeen is older than the threshold
  if (server.lastSeen) {
    const lastSeenDate = new Date(server.lastSeen);
    const thresholdDate = new Date(Date.now() - WARNING_THRESHOLD_MS);
    if (lastSeenDate < thresholdDate) return "warning";
  }

  return "active";
}

enum BadgeVariant {
  Draft = "draft",
  Success = "success",
  Destructive = "destructive",
  Warning = "warning",
}

interface StatusConfig {
  label: string;
  icon: typeof FileText;
  variant: BadgeVariant;
}

const STATUS_CONFIG: Record<ServerStatus, StatusConfig> = {
  draft: {
    label: "Draft",
    icon: FileText,
    variant: BadgeVariant.Draft,
  },
  active: {
    label: "Active",
    icon: CheckCircle2,
    variant: BadgeVariant.Success,
  },
  offline: {
    label: "Offline",
    icon: XCircle,
    variant: BadgeVariant.Destructive,
  },
  warning: {
    label: "Warning",
    icon: AlertCircle,
    variant: BadgeVariant.Warning,
  },
};

interface ServerStatusBadgeProps {
  server: MCPServer;
}

export const ServerStatusBadge = memo(function ServerStatusBadge({
  server,
}: ServerStatusBadgeProps) {
  const status = getServerStatus(server);
  const config = STATUS_CONFIG[status];
  const Icon = config.icon;

  return (
    <Badge
      variant={config.variant}
      className="gap-1"
      role="status"
      aria-label={`Server status: ${config.label}`}
    >
      <Icon className="w-3 h-3" aria-hidden="true" />
      <span className="font-medium">{config.label}</span>
      {status === "warning" && <span className="sr-only">Last seen more than 5 minutes ago</span>}
    </Badge>
  );
});

ServerStatusBadge.displayName = "ServerStatusBadge";
