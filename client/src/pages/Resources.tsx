import { useState, useMemo, memo } from "react";
import { useIntl } from "react-intl";
import { Plus, MoreHorizontal, FileText } from "lucide-react";
import { useQuery } from "@/hooks/useQuery";
import type { ResourceRead, GatewayRead, CursorPaginatedGatewaysResponse } from "@/generated/types";
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

/**
 * Card component displaying a single resource
 * Memoized to prevent unnecessary re-renders when parent updates
 *
 * @param resource - Resource to display
 * @param gatewaySlug - Gateway slug for the resource
 * @param onViewResource - Callback when user clicks to view resource details
 */
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
}: {
  resource: NonNullable<ResourceRead>;
  onViewResource: (resource: NonNullable<ResourceRead>) => void;
}) {
  const intl = useIntl();

  return (
    <Card size="sm" className="border-neutral-800 bg-neutral-900 rounded-xl pl-0 pr-4 pt-4 pb-4">
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
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => onViewResource(resource)}>
                {intl.formatMessage({ id: "resources.card.viewDetails" })}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </CardHeader>

      <CardContent>
        <div className="flex flex-wrap gap-1">
          {resource.mimeType && (
            <span className="inline-flex items-center rounded bg-tool-badge-bg px-1.5 py-1 text-[10px] font-medium leading-none text-white">
              {resource.mimeType}
            </span>
          )}
          {resource.uri && (
            <span
              className="inline-flex items-center rounded bg-tool-badge-bg px-1.5 py-1 text-[10px] font-medium leading-none text-white"
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

/**
 * Card component for adding new resources
 * Displays informational text about resource auto-discovery
 *
 * @param onAddResource - Callback when user clicks to add resources
 */
function AddResourcesCard({ onAddResource }: { onAddResource: () => void }) {
  const intl = useIntl();

  return (
    <Card
      size="sm"
      role="button"
      tabIndex={0}
      className="border-neutral-800 bg-neutral-900 rounded-xl pl-0 pr-4 pt-4 pb-4 cursor-pointer transition-opacity hover:opacity-90"
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
          <div className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded bg-tool-add-icon-bg shadow-sm">
            <Plus className="h-3.5 w-3.5 text-tool-add-icon-fg" />
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

/**
 * Resources page component - displays and manages MCP resources
 * Currently implements read-only listing with grouping by gateway
 * Future PRs will add CRUD operations
 *
 * Features:
 * - Groups resources by gateway slug
 * - Shows resource count and active status per group
 * - Details panel for viewing individual resources
 * - Placeholder form for future resource creation
 */
export function Resources() {
  const intl = useIntl();
  const [showForm, setShowForm] = useState(false);
  const [selectedResource, setSelectedResource] = useState<NonNullable<ResourceRead> | null>(null);

  const { data, isLoading, error, refetch } = useQuery<ResourceRead[]>("/resources?limit=0");
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

  /**
   * @future Implement resource deletion in follow-up PR
   * Delete functionality will include confirmation dialog
   */
  const handleDeleteResource = () => {};

  return (
    <div className="p-6">
      {showForm ? (
        <ResourceForm
          isOpen={showForm}
          onToggle={() => setShowForm(false)}
          onSuccess={handleFormSuccess}
        />
      ) : (
        <>
          <h1 className="mb-6 text-base font-semibold text-neutral-900 dark:text-white">
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
        </>
      )}
    </div>
  );
}
