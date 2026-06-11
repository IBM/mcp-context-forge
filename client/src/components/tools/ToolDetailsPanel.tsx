import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Activity, Copy, Globe, PanelRightClose, Plus, Wrench } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { Tool } from "@/types/tool";
import { copyToClipboard, truncateMiddle } from "@/components/gateways/utils";
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
  return (
    <div className="flex min-w-0 items-center gap-2">
      <span className="min-w-0 flex-1 truncate font-mono text-[12px]">{truncateMiddle(value)}</span>
      <Button
        type="button"
        variant="ghost"
        size="icon-xs"
        className="size-5 text-muted-foreground"
        aria-label={`Copy ${label}`}
        onClick={() => copyToClipboard(value)}
      >
        <Copy className="size-3.5" />
      </Button>
    </div>
  );
}

function formatDateTime(value?: string, emptyLabel = "Not available") {
  if (!value) return emptyLabel;
  // Strip milliseconds and trailing timezone marker to match ISO display style
  return value.replace(/\.\d+Z?$/, "");
}

export function ToolDetailsPanel({
  tools,
  gatewaySlug,
  open,
  onClose,
}: {
  tools: Tool[];
  gatewaySlug: string;
  open: boolean;
  onClose: () => void;
}) {
  const [selectedTool, setSelectedTool] = useState<Tool | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const headingId = useMemo(() => `tool-details-heading-${gatewaySlug}`, [gatewaySlug]);

  // Select first tool when panel opens or tools change
  useEffect(() => {
    if (open && tools.length > 0 && !selectedTool) {
      setSelectedTool(tools[0]);
    }
  }, [open, tools, selectedTool]);

  // Reset selected tool when panel closes
  useEffect(() => {
    if (!open) {
      setSelectedTool(null);
    }
  }, [open]);

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

  const getVisibilityLabel = useCallback((value?: string) => {
    if (value === "team") return "Team";
    if (value === "public") return "Public";
    if (value === "private") return "Private";
    return "Not available";
  }, []);

  const getIntegrationTypeLabel = useCallback((type?: string) => {
    if (type === "MCP") return "MCP Server";
    if (type === "REST") return "REST API tools";
    if (type === "GRPC") return "gRPC Service";
    return type ?? "Not available";
  }, []);

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
        {tools.length > 0 && (
          <div className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden lg:grid-cols-[minmax(0,1fr)_320px]">
            <div className="min-w-0 overflow-y-auto bg-background px-6 py-8 lg:px-12 dark:bg-neutral-900">
              <h2 id={headingId} className="sr-only">
                Tools for {gatewaySlug}
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
              />
            </div>

            <aside className="relative border-t border-border bg-background lg:border-l lg:border-t-0">
              <Button
                ref={closeButtonRef}
                type="button"
                variant="ghost"
                size="icon-xs"
                aria-label="Close tool details"
                className="absolute right-3 top-3 text-muted-foreground"
                onClick={onClose}
              >
                <PanelRightClose className="size-4" />
              </Button>

              {selectedTool && (
                <>
                  <div className="border-b border-border p-4 pt-8">
                    <h3 className="mb-7 text-sm font-semibold text-foreground">
                      Component details
                    </h3>

                    <dl className="space-y-4">
                      <DetailRow label="Status">
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
                              ? "Active"
                              : "Unreachable"
                            : "Inactive"}
                        </span>
                      </DetailRow>
                      <DetailRow label="Visibility">
                        <span className="flex items-center gap-2">
                          <Globe className="size-3.5 text-muted-foreground" />
                          {getVisibilityLabel(selectedTool.visibility)}
                        </span>
                      </DetailRow>
                      <DetailRow label="Type">
                        <span className="text-foreground">
                          {getIntegrationTypeLabel(selectedTool.integrationType)}
                        </span>
                      </DetailRow>
                      <DetailRow label="Version">
                        <span className="text-foreground">{selectedTool.version ?? 1}</span>
                      </DetailRow>
                      <DetailRow label="Request type">
                        <span className="text-foreground">{selectedTool.requestType}</span>
                      </DetailRow>
                      {selectedTool.url && (
                        <DetailRow label="URL">
                          <CopyValue label="URL" value={selectedTool.url} />
                        </DetailRow>
                      )}
                      <DetailRow label="Tags" className="items-center">
                        <div className="flex min-w-0 flex-wrap items-center gap-2">
                          {(selectedTool.tags || []).length > 0 ? (
                            <>
                              {(selectedTool.tags || []).map((tag, index) => (
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
                                add
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
                              add
                            </button>
                          )}
                        </div>
                      </DetailRow>
                    </dl>
                  </div>

                  <div className="p-4">
                    <h3 className="mb-7 text-sm font-semibold text-foreground">Activity</h3>
                    <dl className="space-y-4">
                      <DetailRow label="Created">
                        {formatDateTime(selectedTool.createdAt)}
                      </DetailRow>
                      <DetailRow label="Last modified">
                        {formatDateTime(selectedTool.updatedAt)}
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
