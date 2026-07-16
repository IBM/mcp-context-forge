import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  Activity,
  Globe,
  MessageSquareCode,
  PanelRightClose,
} from "lucide-react";
import { useIntl } from "react-intl";
import type { PromptRead } from "@/generated/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { InlineTagAdd } from "@/components/ui/inline-tag-add";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { getTagDisplay } from "@/components/gateways/utils";
import { formatDateTime } from "@/utils/format";

import { PromptCodeTab } from "./PromptCodeTab";
import { PromptDefinitionTable } from "./PromptDefinitionTable";

// Segmented-control styling for the Try it / Definition tab triggers.
const SEGMENTED_TRIGGER_CLASS =
  "rounded-md px-3 py-1 font-medium data-[state=active]:bg-background data-[state=active]:text-foreground data-[state=active]:shadow-sm";

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
  /**
   * Persists the prompt's full tag list after an inline add. Receives the prompt
   * ID and the new complete list of tag labels. When omitted, the tag row shows
   * a non-interactive "add" affordance.
   */
  onAddTag?: (promptId: string, tags: string[]) => Promise<void>;
  onEdit?: (prompt: NonNullable<PromptRead>) => void;
  onDelete?: (prompt: NonNullable<PromptRead>) => void;
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
  onAddTag,
  onEdit,
  onDelete,
}: PromptDetailsPanelProps) {
  const intl = useIntl();
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const [selectedId, setSelectedId] = useState<string | undefined>(
    initialPromptId ?? prompts[0]?.id,
  );
  const [activeTab, setActiveTab] = useState("tryIt");

  useEffect(() => {
    if (!open) return;
    setSelectedId(initialPromptId ?? prompts[0]?.id);
  }, [open, initialPromptId, prompts]);

  // Always land on "Try it" each time the panel opens, regardless of which tab
  // was active when it was last closed. Keyed on `open` only so a data refetch
  // while the panel is open doesn't yank the user off the Definition tab.
  useEffect(() => {
    if (open) setActiveTab("tryIt");
  }, [open]);

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
        inert={!open}
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
              {intl.formatMessage({ id: "prompts.details.srHeading" }, { title })}
            </h2>

            <div className="flex min-w-0 items-start gap-3">
              <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-sm bg-emerald-300 text-neutral-950">
                <MessageSquareCode className="size-4" />
              </span>
              <span aria-hidden="true" className="truncate text-xl font-semibold text-foreground">
                {title}
              </span>
            </div>

            {selected && (
              <p className="mt-7 max-w-4xl text-[15px] leading-6 text-muted-foreground">
                {selected.gatewayId || selected.gatewaySlug
                  ? intl.formatMessage({
                      id:
                        prompts.length === 1
                          ? "prompts.details.federatedSubheader.one"
                          : "prompts.details.federatedSubheader.other",
                    })
                  : intl.formatMessage(
                      { id: "prompts.details.localSubheader" },
                      {
                        visibility: (selected.visibility ?? "unknown").toLowerCase(),
                        argCount: (selected.arguments ?? []).filter(Boolean).length,
                      },
                    )}
              </p>
            )}

            <div className="my-8 h-px bg-border" />

            <Tabs value={activeTab} onValueChange={setActiveTab}>
              <TabsList className="inline-flex h-9 w-fit items-center gap-1 rounded-lg bg-muted p-1">
                <TabsTrigger value="tryIt" className={SEGMENTED_TRIGGER_CLASS}>
                  {intl.formatMessage({ id: "prompts.details.tab.tryIt" })}
                </TabsTrigger>
                <TabsTrigger value="definition" className={SEGMENTED_TRIGGER_CLASS}>
                  {intl.formatMessage({ id: "prompts.details.tab.definition" })}
                </TabsTrigger>
              </TabsList>

              <TabsContent value="tryIt" className="mt-8 space-y-6">
                <h3 className="text-sm font-semibold text-foreground">
                  {intl.formatMessage({ id: "prompts.details.promptPreview" })}
                </h3>

                {prompts.length > 1 && (
                  <div
                    className="flex flex-wrap gap-2"
                    role="group"
                    aria-label={intl.formatMessage({ id: "prompts.details.selectPrompt" })}
                  >
                    {prompts.map((p) => {
                      const isSelected = p.id === selected?.id;
                      return (
                        <Button
                          key={p.id}
                          type="button"
                          variant={isSelected ? "secondary" : "outline"}
                          size="sm"
                          aria-pressed={isSelected}
                          onClick={() => setSelectedId(p.id)}
                          className={cn(
                            "rounded-full font-mono text-[12px]",
                            isSelected
                              ? "border-transparent bg-muted text-foreground"
                              : "text-muted-foreground",
                          )}
                        >
                          {p.name}
                        </Button>
                      );
                    })}
                  </div>
                )}

                {selected?.description && (
                  <p className="max-w-4xl whitespace-normal break-words text-[13px] leading-4 text-muted-foreground">
                    {selected.description}
                  </p>
                )}

                {selected && <PromptCodeTab key={selected.id} prompt={selected} />}
              </TabsContent>

              <TabsContent value="definition" className="mt-8">
                <PromptDefinitionTable
                  prompts={prompts}
                  selectedPromptId={selected?.id}
                  onSelectPrompt={(p) => setSelectedId(p.id)}
                  onEdit={onEdit}
                  onDelete={onDelete}
                />
              </TabsContent>
            </Tabs>
          </div>

          <aside className="relative overflow-y-auto border-t border-border bg-background lg:border-l lg:border-t-0 dark:bg-neutral-900">
            <Button
              ref={closeButtonRef}
              type="button"
              variant="ghost"
              size="icon-xs"
              aria-label={intl.formatMessage({ id: "prompts.details.close" })}
              className="absolute right-3 top-3 text-muted-foreground"
              onClick={onClose}
            >
              <PanelRightClose className="size-4" />
            </Button>

            {selected && (
              <>
                <div className="border-b border-border p-4 pt-8">
                  <h3 className="mb-7 text-sm font-semibold text-foreground">
                    {intl.formatMessage({ id: "prompts.details.promptDetails" })}
                  </h3>

                  <dl className="space-y-4">
                    <DetailRow label={intl.formatMessage({ id: "prompts.details.label.status" })}>
                      <span className="flex items-center gap-2">
                        <Activity
                          className={`size-3.5 ${
                            selected.enabled ? "text-emerald-400" : "text-gray-400"
                          }`}
                        />
                        {selected.enabled
                          ? intl.formatMessage({ id: "prompts.details.status.active" })
                          : intl.formatMessage({ id: "prompts.details.status.inactive" })}
                      </span>
                    </DetailRow>
                    <DetailRow
                      label={intl.formatMessage({ id: "prompts.details.label.visibility" })}
                    >
                      <span className="flex items-center gap-2">
                        <Globe className="size-3.5 text-muted-foreground" />
                        {selected.visibility === "team"
                          ? intl.formatMessage({ id: "prompts.details.visibility.team" })
                          : selected.visibility === "public"
                            ? intl.formatMessage({ id: "prompts.details.visibility.public" })
                            : selected.visibility === "private"
                              ? intl.formatMessage({ id: "prompts.details.visibility.private" })
                              : intl.formatMessage({ id: "prompts.details.notAvailable" })}
                      </span>
                    </DetailRow>
                    {(() => {
                      const tagLabels = (selected.tags || []).map(
                        (tag, index) => getTagDisplay(tag, index).label,
                      );
                      return (
                        <InlineTagAdd
                          label="Tags"
                          existingTags={tagLabels}
                          onAdd={
                            onAddTag
                              ? (newTags) => onAddTag(selected.id, [...tagLabels, ...newTags])
                              : undefined
                          }
                        >
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
                        </InlineTagAdd>
                      );
                    })()}
                  </dl>
                </div>

                <div className="p-4">
                  <h3 className="mb-7 text-sm font-semibold text-foreground">
                    {intl.formatMessage({ id: "prompts.details.activity" })}
                  </h3>
                  <dl className="space-y-4">
                    <DetailRow label={intl.formatMessage({ id: "prompts.details.label.created" })}>
                      {formatDateTime(selected.createdAt)}
                    </DetailRow>
                    <DetailRow
                      label={intl.formatMessage({ id: "prompts.details.label.lastModified" })}
                    >
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
