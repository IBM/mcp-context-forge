import { useIntl } from "react-intl";
import {
  Box,
  Edit,
  EllipsisVertical,
  Eye,
  MessageSquareCode,
  Plus,
  Power,
  Trash2,
  Upload,
  Wrench,
} from "lucide-react";
import { MCPIcon } from "@/components/icons/MCPIcon";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { VirtualServer } from "@/types/server";
import {
  formatServerTimestamp,
  getTagDisplay,
  getVirtualServerComponentCounts,
} from "@/components/gateways/utils";
import { cn } from "@/lib/utils";

export function VirtualServerCard({
  server,
  onViewDetails,
  onAddComponents,
  onEdit,
  onDelete,
  onToggleStatus,
  className,
}: {
  server: VirtualServer;
  onViewDetails: (server: VirtualServer) => void;
  onAddComponents?: (server: VirtualServer) => void;
  onEdit?: (server: VirtualServer) => void;
  onDelete?: (server: VirtualServer) => void;
  onToggleStatus?: (server: VirtualServer) => void;
  className?: string;
}) {
  const intl = useIntl();
  const { toolCount, resourceCount, promptCount, total } = getVirtualServerComponentCounts(server);
  const tags = (server.tags ?? []).map((tag, index) => getTagDisplay(tag, index));
  const isEmptyComposition = total === 0;

  return (
    <Card
      size="sm"
      className={cn(
        isEmptyComposition ? "min-h-29 justify-center" : "min-h-35 justify-between",
        "cursor-pointer transition-colors hover:bg-accent/50",
        className,
      )}
      data-testid="virtual-server-card"
      data-server-name={server.name}
      onClick={() => onViewDetails(server)}
    >
      <CardHeader className="gap-3">
        <div className="flex items-center gap-3">
          <span className="flex size-6 shrink-0 items-center justify-center rounded-sm bg-primary text-primary-foreground">
            <MCPIcon className="size-4 [&_path]:fill-current" />
          </span>
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <CardTitle className="truncate">{server.name}</CardTitle>
            {server.enabled && (
              <span
                className="size-1.5 rounded-full bg-emerald-500"
                data-testid="enabled-indicator"
                aria-label="Enabled"
              />
            )}
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {!isEmptyComposition && (
              <Button
                variant="ghost"
                size="icon-xs"
                aria-label={`Open ${server.name} (coming soon)`}
                disabled
              >
                <Upload className="size-4" />
              </Button>
            )}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  aria-label={`Actions for ${server.name}`}
                  onClick={(e) => e.stopPropagation()}
                >
                  <EllipsisVertical className="size-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem
                  onClick={(e) => {
                    e.stopPropagation();
                    onViewDetails(server);
                  }}
                >
                  <Eye className="mr-2 size-4" />
                  {intl.formatMessage({ id: "gateways.card.viewDetails" })}
                </DropdownMenuItem>
                <DropdownMenuItem disabled>
                  <Power className="mr-2 size-4" />
                  {intl.formatMessage({ id: "gateways.card.testConnection" })}
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={(e) => {
                    e.stopPropagation();
                    onEdit?.(server);
                  }}
                  disabled={!onEdit}
                >
                  <Edit className="mr-2 size-4" />
                  {intl.formatMessage({ id: "gateways.card.editServer" })}
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={(e) => {
                    e.stopPropagation();
                    onToggleStatus?.(server);
                  }}
                  disabled={!onToggleStatus}
                >
                  <Power className="mr-2 size-4" />
                  {server.enabled ? "Deactivate" : "Activate"}
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onClick={(e) => {
                    e.stopPropagation();
                    onDelete?.(server);
                  }}
                  disabled={!onDelete}
                  className="text-destructive focus:text-destructive"
                >
                  <Trash2 className="mr-2 size-4" />
                  {intl.formatMessage({ id: "common.button.delete" })}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </CardHeader>
      {isEmptyComposition ? (
        <CardContent>
          <Button
            type="button"
            variant="secondary"
            className="h-10 w-full justify-start rounded-sm px-3 text-left text-[13px] text-muted-foreground"
            onClick={() => onAddComponents?.(server)}
          >
            <Plus className="size-4" />
            {intl.formatMessage({ id: "gateways.card.addSourcesAndComponents" })}
          </Button>
        </CardContent>
      ) : (
        <CardContent className="space-y-3">
          <div className="flex items-center gap-3 text-[13px] font-medium text-secondary-foreground">
            <span className="flex items-center gap-2" data-testid="tool-count">
              <Wrench className="size-4 text-muted-foreground" />
              {toolCount}
            </span>
            <span className="text-border">•</span>
            <span className="flex items-center gap-2" data-testid="resource-count">
              <Box className="size-4 text-muted-foreground" />
              {resourceCount}
            </span>
            <span className="text-border">•</span>
            <span className="flex items-center gap-2" data-testid="prompt-count">
              <MessageSquareCode className="size-4 text-muted-foreground" />
              {promptCount}
            </span>
          </div>
          <div className="flex items-center gap-2 overflow-hidden">
            <div className="flex min-w-0 flex-1 items-center gap-2 overflow-hidden">
              {tags.map((tag) => (
                <Badge
                  key={tag.key}
                  variant="outline"
                  className="shrink-0 px-1.5 py-0 text-[10px] font-medium text-muted-foreground"
                >
                  {tag.label}
                </Badge>
              ))}
            </div>
            <span
              className="shrink-0 truncate text-[13px] text-muted-foreground"
              data-testid="last-updated"
            >
              {formatServerTimestamp(
                server.updatedAt || server.createdAt,
                intl.formatMessage({ id: "gateways.card.notSyncedYet" }),
              )}
            </span>
          </div>
        </CardContent>
      )}
    </Card>
  );
}
