import { useState, useMemo, memo } from "react";
import { useIntl } from "react-intl";
import { Plus, MoreHorizontal, FileText } from "lucide-react";
import { useQuery } from "@/hooks/useQuery";
import type { ResourceGroup, ResourcesResponse } from "@/types/resource";
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
import { groupResourcesByGateway } from "@/utils/resourceGrouping";

/**
 * Card component displaying a group of resources from a single gateway
 * Memoized to prevent unnecessary re-renders when parent updates
 *
 * @param group - Resource group to display
 * @param onViewGroup - Callback when user clicks to view group details
 */
const ResourceGroupCard = memo(function ResourceGroupCard({
  group,
  onViewGroup,
}: {
  group: ResourceGroup;
  onViewGroup: (group: ResourceGroup) => void;
}) {
  const intl = useIntl();
  const MAX_VISIBLE_RESOURCES = 8;
  const visibleResources = group.resources.slice(0, MAX_VISIBLE_RESOURCES);
  const remainingCount = group.resources.length - MAX_VISIBLE_RESOURCES;

  const handleView = () => {
    onViewGroup(group);
  };

  return (
    <Card size="sm">
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
                  { id: "resources.card.moreOptions" },
                  { gatewaySlug: group.gatewaySlug },
                )}
                className="h-7 w-7 p-0"
              >
                <MoreHorizontal className="h-4 w-4" />
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
            <span
              key={resource.id}
              className="inline-flex items-center rounded bg-tool-badge-bg px-1.5 py-1 text-[10px] font-medium leading-none text-white"
              title={resource.description}
            >
              {resource.name}
            </span>
          ))}
          {remainingCount > 0 && (
            <span
              className="inline-flex items-center rounded bg-tool-badge-bg px-1.5 py-1 text-[10px] font-medium leading-none text-white"
              title={intl.formatMessage(
                { id: "resources.card.moreResources" },
                { count: remainingCount },
              )}
            >
              +{remainingCount}
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
      className="cursor-pointer transition-opacity hover:opacity-90"
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
  const [selectedGroup, setSelectedGroup] = useState<ResourceGroup | null>(null);

  const { data, isLoading, error, refetch } = useQuery<ResourcesResponse>("/resources?limit=0");

  // Group resources by gateway using utility function
  const resourceGroups = useMemo<ResourceGroup[]>(
    () => groupResourcesByGateway(data?.data ?? []),
    [data?.data],
  );

  const handleFormSuccess = async () => {
    setShowForm(false);
    await refetch();
  };

  const handleGroupClick = (group: ResourceGroup) => {
    setSelectedGroup(group);
  };

  const handleClosePanel = () => {
    setSelectedGroup(null);
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
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2 xl:grid-cols-2 2xl:grid-cols-3">
              <AddResourcesCard onAddResource={() => setShowForm(true)} />
              {resourceGroups.map((group) => (
                <ResourceGroupCard
                  key={group.gatewaySlug}
                  group={group}
                  onViewGroup={handleGroupClick}
                />
              ))}
            </div>
          )}

          {selectedGroup && (
            <ResourceDetailsPanel
              resources={selectedGroup.resources}
              gatewaySlug={selectedGroup.gatewaySlug}
              open={!!selectedGroup}
              onClose={handleClosePanel}
              onDeleteResource={handleDeleteResource}
            />
          )}
        </>
      )}
    </div>
  );
}
