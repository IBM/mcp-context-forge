import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Activity, Globe, MessageSquareCode, PanelRightClose, Plus } from "lucide-react";

import type { PromptRead } from "@/generated/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { getTagDisplay } from "@/components/gateways/utils";
import { formatDateTime } from "@/utils/format";

import { PromptCodeTab } from "./PromptCodeTab";

function DetailRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[96px_minmax(0,1fr)] items-start gap-4">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-foreground">{children}</dd>
    </div>
  );
}

export interface PromptDetailsPanelProps {
  prompts: NonNullable<PromptRead>[];
  title: string;
  initialPromptId?: string;
  open: boolean;
  onClose: () => void;
}

/**
 * In-flow drawer that hosts a prompt picker (pill row) and the selected
 * prompt's Code tab. Shell mechanics (overlay, transform, focus trap, ESC,
 * focus restore) mirror `ToolDetailsPanel` so the drawer composes inside
 * AppShell's `relative overflow-hidden` content region.
 *
 * Scaffold for #5323: pill selector + Code tab wired. The kebab menu is a
 * placeholder for future per-prompt actions; the group/server context in the
 * header will populate from #5101's card metadata once integrated.
 */
export function PromptDetailsPanel({
  prompts,
  title,
  initialPromptId,
  open,
  onClose,
}: PromptDetailsPanelProps) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const [selectedId, setSelectedId] = useState<string | undefined>(
    initialPromptId ?? prompts[0]?.id,
  );

  useEffect(() => {
    if (!open) return;
    setSelectedId(initialPromptId ?? prompts[0]?.id);
  }, [open, initialPromptId, prompts]);

  const selected = useMemo(
    () => prompts.find((p) => p.id === selectedId) ?? prompts[0] ?? null,
    [prompts, selectedId],
  );

  const headingId = useMemo(
    () => `prompt-details-heading-${selected?.id ?? "none"}`,
    [selected?.id],
  );

  useEffect(() => {
    if (!open) return;
    previousFocusRef.current = (document.activeElement as HTMLElement | null) ?? null;
    closeButtonRef.current?.focus();
    return () => {
      previousFocusRef.current?.focus?.();
      previousFocusRef.current = null;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

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
        <div className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden lg:grid-cols-[minmax(0,1fr)_320px]">
          <div className="min-w-0 overflow-y-auto bg-background px-6 py-8 dark:bg-neutral-900 lg:px-12">
            <h2 id={headingId} className="sr-only">
              Prompt details: {title}
            </h2>

            <div className="flex items-start justify-between gap-4">
              <div className="flex min-w-0 items-start gap-3">
                <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-sm bg-emerald-300 text-neutral-950">
                  <MessageSquareCode className="size-4" />
                </span>
                <div className="min-w-0">
                  <div className="flex min-w-0 items-center gap-2">
                    <span
                      aria-hidden="true"
                      className="truncate text-xl font-semibold text-foreground"
                    >
                      {title}
                    </span>
                  </div>
                </div>
              </div>
            </div>

            {/* TODO(#5563): i18n pass and full local-prompt drawer variant (Try it / Definition tabs). */}
            {selected && (
              <p className="mt-7 max-w-4xl text-[15px] leading-6 text-muted-foreground">
                {selected.gatewayId || selected.gatewaySlug ? (
                  "Prompts added from connected MCP server"
                ) : (
                  <>
                    Local prompt
                    {" · "}
                    {(selected.visibility ?? "unknown").toLowerCase()}
                    {" · "}
                    {(selected.arguments ?? []).filter(Boolean).length}{" "}
                    {(selected.arguments ?? []).filter(Boolean).length === 1
                      ? "argument"
                      : "arguments"}
                  </>
                )}
              </p>
            )}

            <div className="my-8 h-px bg-border" />

            <div className="flex items-center justify-between gap-4">
              <h3 className="text-sm font-semibold text-foreground">Prompt preview</h3>
            </div>

            {prompts.length > 0 && (
              <div className="mt-8 flex flex-wrap gap-2" role="tablist" aria-label="Select prompt">
                {prompts.map((p) => {
                  const isSelected = p.id === selected?.id;
                  return (
                    <button
                      key={p.id}
                      type="button"
                      role="tab"
                      aria-selected={isSelected}
                      onClick={() => setSelectedId(p.id)}
                      className={cn(
                        "rounded-full border px-3 py-1.5 font-mono text-[12px] transition-colors",
                        isSelected
                          ? "border-transparent bg-muted text-foreground"
                          : "border-border bg-transparent text-muted-foreground hover:bg-muted/50 hover:text-foreground",
                      )}
                    >
                      {p.name}
                    </button>
                  );
                })}
              </div>
            )}

            {selected?.description && (
              <p className="mt-4 max-w-4xl whitespace-normal break-words text-[13px] leading-4 text-[color:var(--placeholder-foreground)]">
                {selected.description}
              </p>
            )}

            <div className="mt-6">
              {selected && <PromptCodeTab key={selected.id} prompt={selected} />}
            </div>
          </div>

          <aside className="relative overflow-y-auto border-t border-border bg-background lg:border-l lg:border-t-0 dark:bg-neutral-900">
            <Button
              ref={closeButtonRef}
              type="button"
              variant="ghost"
              size="icon-xs"
              aria-label="Close prompt details"
              className="absolute right-3 top-3 text-muted-foreground"
              onClick={onClose}
            >
              <PanelRightClose className="size-4" />
            </Button>

            {selected && (
              <>
                <div className="border-b border-border p-4 pt-8">
                  <h3 className="mb-7 text-sm font-semibold text-foreground">Prompt details</h3>

                  <dl className="space-y-4">
                    <DetailRow label="Status">
                      <span className="flex items-center gap-2">
                        <Activity
                          className={`size-3.5 ${
                            selected.enabled ? "text-emerald-400" : "text-gray-400"
                          }`}
                        />
                        {selected.enabled ? "Active" : "Inactive"}
                      </span>
                    </DetailRow>
                    <DetailRow label="Visibility">
                      <span className="flex items-center gap-2">
                        <Globe className="size-3.5 text-muted-foreground" />
                        {selected.visibility
                          ? selected.visibility.charAt(0).toUpperCase() +
                            selected.visibility.slice(1)
                          : "Not available"}
                      </span>
                    </DetailRow>
                    <DetailRow label="Tags">
                      <div className="flex min-w-0 flex-wrap items-center gap-2">
                        {(selected.tags || []).map((tag, index) => {
                          const { key, label } = getTagDisplay(tag, index);
                          return (
                            <Badge
                              key={key}
                              variant="outline"
                              className="rounded-full px-2 py-0 text-[11px] font-medium text-muted-foreground"
                            >
                              {label}
                            </Badge>
                          );
                        })}
                        <button
                          type="button"
                          tabIndex={-1}
                          aria-hidden="true"
                          className="flex items-center gap-1 text-[12px] text-muted-foreground hover:text-foreground"
                        >
                          <Plus className="size-3" aria-hidden="true" />
                          add
                        </button>
                      </div>
                    </DetailRow>
                  </dl>
                </div>

                <div className="p-4">
                  <h3 className="mb-7 text-sm font-semibold text-foreground">Activity</h3>
                  <dl className="space-y-4">
                    <DetailRow label="Created">{formatDateTime(selected.createdAt)}</DetailRow>
                    <DetailRow label="Last modified">
                      {formatDateTime(selected.updatedAt)}
                    </DetailRow>
                  </dl>
                </div>
              </>
            )}
          </aside>
        </div>
      </aside>
    </>
  );
}
