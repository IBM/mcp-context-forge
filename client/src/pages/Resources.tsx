import { useState, useMemo, useCallback, useRef, useEffect, memo } from "react";
import { useIntl } from "react-intl";
import { Plus, EllipsisVertical, FileText } from "lucide-react";
import { toast } from "sonner";
import { useQuery } from "@/hooks/useQuery";
import { resourcesApi } from "@/api/resources";
import { ApiError } from "@/api/client";
import { extractApiErrorDetail, sanitizeError } from "@/utils/errors";
import type {
  ResourceRead,
  GatewayRead,
  CursorPaginatedGatewaysResponse,
  BodyCreateResourceV1ResourcesPost,
} from "@/generated/types";
import { ResourceReadVisibility } from "@/generated/types";
import type { ResourceGroup } from "@/types/resource";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { CardTag } from "@/components/ui/card-tag";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ResourceForm } from "@/components/resources/ResourceForm";
import { ResourceDetailsPanel } from "@/components/resources/ResourceDetailsPanel";
import { ConfirmDialog } from "@/components/servers/ConfirmDialog";

const OPTIMISTIC_RESOURCE_ID = "__optimistic__";
/** Maximum number of resource badges to display before showing "+N more" overflow indicator */
const MAX_VISIBLE_RESOURCE_BADGES = 8;

/**
 * Groups resources by their gateway slug for display in the Resources page.
 * Resources without a gateway are grouped under the REST resources label.
 * Each group tracks whether any of its resources are enabled (active status).
 *
 * @param resources - Array of resources to group
 * @param gatewayNameById - Map of gateway IDs to display names (slug or name)
 * @param restResourcesLabel - Localized label for resources without a gateway
 * @returns Array of resource groups with computed active status
 */
function buildGroups(
  resources: NonNullable<ResourceRead>[],
  gatewayNameById: Map<string, string>,
  restResourcesLabel: string,
): ResourceGroup[] {
  const map = new Map<string, ResourceGroup>();
  for (const resource of resources) {
    const slug = resource.gatewayId
      ? (gatewayNameById.get(resource.gatewayId) ?? resource.gatewayId)
      : restResourcesLabel;

    let group = map.get(slug);
    if (!group) {
      group = {
        gatewaySlug: slug,
        gatewayId: resource.gatewayId ?? undefined,
        resources: [],
        isActive: false,
      };
      map.set(slug, group);
    }

    group.resources.push(resource);
    group.isActive = group.isActive || !!resource.enabled;
  }
  return Array.from(map.values());
}

