import { useMemo, useState, useCallback, useEffect } from "react";
import { useIntl } from "react-intl";
import { Plus, EllipsisVertical, Wrench } from "lucide-react";
import { toast } from "sonner";
import { useQuery } from "@/hooks/useQuery";
import { toolsApi } from "@/api/tools";
import { ApiError } from "@/api/client";
import { useRouter } from "@/router";
import { extractApiErrorDetail, sanitizeError } from "@/utils/errors";
import type { Tool, ToolGroup } from "@/types/tool";
import { Card, CardHeader, CardContent } from "@/components/ui/card";
import { CardTag } from "@/components/ui/card-tag";
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

function buildGroups(tools: Tool[], restToolsLabel: string): ToolGroup[] {
  const map = new Map<string, ToolGroup>();
  for (const tool of tools) {
    const slug = tool.gatewaySlug || restToolsLabel;
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
  const intl = useIntl();
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
              {intl.formatMessage({ id: "tools.card.toolCount" }, { count: group.tools.length })}
            </span>
            <span
              role="img"
              aria-label={intl.formatMessage({
                id: group.isActive
                  ? "tools.details.status.active"
                  : "tools.details.status.inactive",
              })}
              className={`h-1.5 w-1.5 flex-shrink-0 rounded-full ${group.isActive ? "bg-tool-status-active" : "bg-tool-status-inactive"}`}
            />
          </div>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-label={intl.formatMessage(
                  { id: "tools.card.moreOptionsFor" },
                  { name: group.gatewaySlug },
                )}
                className="h-7 w-7 p-0"
              >
                <EllipsisVertical className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={handleView}>
                {intl.formatMessage({ id: "tools.card.viewDetails" })}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </CardHeader>

      <CardContent>
        <div className="flex flex-wrap gap-1">
          {visibleTools.map((tool) => (
            <CardTag key={tool.id} tooltip={tool.description}>
              {tool.name}
            </CardTag>
          ))}
          {remainingCount > 0 && (
            <CardTag
              tooltip={intl.formatMessage(
                { id: "tools.card.moreToolsTitle" },
                { count: remainingCount },
              )}
            >
              +{remainingCount}
            </CardTag>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function AddToolsCard({ onAddTool }: { onAddTool: () => void }) {
  const intl = useIntl();
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
          <span className="text-sm font-semibold text-neutral-900 dark:text-white">
            {intl.formatMessage({ id: "tools.add.title" })}
          </span>
        </div>
      </CardHeader>
      <CardContent>
        <p className="text-sm leading-relaxed text-neutral-500 dark:text-neutral-400">
          {intl.formatMessage({ id: "tools.add.description" })}
        </p>
      </CardContent>
    </Card>
  );
}

export function Tools() {
  const intl = useIntl();
  const { path } = useRouter();
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editingTool, setEditingTool] = useState<Tool | null>(null);
  const [selectedGroup, setSelectedGroup] = useState<ToolGroup | null>(null);
  const [selectedToolIdForDetails, setSelectedToolIdForDetails] = useState<string | null>(null);
  const [isDetailsPanelOpen, setIsDetailsPanelOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [selectedToolId, setSelectedToolId] = useState<string | null>(null);
  const [selectedToolName, setSelectedToolName] = useState<string | null>(null);
  const [allTools, setAllTools] = useState<Tool[]>([]);
  const selectedSearchToolId = useMemo(() => {
    const queryString = path.split("?")[1] ?? "";
    return new URLSearchParams(queryString).get("selected")?.trim() || null;
  }, [path]);

  // include_inactive=true so deactivated tools stay listed (and re-activatable);
  // the backend filters them out by default.
  const {
    data: toolsData,
    error,
    isLoading,
    refetch,
    setData: setToolsData,
  } = useQuery<Tool[]>("/tools?limit=0&include_inactive=true");

  useEffect(() => {
    if (toolsData) setAllTools(toolsData);
  }, [toolsData]);

  const { data: editedToolData } = useQuery<Tool>(`/tools/${editingTool?.id}`, {
    enabled: Boolean(editingTool?.id),
  });

  const toolForForm = editedToolData?.id === editingTool?.id ? editedToolData : editingTool;

  const restToolsLabel = intl.formatMessage({ id: "tools.restToolsGroup" });
  const groups = useMemo(() => buildGroups(allTools, restToolsLabel), [allTools, restToolsLabel]);

  // Keep the open details panel pointed at the latest group data so status
  // changes (e.g. activate/deactivate) are reflected once the list is updated.
  const activeGroup = useMemo(
    () =>
      selectedGroup
        ? (groups.find((g) => g.gatewaySlug === selectedGroup.gatewaySlug) ?? selectedGroup)
        : null,
    [groups, selectedGroup],
  );

  const handleFormSuccess = () => {
    setIsFormOpen(false);
    setEditingTool(null);
    refetch();
  };

  const handleEditTool = useCallback((tool: Tool) => {
    setEditingTool(tool);
    setIsDetailsPanelOpen(false);
    setIsFormOpen(true);
  }, []);

  const handleViewGroup = (group: ToolGroup) => {
    setSelectedToolIdForDetails(null);
    setSelectedGroup(group);
    setIsDetailsPanelOpen(true);
  };

  const handleCloseDetails = () => {
    setIsDetailsPanelOpen(false);
    setSelectedToolIdForDetails(null);
  };

  useEffect(() => {
    if (!selectedSearchToolId) return;

    const group = groups.find((candidate) =>
      candidate.tools.some((tool) => tool.id === selectedSearchToolId),
    );
    if (!group) return;

    setSelectedGroup(group);
    setSelectedToolIdForDetails(selectedSearchToolId);
    setIsDetailsPanelOpen(true);
  }, [groups, selectedSearchToolId]);

  const handleToggleTool = useCallback(
    async (tool: Tool) => {
      const name = tool.displayName || tool.name || tool.id;
      const activate = !tool.enabled;

      try {
        await (activate ? toolsApi.activate(tool.id) : toolsApi.deactivate(tool.id));
        // Refresh only the affected tool and patch it into the list, instead of
        // refetching the whole catalog.
        const updated = await toolsApi.get(tool.id);
        setToolsData((prev) => prev?.map((t) => (t.id === updated.id ? updated : t)));
        toast.success(
          intl.formatMessage(
            {
              id: activate ? "tools.toggle.activateSuccess" : "tools.toggle.deactivateSuccess",
            },
            { name },
          ),
        );
      } catch (err) {
        let errorMessage = intl.formatMessage({ id: "tools.toggle.error" });

        if (err instanceof ApiError) {
          const detail = extractApiErrorDetail(err.body);
          errorMessage =
            detail ||
            intl.formatMessage(
              { id: "tools.toggle.errorWithMessage" },
              {
                message: err.message || intl.formatMessage({ id: "tools.toggle.errorUnknown" }),
              },
            );
        } else if (err instanceof Error) {
          errorMessage = intl.formatMessage(
            { id: "tools.toggle.errorWithMessage" },
            { message: err.message },
          );
        }

        toast.error(errorMessage);
      }
    },
    [setToolsData, intl],
  );

  const handleAddToolTag = useCallback(
    async (toolId: string, tags: string[]) => {
      try {
        const updated = await toolsApi.updateTags(toolId, tags);
        setToolsData((prev) => prev?.map((t) => (t.id === updated.id ? updated : t)));
      } catch (err) {
        const detail = err instanceof ApiError ? extractApiErrorDetail(err.body) : null;
        toast.error(detail || intl.formatMessage({ id: "tools.tags.addError" }));
        throw err;
      }
    },
    [setToolsData, intl],
  );

  const handleDelete = useCallback(
    (id: string) => {
      const tool = allTools.find((t) => t.id === id);
      setSelectedToolId(id);
      setSelectedToolName(tool?.displayName || tool?.name || id);
      setDeleteDialogOpen(true);
    },
    [allTools],
  );

  const confirmDelete = useCallback(async () => {
    if (!selectedToolId || !selectedToolName) return;

    const idToDelete = selectedToolId;
    const nameToDelete = selectedToolName;

    const previousTools = allTools;
    const previousGroup = selectedGroup
      ? { ...selectedGroup, tools: selectedGroup.tools.map((t) => ({ ...t })) }
      : null;

    setAllTools(allTools.filter((t) => t.id !== idToDelete));

    const remainingGroupTools = selectedGroup?.tools.filter((t) => t.id !== idToDelete) ?? [];
    const nextGroup =
      selectedGroup && remainingGroupTools.length > 0
        ? { ...selectedGroup, tools: remainingGroupTools }
        : null;
    setSelectedGroup(nextGroup);
    if (!nextGroup) setIsDetailsPanelOpen(false);

    setDeleteDialogOpen(false);
    setSelectedToolId(null);
    setSelectedToolName(null);

    try {
      await toolsApi.delete(idToDelete);
      toast.success(intl.formatMessage({ id: "tools.delete.success" }, { name: nameToDelete }));

      try {
        await refetch();
      } catch (refreshErr) {
        console.error("Failed to refresh tools after deletion:", sanitizeError(refreshErr));
      }
    } catch (err) {
      setAllTools(previousTools);
      setSelectedGroup(previousGroup);
      if (previousGroup) setIsDetailsPanelOpen(true);

      let errorMessage = intl.formatMessage({ id: "tools.delete.error" });

      if (err instanceof ApiError) {
        const detail = extractApiErrorDetail(err.body);
        errorMessage =
          detail ||
          intl.formatMessage(
            { id: "tools.delete.errorWithMessage" },
            {
              message: err.message || intl.formatMessage({ id: "tools.delete.errorUnknown" }),
            },
          );
      } else if (err instanceof Error) {
        errorMessage = intl.formatMessage(
          { id: "tools.delete.errorWithMessage" },
          { message: err.message },
        );
      }

      toast.error(errorMessage);
    }
  }, [allTools, selectedToolId, selectedToolName, selectedGroup, refetch, intl]);

  return (
    <div className="p-6">
      {isFormOpen ? (
        <ToolForm
          isOpen={isFormOpen}
          onToggle={() => {
            setIsFormOpen(false);
            setEditingTool(null);
          }}
          onSuccess={handleFormSuccess}
          tool={toolForForm ?? undefined}
        />
      ) : (
        <>
          <h1 className="mb-6 text-base font-semibold text-neutral-900 dark:text-white">
            {intl.formatMessage({ id: "tools.title" })}
          </h1>

          {isLoading && (
            <div
              role="status"
              aria-live="polite"
              aria-busy="true"
              className="flex items-center justify-center p-12"
            >
              <span className="sr-only">{intl.formatMessage({ id: "tools.loading" })}</span>
              <div className="h-8 w-8 animate-spin rounded-full border-4 border-gray-200 border-t-blue-600 dark:border-gray-700 dark:border-t-blue-400" />
            </div>
          )}

          {error && (
            <div
              className="mb-6 rounded-lg border border-red-200 bg-red-50 p-4 dark:border-red-800 dark:bg-red-900/20"
              role="alert"
              aria-live="assertive"
            >
              <h3 className="mb-1 font-semibold">
                {intl.formatMessage({ id: "tools.error.loading" })}
              </h3>
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

          {activeGroup && (
            <ToolDetailsPanel
              tools={activeGroup.tools}
              gatewaySlug={activeGroup.gatewaySlug}
              open={isDetailsPanelOpen}
              selectedToolId={selectedToolIdForDetails}
              onClose={handleCloseDetails}
              onDeleteTool={handleDelete}
              onEditTool={handleEditTool}
              onToggleTool={handleToggleTool}
              onAddTag={handleAddToolTag}
            />
          )}

          <ConfirmDialog
            open={deleteDialogOpen}
            onOpenChange={setDeleteDialogOpen}
            onConfirm={confirmDelete}
            title={intl.formatMessage({ id: "tools.delete.confirm.title" })}
            description={intl.formatMessage(
              { id: "tools.delete.confirm.description" },
              { name: selectedToolName },
            )}
            confirmLabel={intl.formatMessage({ id: "tools.delete.confirm.button" })}
            variant="destructive"
          />
        </>
      )}
    </div>
  );
}
