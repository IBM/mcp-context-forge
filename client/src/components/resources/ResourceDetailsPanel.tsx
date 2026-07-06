import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useIntl } from "react-intl";
import { Activity, Copy, FileText, Globe, PanelRightClose, Plus } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { ResourceRead } from "@/generated/types";
import { copyToClipboard, truncateMiddle } from "@/components/gateways/utils";
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

function CopyValue({ label, value }: { label: string; value: string }) {
  const intl = useIntl();
  return (
    <div className="flex min-w-0 items-center gap-2">
      <span className="min-w-0 flex-1 truncate font-mono text-[12px]">{truncateMiddle(value)}</span>
      <Button
        type="button"
        variant="ghost"
        size="icon-xs"
        className="size-5 text-muted-foreground"
        aria-label={intl.formatMessage({ id: "resources.details.copyValue" }, { label })}
        onClick={() => copyToClipboard(value)}
      >
        <Copy className="size-3.5" />
      </Button>
    </div>
  );
}

export function ResourceDetailsPanel({
  resources,
  gatewaySlug,
  open,
  onClose,
  onEditResource,
  onDeleteResource,
}: {
  resources: NonNullable<ResourceRead>[];
  gatewaySlug: string;
  open: boolean;
  onClose: () => void;
  onEditResource?: (resource: NonNullable<ResourceRead>) => void;
  onDeleteResource?: (resourceId: string) => void;
}) {
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
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // Focus trap: keep focus within panel when open
  useEffect(() => {
    if (!open) return;

    let isRedirecting = false;

    const handleFocusTrap = (e: FocusEvent) => {
      if (isRedirecting) return;

      const panel = document.querySelector('[role="region"][aria-hidden="false"]');
      const closeButton = closeButtonRef.current;
      if (!panel || !closeButton) return;

      const target = e.target as Element | null;
      if (!target || panel.contains(target) || target === closeButton) return;
      if (target.closest("[data-radix-popper-content-wrapper]")) return;

      if (document.activeElement !== closeButton) {
        isRedirecting = true;
        closeButton.focus();
        isRedirecting = false;
      }
    };

    document.addEventListener("focusin", handleFocusTrap, true);
    return () => document.removeEventListener("focusin", handleFocusTrap, true);
  }, [open]);

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
                          <Globe className="size-3.5 text-muted-foreground" />
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
                      <DetailRow
                        label={intl.formatMessage({ id: "resources.details.label.tags" })}
                        className="items-center"
                      >
                        <div className="flex min-w-0 flex-wrap items-center gap-2">
                          {(selectedResource.tags || []).length > 0 ? (
                            <>
                              {(selectedResource.tags || []).map((tag, index) => (
                                <Badge
                                  key={`${tag}-${index}`}
                                  variant="outline"
                                  className="rounded-full px-2 py-0 text-[11px] font-medium text-muted-foreground"
                                >
                                  {tag}
                                </Badge>
                              ))}
                              <button
                                type="button"
                                tabIndex={-1}
                                aria-hidden="true"
                                className="flex items-center gap-1 text-[12px] text-muted-foreground hover:text-foreground"
                              >
                                <Plus className="size-3" aria-hidden="true" />
                                {intl.formatMessage({ id: "resources.details.addTag" })}
                              </button>
                            </>
                          ) : (
                            <button
                              type="button"
                              tabIndex={-1}
                              aria-hidden="true"
                              className="flex items-center gap-1 text-[12px] text-muted-foreground hover:text-foreground"
                            >
                              <Plus className="size-3" aria-hidden="true" />
                              {intl.formatMessage({ id: "resources.details.addTag" })}
                            </button>
                          )}
                        </div>
                      </DetailRow>
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