const ResourceGroupCard = memo(function ResourceGroupCard({
  group,
  onViewGroup,
}: {
  group: ResourceGroup;
  onViewGroup: (group: ResourceGroup) => void;
}) {
  const intl = useIntl();
  const visibleResources = group.resources.slice(0, MAX_VISIBLE_RESOURCE_BADGES);
  const remainingCount = group.resources.length - MAX_VISIBLE_RESOURCE_BADGES;

  const handleView = () => {
    onViewGroup(group);
  };

  return (
    <Card size="sm" className="rounded-xl pl-0 pt-4 pb-4">
      <CardHeader>
        <div className="flex items-center gap-3">
          <div className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded bg-tool-icon-bg">
            <FileText className="h-3.5 w-3.5 text-black" />
          </div>

          <div className="flex min-w-0 flex-1 items-center gap-2">
            <span className="truncate text-sm font-semibold text-neutral-500 dark:text-neutral-400">
              {group.gatewaySlug}
            </span>
            <span className="whitespace-nowrap text-sm font-semibold text-neutral-900 dark:text-white">
              {intl.formatMessage(
                { id: "resources.card.resourceCount" },
                { count: group.resources.length },
              )}
            </span>
            <span
              role="img"
              aria-label={intl.formatMessage({
                id: group.isActive
                  ? "resources.details.status.active"
                  : "resources.details.status.inactive",
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
                  { id: "resources.card.moreOptionsFor" },
                  { name: group.gatewaySlug },
                )}
                className="h-7 w-7 p-0"
              >
                <EllipsisVertical className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={handleView}>
                {intl.formatMessage({ id: "resources.card.viewDetails" })}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </CardHeader>

      <CardContent>
        <div className="flex flex-wrap gap-1">
          {visibleResources.map((resource) => (
            <CardTag
              key={resource.id}
              variant="neutral"
              tooltip={resource.description ?? undefined}
            >
              {resource.name}
            </CardTag>
          ))}
          {remainingCount > 0 && (
            <CardTag
              variant="neutral"
              tooltip={intl.formatMessage(
                { id: "resources.card.moreResources" },
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
});

function AddResourcesCard({ onAddResource }: { onAddResource: () => void }) {
  const intl = useIntl();

  return (
    <Card
      size="sm"
      role="button"
      tabIndex={0}
      className="rounded-xl pl-0 pr-4 pt-4 pb-4 cursor-pointer transition-opacity hover:opacity-90"
      onClick={onAddResource}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onAddResource();
        }
      }}
    >
      <CardHeader>
        <div className="flex items-center gap-3">
          <div className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded bg-neutral-200 shadow-sm dark:bg-white">
            <Plus className="h-3.5 w-3.5 text-neutral-700 dark:text-neutral-900" />
          </div>
          <span className="text-sm font-semibold text-neutral-900 dark:text-white">
            {intl.formatMessage({ id: "resources.addResources.title" })}
          </span>
        </div>
      </CardHeader>
      <CardContent>
        <p className="text-sm leading-relaxed text-neutral-500 dark:text-neutral-400">
          {intl.formatMessage({ id: "resources.addResources.description" })}
        </p>
      </CardContent>
    </Card>
  );
}

export function Resources() {
  const intl = useIntl();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [showForm, setShowForm] = useState(false);
  const [selectedGroup, setSelectedGroup] = useState<ResourceGroup | null>(null);
  const [isDetailsPanelOpen, setIsDetailsPanelOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deleteResourceId, setDeleteResourceId] = useState<string | null>(null);
  const [deleteResourceName, setDeleteResourceName] = useState<string | null>(null);
  const [shouldRedirectDeleteCloseFocus, setShouldRedirectDeleteCloseFocus] = useState(false);
  const [shouldRestoreFormCloseFocus, setShouldRestoreFormCloseFocus] = useState(false);

  const {
    data,
    isLoading,
    error,
    refetch,
    setData: setResourcesData,
  } = useQuery<ResourceRead[]>("/resources?limit=0");
  const { data: gatewaysData } = useQuery<CursorPaginatedGatewaysResponse>(
    "/gateways?limit=0&include_pagination=true",
    {
      enabled: !isLoading,
    },
  );

  const gatewayNameById = useMemo(() => {
    const gateways: NonNullable<GatewayRead>[] = (gatewaysData?.gateways ?? []).filter(
      (g): g is NonNullable<GatewayRead> => g !== null,
    );
    const entries: [string, string][] = [];
    for (const gateway of gateways) {
      if (!gateway.id) continue;
      entries.push([gateway.id, gateway.slug?.trim() || gateway.name?.trim() || gateway.id]);
    }
    return new Map(entries);
  }, [gatewaysData]);

  const validResources = useMemo(
    () => (data ?? []).filter((r): r is NonNullable<ResourceRead> => r !== null),
    [data],
  );

  const restResourcesLabel = useMemo(
    () => intl.formatMessage({ id: "resources.restResourcesGroup" }),
    [intl],
  );
  const groups = useMemo(
    () => buildGroups(validResources, gatewayNameById, restResourcesLabel),
    [validResources, gatewayNameById, restResourcesLabel],
  );

  // Keep the open details panel pointed at the latest group data so status
  // changes (e.g. a delete elsewhere) are reflected once the list is updated.
  const activeGroup = useMemo(
    () =>
      selectedGroup
        ? (groups.find((g) => g.gatewaySlug === selectedGroup.gatewaySlug) ?? selectedGroup)
        : null,
    [groups, selectedGroup],
  );

  const handleOptimisticAdd = useCallback(
    (formData: BodyCreateResourceV1ResourcesPost) => {
      const { resource } = formData;
      const optimistic: NonNullable<ResourceRead> = {
        id: OPTIMISTIC_RESOURCE_ID,
        uri: resource.uri,
        name: resource.name,
        description: resource.description ?? null,
        mimeType: resource.mimeType ?? null,
        size: null,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        enabled: true,
        tags: resource.tags ?? [],
        visibility:
          (resource.visibility as ResourceReadVisibility) ?? ResourceReadVisibility.public,
      };
      setResourcesData((prev) => [optimistic, ...(prev ?? [])]);
    },
    [setResourcesData],
  );

  const handleOptimisticRollback = useCallback(() => {
    setResourcesData((prev) => prev?.filter((r) => r?.id !== OPTIMISTIC_RESOURCE_ID) ?? []);
  }, [setResourcesData]);

  const handleFormSuccess = async () => {
    setShouldRestoreFormCloseFocus(true);
    setShowForm(false);
    await refetch();
  };

  useEffect(() => {
    if (!showForm && shouldRestoreFormCloseFocus) {
      headingRef.current?.focus();
      setShouldRestoreFormCloseFocus(false);
    }
  }, [showForm, shouldRestoreFormCloseFocus]);

  const handleViewGroup = (group: ResourceGroup) => {
    setSelectedGroup(group);
    setIsDetailsPanelOpen(true);
  };

  const handleCloseDetails = () => {
    setIsDetailsPanelOpen(false);
  };

  const handleDeleteResource = useCallback(
    (id: string) => {
      if (id === OPTIMISTIC_RESOURCE_ID) return;
      const resource = validResources.find((r) => r.id === id);
      setDeleteResourceId(id);
      setDeleteResourceName(resource?.name || id);
      setShouldRedirectDeleteCloseFocus(false);
      setDeleteDialogOpen(true);
    },
    [validResources],
  );

  const confirmDelete = useCallback(async () => {
    if (!deleteResourceId || !deleteResourceName) return;

    const idToDelete = deleteResourceId;
    const nameToDelete = deleteResourceName;

    const previousData = data;
    const previousGroup = selectedGroup
      ? { ...selectedGroup, resources: selectedGroup.resources.map((r) => ({ ...r })) }
      : null;

    setResourcesData((prev) => prev?.filter((r) => r?.id !== idToDelete) ?? []);

    const remainingGroupResources =
      selectedGroup?.resources.filter((r) => r.id !== idToDelete) ?? [];
    const nextGroup =
      selectedGroup && remainingGroupResources.length > 0
        ? { ...selectedGroup, resources: remainingGroupResources }
        : null;
    setSelectedGroup(nextGroup);
    setShouldRedirectDeleteCloseFocus(!nextGroup);
    if (!nextGroup) setIsDetailsPanelOpen(false);

    setDeleteDialogOpen(false);
    setDeleteResourceId(null);
    setDeleteResourceName(null);

    try {
      await resourcesApi.delete(idToDelete);
      toast.success(intl.formatMessage({ id: "resources.delete.success" }, { name: nameToDelete }));

      try {
        await refetch();
      } catch (refreshErr) {
        console.error("Failed to refresh resources after deletion:", sanitizeError(refreshErr));
        toast.warning(intl.formatMessage({ id: "resources.delete.refreshFailed" }), {
          description: intl.formatMessage({
            id: "resources.delete.refreshFailedDescription",
          }),
        });
      }
    } catch (err) {
      setResourcesData(previousData);
      setSelectedGroup(previousGroup);
      setIsDetailsPanelOpen(!!previousGroup);
      setShouldRedirectDeleteCloseFocus(false);

      console.error("Delete rollback:", sanitizeError(err));

      let errorMessage = intl.formatMessage({ id: "resources.delete.error" });

      if (err instanceof ApiError) {
        const detail = extractApiErrorDetail(err.body);
        errorMessage =
          detail ||
          intl.formatMessage(
            { id: "resources.delete.errorWithMessage" },
            { message: err.message || intl.formatMessage({ id: "resources.delete.errorUnknown" }) },
          );
      } else if (err instanceof Error) {
        errorMessage = intl.formatMessage(
          { id: "resources.delete.errorWithMessage" },
          { message: err.message },
        );
      }

      toast.error(errorMessage);
    }
  }, [deleteResourceId, deleteResourceName, data, selectedGroup, setResourcesData, refetch, intl]);

  return (
    <div className="p-6">
      {showForm ? (
        <ResourceForm
          isOpen={showForm}
          onToggle={() => {
            setShouldRestoreFormCloseFocus(true);
            setShowForm(false);
          }}
          onSuccess={handleFormSuccess}
          onBeforeSubmit={handleOptimisticAdd}
          onError={handleOptimisticRollback}
        />
      ) : (
        <>
          <h1
            ref={headingRef}
            tabIndex={-1}
            className="mb-6 text-base font-semibold text-neutral-900 dark:text-white"
          >
            {intl.formatMessage({ id: "resources.title" })}
          </h1>

          {isLoading && (
            <div
              role="status"
              aria-live="polite"
              aria-busy="true"
              className="flex items-center justify-center p-12"
            >
              <span className="sr-only">{intl.formatMessage({ id: "resources.loading" })}</span>
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
                {intl.formatMessage({ id: "resources.errorLoading" })}
              </h3>
              <p className="text-red-800 dark:text-red-200">{error.message}</p>
            </div>
          )}

          {!isLoading && (
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2 2xl:grid-cols-3">
              <AddResourcesCard onAddResource={() => setShowForm(true)} />
              {groups.map((group) => (
                <ResourceGroupCard
                  key={group.gatewaySlug}
                  group={group}
                  onViewGroup={handleViewGroup}
                />
              ))}
            </div>
          )}

          {activeGroup && (
            <ResourceDetailsPanel
              resources={activeGroup.resources}
              gatewaySlug={activeGroup.gatewaySlug}
              open={isDetailsPanelOpen}
              onClose={handleCloseDetails}
              onDeleteResource={handleDeleteResource}
            />
          )}

          <ConfirmDialog
            open={deleteDialogOpen}
            onOpenChange={setDeleteDialogOpen}
            onConfirm={confirmDelete}
            title={intl.formatMessage({ id: "resources.delete.confirm.title" })}
            description={intl.formatMessage(
              { id: "resources.delete.confirm.description" },
              { name: deleteResourceName },
            )}
            confirmLabel={intl.formatMessage({ id: "resources.delete.confirm.button" })}
            variant="destructive"
            closeOnConfirm={false}
            onCloseAutoFocus={(event) => {
              if (!shouldRedirectDeleteCloseFocus) return;

              // The card/panel that held focus is gone (removed optimistically),
              // so Radix's default restore-to-trigger would drop focus on <body>.
              event.preventDefault();
              headingRef.current?.focus();
              setShouldRedirectDeleteCloseFocus(false);
            }}
          />
        </>
      )}
    </div>
  );
}

