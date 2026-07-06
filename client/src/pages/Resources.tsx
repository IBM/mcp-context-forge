import { useState, useMemo, memo, useCallback, useRef } from "react";
import { useIntl } from "react-intl";
import { Plus, EllipsisVertical, FileText } from "lucide-react";
import { toast } from "sonner";
import { useQuery } from "@/hooks/useQuery";
import { resourcesApi } from "@/api/resources";
import { ApiError } from "@/api/client";
import { extractApiErrorDetail } from "@/utils/errors";
import type {
  ResourceRead,
  GatewayRead,
  CursorPaginatedGatewaysResponse,
  BodyCreateResourceV1ResourcesPost,
} from "@/generated/types";
import { ResourceReadVisibility } from "@/generated/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
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

function getUriLabel(uri: string): string {
  try {
    return new URL(uri).hostname || uri;
  } catch {
    return uri;
  }
}

const ResourceCard = memo(function ResourceCard({
  resource,
  onViewResource,
  onDeleteResource,
}: {
  resource: NonNullable<ResourceRead>;
  onViewResource: (resource: NonNullable<ResourceRead>) => void;
  onDeleteResource: (id: string) => void;
}) {
  const intl = useIntl();

  return (
    <Card size="sm" className="rounded-xl pl-0 pt-4 pb-4">
      <CardHeader>
        <div className="flex items-center gap-3">
          <div className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded bg-tool-icon-bg">
            <FileText className="h-3.5 w-3.5 text-black" />
          </div>

          <div className="flex min-w-0 flex-1 items-center gap-2">
            <span className="truncate text-sm font-semibold text-neutral-900 dark:text-white">
              {resource.name}
            </span>
            <span className="h-1.5 w-1.5 flex-shrink-0 rounded-full bg-tool-status-active" />
          </div>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-label={intl.formatMessage(
                  { id: "resources.card.moreOptions" },
                  { gatewaySlug: resource.name },
                )}
                className="h-7 w-7 p-0"
              >
                <EllipsisVertical className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => onViewResource(resource)}>
                {intl.formatMessage({ id: "resources.card.viewDetails" })}
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => onDeleteResource(resource.id)}
                disabled={resource.id === OPTIMISTIC_RESOURCE_ID}
                className="text-destructive focus:text-destructive"
              >
                {intl.formatMessage({ id: "common.button.delete" })}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </CardHeader>

      <CardContent>
        <div className="flex flex-wrap gap-1">
          {resource.mimeType && (
            <span className="inline-flex items-center rounded bg-neutral-100 px-1.5 py-1 text-[10px] font-medium leading-none text-neutral-700 dark:bg-neutral-800 dark:text-white">
              {resource.mimeType}
            </span>
          )}
          {resource.uri && (
            <span
              className="inline-flex items-center rounded bg-neutral-100 px-1.5 py-1 text-[10px] font-medium leading-none text-neutral-700 dark:bg-neutral-800 dark:text-white"
              title={resource.uri}
            >
              {getUriLabel(resource.uri)}
            </span>
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
  const [selectedResource, setSelectedResource] = useState<NonNullable<ResourceRead> | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deleteResourceId, setDeleteResourceId] = useState<string | null>(null);
  const [deleteResourceName, setDeleteResourceName] = useState<string | null>(null);
  const [shouldRedirectDeleteCloseFocus, setShouldRedirectDeleteCloseFocus] = useState(false);

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
    return new Map(
      gateways.map((gateway) => [
        gateway.id,
        gateway.slug?.trim() || gateway.name?.trim() || gateway.id,
      ]),
    );
  }, [gatewaysData]);

  const handleOptimisticAdd = useCallback(
    (formData: BodyCreateResourceV1ResourcesPost) => {
      const { resource } = formData;
      const optimistic: NonNullable<ResourceRead> = {
        id: "__optimistic__",
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
    setResourcesData((prev) => prev?.filter((r) => r?.id !== "__optimistic__") ?? []);
  }, [setResourcesData]);

  const handleFormSuccess = async () => {
    setShowForm(false);
    await refetch();
  };

  const handleResourceClick = (resource: NonNullable<ResourceRead>) => {
    setSelectedResource(resource);
  };

  const handleClosePanel = () => {
    setSelectedResource(null);
  };

  const handleDeleteResource = useCallback(
    (id: string) => {
      if (id === OPTIMISTIC_RESOURCE_ID) return;
      const resource = data?.find((r) => r?.id === id);
      setDeleteResourceId(id);
      setDeleteResourceName(resource?.name || id);
      setShouldRedirectDeleteCloseFocus(false);
      setDeleteDialogOpen(true);
    },
    [data],
  );

  const confirmDelete = useCallback(async () => {
    if (!deleteResourceId || !deleteResourceName) return;

    const resourceId = deleteResourceId;
    const resourceName = deleteResourceName;
    const previousData = data;

    setResourcesData((prev) => prev?.filter((r) => r?.id !== resourceId) ?? []);
    setShouldRedirectDeleteCloseFocus(true);
    setDeleteDialogOpen(false);
    setDeleteResourceId(null);
    setDeleteResourceName(null);
    setSelectedResource(null);

    try {
      await resourcesApi.delete(resourceId);
      toast.success(intl.formatMessage({ id: "resources.delete.success" }, { name: resourceName }));
      await refetch();
    } catch (err) {
      setResourcesData(previousData);

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
  }, [deleteResourceId, deleteResourceName, data, setResourcesData, refetch, intl]);

  return (
    <div className="p-6">
      {showForm ? (
        <ResourceForm
          isOpen={showForm}
          onToggle={() => setShowForm(false)}
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
              {data
                ?.filter((r): r is NonNullable<ResourceRead> => r !== null)
                .map((resource) => (
                  <ResourceCard
                    key={resource.id}
                    resource={resource}
                    onViewResource={handleResourceClick}
                    onDeleteResource={handleDeleteResource}
                  />
                ))}
            </div>
          )}

          {selectedResource && (
            <ResourceDetailsPanel
              resources={[selectedResource]}
              gatewaySlug={
                selectedResource.gatewayId
                  ? gatewayNameById.get(selectedResource.gatewayId) || selectedResource.gatewayId
                  : "unknown"
              }
              open={!!selectedResource}
              onClose={handleClosePanel}
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
