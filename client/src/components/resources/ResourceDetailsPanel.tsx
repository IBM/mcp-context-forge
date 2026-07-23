import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useIntl } from "react-intl";
import { Activity, Building2, FileText, PanelRightClose } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CopyValue } from "@/components/ui/copy-value";
import { InlineTagAdd } from "@/components/ui/inline-tag-add";
import { cn } from "@/lib/utils";
import type { ResourceRead } from "@/generated/types";
import { formatBytes, formatDateTime } from "@/utils/format";
import { ResourcesTable } from "@/components/resources/ResourcesTable";

function DetailRow({
  label,
  children,
  className,
}: {
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`grid grid-cols-[96px_minmax(0,1fr)] items-start gap-4 ${className ?? ""}`}>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-foreground">{children}</dd>
    </div>
  );
}

interface ResourceDetailsPanelProps {
  resources: NonNullable<ResourceRead>[];
  gatewaySlug: string;
  open: boolean;
  onClose: () => void;
  onEditResource?: (resource: NonNullable<ResourceRead>) => void;
  onDeleteResource?: (resourceId: string) => void;
  /**
   * Persists the resource's full tag list after an inline add. Receives the
   * resource ID and the new complete list of tag labels. When omitted, the tag
   * row shows a non-interactive "add" affordance.
   */
  onAddTag?: (resourceId: string, tags: string[]) => Promise<void>;
}

