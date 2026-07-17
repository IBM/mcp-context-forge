import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useIntl } from "react-intl";
import { Activity, Copy, Globe, PanelRightClose, Wrench } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { InlineTagAdd } from "@/components/ui/inline-tag-add";
import { cn } from "@/lib/utils";
import type { Tool } from "@/types/tool";
import { copyToClipboard } from "@/lib/clipboard";
import { truncateMiddle } from "@/components/gateways/utils";
import { formatDateTime } from "@/utils/format";
import { ToolsTable } from "@/components/tools/ToolsTable";

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
        aria-label={intl.formatMessage({ id: "tools.details.copyValue" }, { label })}
        onClick={() => copyToClipboard(value)}
      >
        <Copy className="size-3.5" />
      </Button>
    </div>
  );
}

export function ToolDetailsPanel({
  tools,
  gatewaySlug,
  open,
  selectedToolId,
  onClose,
  onDeleteTool,
  onEditTool,
  onToggleTool,
  onAddTag,
}: {
  tools: Tool[];
  gatewaySlug: string;
  open: boolean;
  selectedToolId?: string | null;
  onClose: () => void;
  onDeleteTool?: (toolId: string) => void;
  onEditTool?: (tool: Tool) => void;
  onToggleTool?: (tool: Tool) => void;
  /**
   * Persists the tool's full tag list after an inline add. Receives the tool ID
   * and the new complete list of tag labels. When omitted, the tag row shows a
   * non-interactive "add" affordance.
   */
  onAddTag?: (toolId: string, tags: string[]) => Promise<void>;
}) {
  const intl = useIntl();
  const [selectedTool, setSelectedTool] = useState<Tool | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const headingId = useMemo(() => `tool-details-heading-${gatewaySlug}`, [gatewaySlug]);

  // Select the requested tool when opened from global search; otherwise use the first tool.
  useEffect(() => {
    if (!open || tools.length === 0) return;

    const requestedTool = selectedToolId ? tools.find((tool) => tool.id === selectedToolId) : null;
    const nextTool = requestedTool ?? selectedTool ?? tools[0];
    if (nextTool && selectedTool?.id !== nextTool.id) {
      setSelectedTool(nextTool);
    }
  }, [open, tools, selectedTool, selectedToolId]);

  // Reset selected tool when panel closes
  useEffect(() => {
    if (!open) {
      setSelectedTool(null);
    }
  }, [open]);

  // Re-sync the selected tool when the tools list refreshes (e.g. after an
  // activate/deactivate) so the details column reflects the latest status.
  useEffect(() => {
    if (!selectedTool) return;
    const updated = tools.find((t) => t.id === selectedTool.id);
    if (updated && updated !== selectedTool) {
      setSelectedTool(updated);
    }
  }, [tools, selectedTool]);

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
      if (value === "team") return intl.formatMessage({ id: "tools.details.visibility.team" });
      if (value === "public") return intl.formatMessage({ id: "tools.details.visibility.public" });
      if (value === "private")
        return intl.formatMessage({ id: "tools.details.visibility.private" });
      return intl.formatMessage({ id: "tools.details.notAvailable" });
    },
    [intl],
  );

  const getIntegrationTypeLabel = useCallback(
    (type?: string) => {
      if (type === "MCP") return intl.formatMessage({ id: "tools.details.integrationType.mcp" });
      if (type === "REST") return intl.formatMessage({ id: "tools.details.integrationType.rest" });
      if (type === "GRPC") return intl.formatMessage({ id: "tools.details.integrationType.grpc" });
      return type ?? intl.formatMessage({ id: "tools.details.notAvailable" });
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
        {tools.length > 0 && (
          <div className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden lg:grid-cols-[minmax(0,1fr)_320px]">
            <div className="min-w-0 overflow-y-auto bg-background px-6 py-8 lg:px-12 dark:bg-neutral-900">
              <h2 id={headingId} className="sr-only">
                {intl.formatMessage({ id: "tools.details.toolsFor" }, { name: gatewaySlug })}
              </h2>

              {/* Header with icon and title */}
              <div className="mb-6 flex items-center gap-3">
                <div className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded bg-tool-icon-bg">
                  <Wrench className="h-3.5 w-3.5 text-black" />
                </div>
                <div className="min-w-0 flex-1">
                  <h3 className="text-base font-semibold text-foreground">{gatewaySlug}</h3>
                </div>
              </div>

              {/* Subtitle */}
              <p className="mb-8 text-sm text-muted-foreground">
                {getIntegrationTypeLabel(tools[0]?.integrationType)}
              </p>

              {/* Table */}
              <ToolsTable
                tools={tools}
                selectedToolId={selectedTool?.id}
                onSelectTool={setSelectedTool}
                onDeleteTool={onDeleteTool}
                onEditTool={onEditTool}
                onToggleTool={onToggleTool}
              />
            </div>

            <aside className="relative border-t border-border bg-background lg:border-l lg:border-t-0">
              <Button
                ref={closeButtonRef}
                type="button"
                variant="ghost"
                size="icon-xs"
                aria-label={intl.formatMessage({ id: "tools.details.close" })}
                className="absolute right-3 top-3 text-muted-foreground"
                onClick={onClose}
              >
                <PanelRightClose className="size-4" />
              </Button>

              {selectedTool && (
                <>
                  <div className="border-b border-border p-4 pt-8">
                    <h3 className="mb-7 text-sm font-semibold text-foreground">
                      {intl.formatMessage({ id: "tools.details.componentDetails" })}
                    </h3>

                    <dl className="space-y-4">
                      <DetailRow label={intl.formatMessage({ id: "tools.details.label.status" })}>
                        <span className="flex items-center gap-2">
                          <Activity
                            className={`size-3.5 ${
                              selectedTool.enabled && selectedTool.reachable
                                ? "text-emerald-400"
                                : "text-gray-400"
                            }`}
                          />
                          {selectedTool.enabled
                            ? selectedTool.reachable
                              ? intl.formatMessage({ id: "tools.details.status.active" })
                              : intl.formatMessage({ id: "tools.details.status.unreachable" })
                            : intl.formatMessage({ id: "tools.details.status.inactive" })}
                        </span>
                      </DetailRow>
                      <DetailRow
                        label={intl.formatMessage({ id: "tools.details.label.visibility" })}
                      >
                        <span className="flex items-center gap-2">
                          <Globe className="size-3.5 text-muted-foreground" />
                          {getVisibilityLabel(selectedTool.visibility)}
                        </span>
                      </DetailRow>
                      <DetailRow label={intl.formatMessage({ id: "tools.details.label.type" })}>
                        <span className="text-foreground">
                          {getIntegrationTypeLabel(selectedTool.integrationType)}
                        </span>
                      </DetailRow>
                      <DetailRow label={intl.formatMessage({ id: "tools.details.label.version" })}>
                        <span className="text-foreground">{selectedTool.version ?? 1}</span>
                      </DetailRow>
                      <DetailRow
                        label={intl.formatMessage({ id: "tools.details.label.requestType" })}
                      >
                        <span className="text-foreground">{selectedTool.requestType}</span>
                      </DetailRow>
                      {selectedTool.url && (
                        <DetailRow label={intl.formatMessage({ id: "tools.details.label.url" })}>
                          <CopyValue
                            label={intl.formatMessage({ id: "tools.details.label.url" })}
                            value={selectedTool.url}
                          />
                        </DetailRow>
                      )}
                      {(() => {
                        const tagLabels = (selectedTool.tags || []).map((tag) =>
                          typeof tag === "string" ? tag : tag.label,
                        );
                        return (
                          <InlineTagAdd
                            label={intl.formatMessage({ id: "tools.details.label.tags" })}
                            existingTags={tagLabels}
                            onAdd={
                              onAddTag
                                ? (newTags) => onAddTag(selectedTool.id, [...tagLabels, ...newTags])
                                : undefined
                            }
                          >
                            {tagLabels.map((label, index) => (
                              <Badge
                                key={`${label}-${index}`}
                                variant="outline"
                                className="rounded-full px-2 py-0 text-[11px] font-medium text-muted-foreground"
                              >
                                {label}
                              </Badge>
                            ))}
                          </InlineTagAdd>
                        );
                      })()}
                    </dl>
                  </div>

                  <div className="p-4">
                    <h3 className="mb-7 text-sm font-semibold text-foreground">
                      {intl.formatMessage({ id: "tools.details.activity" })}
                    </h3>
                    <dl className="space-y-4">
                      <DetailRow label={intl.formatMessage({ id: "tools.details.label.created" })}>
                        {formatDateTime(
                          selectedTool.createdAt,
                          intl.formatMessage({ id: "tools.details.notAvailable" }),
                        )}
                      </DetailRow>
                      <DetailRow
                        label={intl.formatMessage({ id: "tools.details.label.lastModified" })}
                      >
                        {formatDateTime(
                          selectedTool.updatedAt,
                          intl.formatMessage({ id: "tools.details.notAvailable" }),
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
