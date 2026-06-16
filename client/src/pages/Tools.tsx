import { useMemo, useState, useCallback } from "react";
import { Plus, MoreHorizontal, Wrench } from "lucide-react";
import { toast } from "sonner";
import { useQuery } from "@/hooks/useQuery";
import { toolsApi } from "@/api/tools";
import { ApiError } from "@/api/client";
import { extractApiErrorDetail } from "@/utils/errors";
import type { Tool, ToolGroup } from "@/types/tool";
import { Card, CardHeader, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ToolDetailsPanel } from "@/components/tools/ToolDetailsPanel";
import { ToolForm } from "@/components/tools/ToolForm";
import { ConfirmDialog } from "@/components/servers/ConfirmDialog";

function buildGroups(tools: Tool[]): ToolGroup[] {
  const map = new Map<string, ToolGroup>();
  for (const tool of tools) {
    const slug = tool.gatewaySlug || "REST tools";
    if (!map.has(slug)) {
      map.set(slug, { gatewaySlug: slug, gatewayId: tool.gatewayId, tools: [], isActive: false });
    }
    const group = map.get(slug)!;
    group.tools.push(tool);
    if (tool.enabled && tool.reachable) group.isActive = true;
  }
  return Array.from(map.values());
}

function ToolGroupCard({
  group,
  onViewGroup,
}: {
  group: ToolGroup;
  onViewGroup: (group: ToolGroup) => void;
}) {
  const MAX_VISIBLE_TOOLS = 8;
  const visibleTools = group.tools.slice(0, MAX_VISIBLE_TOOLS);
  const remainingCount = group.tools.length - MAX_VISIBLE_TOOLS;

  const handleView = () => {
    onViewGroup(group);
  };

  return (
    <Card size="sm">
      <CardHeader>
        <div className="flex items-center gap-3">
          <div className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded bg-tool-icon-bg">
            <Wrench className="h-3.5 w-3.5 text-black" />
          </div>

          <div className="flex min-w-0 flex-1 items-center gap-2">
            <span className="truncate text-sm font-semibold text-neutral-500 dark:text-neutral-400">
              {group.gatewaySlug}
            </span>
            <span className="whitespace-nowrap text-sm font-semibold text-neutral-900 dark:text-white">
              {group.tools.length} {group.tools.length === 1 ? "tool" : "tools"}
            </span>
            <span
              className={`h-1.5 w-1.5 flex-shrink-0 rounded-full ${group.isActive ? "bg-tool-status-active" : "bg-tool-status-inactive"}`}
            />
          </div>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-label={`More options for ${group.gatewaySlug}`}
                className="h-7 w-7 p-0"
              >
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={handleView}>View Details</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </CardHeader>

      <CardContent>
        <div className="flex flex-wrap gap-1">
          {visibleTools.map((tool) => (
            <span
              key={tool.id}
              className="inline-flex items-center rounded bg-tool-badge-bg px-1.5 py-1 text-[10px] font-medium leading-none text-white"
              title={tool.description}
            >
              {tool.name}
            </span>
          ))}
          {remainingCount > 0 && (
            <span
              className="inline-flex items-center rounded bg-tool-badge-bg px-1.5 py-1 text-[10px] font-medium leading-none text-white"
              title={`${remainingCount} more ${remainingCount === 1 ? "tool" : "tools"}`}
            >
              +{remainingCount}
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function AddToolsCard({ onAddTool }: { onAddTool: () => void }) {
  return (
    <Card
      size="sm"
      role="button"
      tabIndex={0}
      className="cursor-pointer transition-opacity hover:opacity-90"
      onClick={onAddTool}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onAddTool();
        }
      }}
    >
      <CardHeader>
        <div className="flex items-center gap-3">
          <div className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded bg-tool-add-icon-bg shadow-sm">
            <Plus className="h-3.5 w-3.5 text-tool-add-icon-fg" />
          </div>
          <span className="text-sm font-semibold text-neutral-900 dark:text-white">Add tools</span>
        </div>
      </CardHeader>
      <CardContent>
        <p className="text-sm leading-relaxed text-neutral-500 dark:text-neutral-400">
          Tools will appear automatically when you connect a MCP server. Or, register a REST
          endpoint as a standalone tool.
        </p>
      </CardContent>
    </Card>
  );
}

export function Tools() {
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [selectedGroup, setSelectedGroup] = useState<ToolGroup | null>(null);
  const [isDetailsPanelOpen, setIsDetailsPanelOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [selectedToolId, setSelectedToolId] = useState<string | null>(null);
  const [selectedToolName, setSelectedToolName] = useState<string | null>(null);

  const { data: toolsData, error, isLoading, refetch } = useQuery<Tool[]>("/tools?limit=0");

  const groups = useMemo(() => buildGroups(toolsData ?? []), [toolsData]);

  const handleFormSuccess = () => {
    setIsFormOpen(false);
    refetch();
  };

  const handleViewGroup = (group: ToolGroup) => {
    setSelectedGroup(group);
    setIsDetailsPanelOpen(true);
  };

  const handleCloseDetails = () => {
    setIsDetailsPanelOpen(false);
  };

  const handleDelete = useCallback(
    (id: string) => {
      const tool = toolsData?.find((t) => t.id === id);
      setSelectedToolId(id);
      setSelectedToolName(tool?.displayName || tool?.name || id);
      setDeleteDialogOpen(true);
    },
    [toolsData],
  );

  const confirmDelete = useCallback(async () => {
    if (!selectedToolId || !selectedToolName) return;

    setDeleteDialogOpen(false);

    try {
      await toolsApi.delete(selectedToolId);
      toast.success(`Tool "${selectedToolName}" deleted successfully`);
      setSelectedToolId(null);
      setSelectedToolName(null);
      setIsDetailsPanelOpen(false);
      setSelectedGroup(null);
      await refetch();
    } catch (err) {
      let errorMessage = "Failed to delete tool";

      if (err instanceof ApiError) {
        const detail = extractApiErrorDetail(err.body);
        errorMessage = detail || `Failed to delete tool: ${err.message || "Unknown error"}`;
      } else if (err instanceof Error) {
        errorMessage = `Failed to delete tool: ${err.message}`;
      }

      toast.error(errorMessage);
    }
  }, [selectedToolId, selectedToolName, refetch]);

  return (
    <div className="p-6">
      {isFormOpen ? (
        <ToolForm
          isOpen={isFormOpen}
          onToggle={() => setIsFormOpen(false)}
          onSuccess={handleFormSuccess}
        />
      ) : (
        <>
          <h1 className="mb-6 text-base font-semibold text-neutral-900 dark:text-white">Tools</h1>

          {isLoading && (
            <div
              role="status"
              aria-live="polite"
              aria-busy="true"
              className="flex items-center justify-center p-12"
            >
              <span className="sr-only">Loading tools, please wait...</span>
              <div className="h-8 w-8 animate-spin rounded-full border-4 border-gray-200 border-t-blue-600 dark:border-gray-700 dark:border-t-blue-400" />
            </div>
          )}

          {error && (
            <div
              className="mb-6 rounded-lg border border-red-200 bg-red-50 p-4 dark:border-red-800 dark:bg-red-900/20"
              role="alert"
              aria-live="assertive"
            >
              <h3 className="mb-1 font-semibold">Error loading tools</h3>
              <p className="text-red-800 dark:text-red-200">{error.message}</p>
            </div>
          )}

          {!isLoading && (
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2 xl:grid-cols-2 2xl:grid-cols-3">
              <AddToolsCard onAddTool={() => setIsFormOpen(true)} />
              {groups.map((group) => (
                <ToolGroupCard
                  key={group.gatewaySlug}
                  group={group}
                  onViewGroup={handleViewGroup}
                />
              ))}
            </div>
          )}

          {selectedGroup && (
            <ToolDetailsPanel
              tools={selectedGroup.tools}
              gatewaySlug={selectedGroup.gatewaySlug}
              open={isDetailsPanelOpen}
              onClose={handleCloseDetails}
              onDeleteTool={handleDelete}
            />
          )}

          <ConfirmDialog
            open={deleteDialogOpen}
            onOpenChange={setDeleteDialogOpen}
            onConfirm={confirmDelete}
            title="Delete tool"
            description={`Are you sure you want to delete "${selectedToolName}"? This action cannot be undone.`}
            confirmLabel="Delete"
            variant="destructive"
          />
        </>
      )}
    </div>
  );
}
