import { Box, EllipsisVertical, MessageSquareCode, Upload, Wrench } from "lucide-react";
import { MCPIcon } from "@/components/icons/MCPIcon";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { VirtualServer } from "@/types/server";
import { formatServerTimestamp, getTagDisplay } from "@/components/gateways/utils";

export function VirtualServerCard({
  server,
  onViewDetails,
}: {
  server: VirtualServer;
  onViewDetails: (server: VirtualServer) => void;
}) {
  const toolCount = server.associatedToolIds?.length ?? 0;
  const resourceCount = server.associatedResources?.length ?? 0;
  const promptCount = server.associatedPrompts?.length ?? 0;
  const tags = (server.tags ?? []).map(getTagDisplay);

  return (
    <Card
      size="sm"
      className="min-h-35 justify-between"
      data-testid="virtual-server-card"
      data-server-name={server.name}
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
            <Button
              variant="ghost"
              size="icon-xs"
              aria-label={`Open ${server.name} (coming soon)`}
              disabled
            >
              <Upload className="size-4" />
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon-xs" aria-label={`Actions for ${server.name}`}>
                  <EllipsisVertical className="size-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => onViewDetails(server)}>
                  View details
                </DropdownMenuItem>
                <DropdownMenuItem disabled>Test connection</DropdownMenuItem>
                <DropdownMenuItem disabled>Edit server</DropdownMenuItem>
                <DropdownMenuItem disabled className="text-destructive">
                  Delete
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </CardHeader>
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
            {formatServerTimestamp(server.updatedAt || server.createdAt)}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}