export function ResourceDetailsPanel({
  resources,
  gatewaySlug,
  open,
  onClose,
  onEditResource,
  onDeleteResource,
  onAddTag,
}: ResourceDetailsPanelProps) {
  const intl = useIntl();
  const [selectedResource, setSelectedResource] = useState<NonNullable<ResourceRead> | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const headingId = useMemo(() => `resource-details-heading-${gatewaySlug}`, [gatewaySlug]);

  // Manage selected resource state: select first on open, reset on close, and
  // re-sync when resources list refreshes to keep details column up-to-date.
  useEffect(() => {
    if (!open) {
      setSelectedResource(null);
      return;
    }

    // Select first resource when panel opens if none selected
    if (resources.length > 0 && !selectedResource) {
      setSelectedResource(resources[0]);
      return;
    }

    // Re-sync the selected resource when the resources list refreshes
    if (selectedResource) {
      const updated = resources.find((r) => r.id === selectedResource.id);
      if (updated && updated !== selectedResource) {
        setSelectedResource(updated);
      }
    }
  }, [open, resources, selectedResource]);

  // Focus close on open; restore focus on close/unmount.
  useEffect(() => {
    if (!open) return;
    previousFocusRef.current = (document.activeElement as HTMLElement | null) ?? null;
    closeButtonRef.current?.focus();
    return () => {
      previousFocusRef.current?.focus?.();
      previousFocusRef.current = null;
    };
  }, [open]);

  // ESC closes while open.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const getVisibilityLabel = useCallback(
    (value?: string | null) => {
      if (value === "team") return intl.formatMessage({ id: "resources.details.visibility.team" });
      if (value === "public")
        return intl.formatMessage({ id: "resources.details.visibility.public" });
      if (value === "private")
        return intl.formatMessage({ id: "resources.details.visibility.private" });
      return intl.formatMessage({ id: "resources.details.notAvailable" });
    },
    [intl],
  );

  return (
    <>
      <div
        data-state={open ? "open" : "closed"}
        aria-hidden="true"
        onClick={onClose}
        className={cn(
          "absolute inset-0 z-10 bg-black/10 transition-opacity duration-150 supports-backdrop-filter:backdrop-blur-xs",
          "data-[state=open]:opacity-100 data-[state=closed]:opacity-0 data-[state=closed]:pointer-events-none",
        )}
      />

      <aside
        role="region"
        aria-labelledby={headingId}
        aria-hidden={!open}
        inert={!open}
        data-state={open ? "open" : "closed"}
        className={cn(
          "absolute inset-y-0 right-0 z-20 flex w-[min(1236px,calc(100%-2rem))] border-l border-border bg-popover text-[13px] shadow-lg",
          "transition-transform duration-200 ease-out",
          "data-[state=open]:translate-x-0 data-[state=closed]:translate-x-full",
          "data-[state=closed]:pointer-events-none",
        )}
      >
        {resources.length > 0 && (
          <div className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden lg:grid-cols-[minmax(0,1fr)_320px]">
            <div className="min-w-0 overflow-y-auto bg-background px-6 py-8 lg:px-12 dark:bg-neutral-900">
              <h2 id={headingId} className="sr-only">
                {intl.formatMessage(
                  { id: "resources.details.resourcesFor" },
                  { name: gatewaySlug },
                )}
              </h2>

              {/* Header with icon and title */}
              <div className="mb-6 flex items-center gap-3">
                <div className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded bg-tool-icon-bg">
                  <FileText className="h-3.5 w-3.5 text-black" />
                </div>
                <div className="min-w-0 flex-1">
                  <h3 className="text-base font-semibold text-foreground">{gatewaySlug}</h3>
                </div>
              </div>

              {/* Table */}
              <ResourcesTable
                resources={resources}
                selectedResourceId={selectedResource?.id}
                onSelectResource={setSelectedResource}
                onEditResource={onEditResource}
                onDeleteResource={onDeleteResource}
              />
            </div>

            <aside className="relative border-t border-border bg-background lg:border-l lg:border-t-0">
              <Button
                ref={closeButtonRef}
                type="button"
                variant="ghost"
                size="icon-xs"
                aria-label={intl.formatMessage({ id: "resources.details.close" })}
                className="absolute right-3 top-3 text-muted-foreground"
                onClick={onClose}
              >
                <PanelRightClose className="size-4" />
              </Button>

              {selectedResource && (
                <>
                  <div className="border-b border-border p-4 pt-8">
                    <h3 className="mb-7 text-sm font-semibold text-foreground">
                      {intl.formatMessage({ id: "resources.details.componentDetails" })}
                    </h3>

                    <dl className="space-y-4">
                      <DetailRow
                        label={intl.formatMessage({ id: "resources.details.label.status" })}
                      >
                        <span className="flex items-center gap-2">
                          <Activity
                            className={`size-3.5 ${
                              selectedResource.enabled ? "text-emerald-400" : "text-gray-400"
                            }`}
                          />
                          {selectedResource.enabled
                            ? intl.formatMessage({ id: "resources.details.status.active" })
                            : intl.formatMessage({ id: "resources.details.status.inactive" })}
                        </span>
                      </DetailRow>
                      <DetailRow
                        label={intl.formatMessage({ id: "resources.details.label.visibility" })}
                      >
                        <span className="flex items-center gap-2">
                          <Building2 className="size-3.5 text-muted-foreground" />
                          {getVisibilityLabel(selectedResource.visibility)}
                        </span>
                      </DetailRow>
                      {selectedResource.mimeType && (
                        <DetailRow
                          label={intl.formatMessage({ id: "resources.details.label.type" })}
                        >
                          <span className="text-foreground">{selectedResource.mimeType}</span>
                        </DetailRow>
                      )}
                      <DetailRow label={intl.formatMessage({ id: "resources.details.label.uri" })}>
                        <CopyValue
                          label={intl.formatMessage({ id: "resources.details.label.uri" })}
                          value={selectedResource.uriTemplate || selectedResource.uri}
                        />
                      </DetailRow>
                      {selectedResource.size != null && (
                        <DetailRow
                          label={intl.formatMessage({ id: "resources.details.label.size" })}
                        >
                          <span className="text-foreground">
                            {formatBytes(selectedResource.size)}
                          </span>
                        </DetailRow>
                      )}
                      {(() => {
                        const tagLabels = selectedResource.tags || [];
                        return (
                          <InlineTagAdd
                            label={intl.formatMessage({ id: "resources.details.label.tags" })}
                            existingTags={tagLabels}
                            onAdd={
                              onAddTag
                                ? (newTags) =>
                                    onAddTag(String(selectedResource.id), [
                                      ...tagLabels,
                                      ...newTags,
                                    ])
                                : undefined
                            }
                          >
                            {tagLabels.map((tag, index) => (
                              <Badge
                                key={`${tag}-${index}`}
                                variant="outline"
                                className="rounded-full px-2 py-0 text-[11px] font-medium text-muted-foreground"
                              >
                                {tag}
                              </Badge>
                            ))}
                          </InlineTagAdd>
                        );
                      })()}
                    </dl>
                  </div>

                  <div className="p-4">
                    <h3 className="mb-7 text-sm font-semibold text-foreground">
                      {intl.formatMessage({ id: "resources.details.activity" })}
                    </h3>
                    <dl className="space-y-4">
                      <DetailRow
                        label={intl.formatMessage({ id: "resources.details.label.created" })}
                      >
                        {formatDateTime(
                          selectedResource.createdAt,
                          intl.formatMessage({ id: "resources.details.notAvailable" }),
                        )}
                      </DetailRow>
                      <DetailRow
                        label={intl.formatMessage({ id: "resources.details.label.lastModified" })}
                      >
                        {formatDateTime(
                          selectedResource.updatedAt,
                          intl.formatMessage({ id: "resources.details.notAvailable" }),
                        )}
                      </DetailRow>
                    </dl>
                  </div>
                </>
              )}
            </aside>
          </div>
        )}
      </aside>
    </>
  );
}
