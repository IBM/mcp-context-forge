import { useCallback, useEffect, useMemo, useRef, useState, type Ref } from "react";
import { MessageSquareCode, MoreVertical, Plus } from "lucide-react";
import { useIntl } from "react-intl";
import { PromptForm } from "@/components/prompts/PromptForm";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { CardTag } from "@/components/ui/card-tag";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { CursorPaginatedPromptsResponse, PromptRead } from "@/generated/types";
import { PromptDetailsPanel } from "@/components/prompts";
import { ConfirmDialog } from "@/components/servers/ConfirmDialog";
import { useQuery } from "@/hooks/useQuery";
import { promptsApi } from "@/api/prompts";
import { ApiError } from "@/api/client";
import { extractApiErrorDetail, sanitizeError } from "@/utils/errors";
import { parseApiError } from "@/lib/errorUtils";
import { toast } from "sonner";
import type { PromptGroup } from "@/types/prompts";

const MAX_VISIBLE_PROMPTS = 8;

type PromptsListResponse = (PromptRead | null)[] | CursorPaginatedPromptsResponse;

function getPromptItems(data: PromptsListResponse | undefined): NonNullable<PromptRead>[] {
  const list = Array.isArray(data) ? data : (data?.prompts ?? []);
  return list.filter((p): p is NonNullable<PromptRead> => p != null);
}

function getPromptLabel(prompt: NonNullable<PromptRead>): string {
  return prompt.displayName || prompt.originalName || prompt.name || "";
}

function getPromptDescription(prompt: NonNullable<PromptRead>): string | null {
  const description = prompt.description;
  if (!description || description.trim() === "" || description.trim().toLowerCase() === "none") {
    return null;
  }
  return description;
}

// Group prompts sourced from the same MCP server (gateway) into a single card,
// mirroring how the Tools page groups tools. Prompts without a gateway (local
// templates) are collapsed into a single "REST prompts" card, matching the
// "REST tools" grouping on the Tools page.
function buildPromptGroups(
  prompts: NonNullable<PromptRead>[],
  restPromptsLabel: string,
): PromptGroup<NonNullable<PromptRead>>[] {
  const map = new Map<string, PromptGroup<NonNullable<PromptRead>>>();

  for (const prompt of prompts) {
    const slug = prompt.gatewaySlug?.trim();
    // Namespace the map key so gateway-less prompts (keyed "rest") can never
    // merge into a real gateway whose slug happens to equal the localized
    // "REST prompts" label. `label` stays purely for display.
    const key = slug ? `gateway:${slug}` : "rest";
    const existing = map.get(key);
    if (!existing) {
      map.set(key, {
        key,
        label: slug || restPromptsLabel,
        gatewayId: prompt.gatewayId,
        prompts: [prompt],
      });
    } else {
      existing.prompts.push(prompt);
    }
  }

  return Array.from(map.values());
}

function PromptGroupCard({
  group,
  onViewDetails,
}: {
  group: PromptGroup<NonNullable<PromptRead>>;
  onViewDetails: (group: PromptGroup<NonNullable<PromptRead>>) => void;
}) {
  const intl = useIntl();
  const visiblePrompts = group.prompts.slice(0, MAX_VISIBLE_PROMPTS);
  const remainingCount = group.prompts.length - MAX_VISIBLE_PROMPTS;

  return (
    <Card size="sm">
      <CardHeader>
        <div className="flex items-center gap-3">
          <div className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded bg-prompt-icon-bg">
            <MessageSquareCode className="h-3.5 w-3.5 text-black" />
          </div>

          <div className="flex min-w-0 flex-1 items-center gap-2">
            <span className="truncate text-sm font-semibold text-neutral-500 dark:text-neutral-400">
              {group.label}
            </span>
          </div>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-label={intl.formatMessage(
                  { id: "prompts.card.moreOptionsFor" },
                  { name: group.label },
                )}
                className="h-7 w-7 p-0"
              >
                <MoreVertical className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => onViewDetails(group)}>
                {intl.formatMessage({ id: "prompts.card.viewDetails" })}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </CardHeader>

      <CardContent>
        <div className="flex flex-wrap gap-1">
          {visiblePrompts.map((prompt: NonNullable<PromptRead>) => (
            <CardTag key={prompt.id} tooltip={getPromptDescription(prompt)}>
              {getPromptLabel(prompt)}
            </CardTag>
          ))}
          {remainingCount > 0 && (
            <CardTag
              tooltip={intl.formatMessage(
                { id: "prompts.card.morePromptsTitle" },
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
}

function AddPromptsCard({
  onActivate,
  cardRef,
}: {
  onActivate: () => void;
  cardRef?: Ref<HTMLDivElement>;
}) {
  const intl = useIntl();

  return (
    <Card
      ref={cardRef}
      size="sm"
      role="button"
      tabIndex={0}
      aria-label={intl.formatMessage({ id: "prompts.add.title" })}
      className="cursor-pointer transition-opacity hover:opacity-90"
      onClick={onActivate}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onActivate();
        }
      }}
    >
      <CardHeader>
        <div className="flex items-center gap-3">
          <div className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded bg-tool-add-icon-bg shadow-sm">
            <Plus className="h-3.5 w-3.5 text-tool-add-icon-fg" />
          </div>
          <span className="text-sm font-semibold text-neutral-900 dark:text-white">
            {intl.formatMessage({ id: "prompts.add.title" })}
          </span>
        </div>
      </CardHeader>
      <CardContent>
        <p className="text-sm leading-relaxed text-neutral-500 dark:text-neutral-400">
          {intl.formatMessage({ id: "prompts.add.description" })}
        </p>
      </CardContent>
    </Card>
  );
}

export function Prompts() {
  const intl = useIntl();
  const [activeGroup, setActiveGroup] = useState<PromptGroup<NonNullable<PromptRead>> | null>(null);
  // Keep the last-shown group populated through the drawer's slide-out
  // transition; clearing `activeGroup` immediately would otherwise blank the
  // drawer body before the exit animation finishes.
  const [displayGroup, setDisplayGroup] = useState<PromptGroup<NonNullable<PromptRead>> | null>(
    null,
  );

  const addPromptsCardRef = useRef<HTMLDivElement>(null);
  const [showForm, setShowForm] = useState(false);
  const [shouldRestoreFormCloseFocus, setShouldRestoreFormCloseFocus] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [promptToDelete, setPromptToDelete] = useState<NonNullable<PromptRead> | null>(null);
  const {
    data: promptsData,
    error,
    isLoading,
    refetch,
    setData: setPromptsData,
  } = useQuery<PromptsListResponse>("/prompts?limit=1000&include_inactive=true");

  const handleAddPromptTag = useCallback(
    async (promptId: string, tags: string[]) => {
      try {
        const updated = await promptsApi.updateTags(promptId, tags);
        if (!updated) return;
        // Patch the single prompt in place instead of refetching the whole
        // catalog, which can be expensive with many prompts on the backend.
        setPromptsData((prev) => {
          if (!prev) return prev;
          const replace = (list: (PromptRead | null)[]) =>
            list.map((p) => (p && p.id === promptId ? updated : p));
          return Array.isArray(prev) ? replace(prev) : { ...prev, prompts: replace(prev.prompts) };
        });
      } catch (err) {
        const detail = err instanceof ApiError ? extractApiErrorDetail(err.body) : null;
        toast.error(detail || intl.formatMessage({ id: "prompts.tags.addError" }));
        throw err;
      }
    },
    [setPromptsData, intl],
  );

  const restPromptsLabel = intl.formatMessage({ id: "prompts.restPromptsGroup" });
  const groups = useMemo(
    () => buildPromptGroups(getPromptItems(promptsData), restPromptsLabel),
    [promptsData, restPromptsLabel],
  );

  // Keep the drawer's group in sync with the latest data: re-resolve the active
  // group from `groups` by key so edits (e.g. adding tags) show immediately.
  // When the drawer closes (`activeGroup` becomes null) we leave `displayGroup`
  // untouched so its content stays put through the slide-out animation.
  useEffect(() => {
    if (!activeGroup) return;
    const fresh = groups.find((g) => g.key === activeGroup.key) ?? activeGroup;
    setDisplayGroup(fresh);
  }, [activeGroup, groups]);

  useEffect(() => {
    if (!showForm && shouldRestoreFormCloseFocus) {
      addPromptsCardRef.current?.focus();
      setShouldRestoreFormCloseFocus(false);
    }
  }, [showForm, shouldRestoreFormCloseFocus]);

  const handleAddPrompt = () => {
    setShouldRestoreFormCloseFocus(false);
    setShowForm(true);
  };

  const handleFormCancel = () => {
    setShouldRestoreFormCloseFocus(true);
    setShowForm(false);
  };

  const handleFormSuccess = async () => {
    setShouldRestoreFormCloseFocus(true);
    setShowForm(false);
    await refetch();
  };

  // TODO: placeholder handler so the details-panel Definition table shows its
  // row overflow menu. No behaviour yet — a follow-up PR adds PromptForm edit
  // mode.
  const handleEditPrompt = () => {
    // TODO: open PromptForm in edit mode for the selected prompt
  };

  const handleDeletePrompt = useCallback((prompt: NonNullable<PromptRead>) => {
    setPromptToDelete(prompt);
    setDeleteDialogOpen(true);
  }, []);

  const confirmDeletePrompt = useCallback(async () => {
    if (!promptToDelete) return;

    const prompt = promptToDelete;
    const name = getPromptLabel(prompt) || prompt.id;

    // Snapshot the list and the open group so we can roll back the optimistic
    // removal if the DELETE fails, mirroring the Tools page delete flow.
    const previousData = promptsData;
    const previousActiveGroup = activeGroup;

    const removeFromList = (list: (PromptRead | null)[]) =>
      list.filter((p) => p == null || p.id !== prompt.id);
    setPromptsData((prev) => {
      if (!prev) return prev;
      return Array.isArray(prev)
        ? removeFromList(prev)
        : { ...prev, prompts: removeFromList(prev.prompts) };
    });

    // Keep the open drawer's group in sync with the removal: drop the prompt
    // from its list, and close the drawer once the group is empty. Recomputing
    // from the current `activeGroup` (rather than checking a frozen snapshot)
    // keeps sequential deletes from the same group correct.
    if (activeGroup) {
      const remaining = activeGroup.prompts.filter((p) => p.id !== prompt.id);
      setActiveGroup(remaining.length > 0 ? { ...activeGroup, prompts: remaining } : null);
    }

    setDeleteDialogOpen(false);
    setPromptToDelete(null);

    try {
      await promptsApi.delete(prompt.id);
      toast.success(intl.formatMessage({ id: "prompts.delete.success" }, { name }));

      try {
        await refetch();
      } catch (refreshErr) {
        console.error("Failed to refresh prompts after deletion:", sanitizeError(refreshErr));
      }
    } catch (err) {
      // Restore the pre-delete list and reopen the group on failure.
      setPromptsData(() => previousData);
      setActiveGroup(previousActiveGroup);

      // Surface the backend detail when present, otherwise the localized fallback.
      toast.error(parseApiError(err, intl.formatMessage({ id: "prompts.delete.error" })));
    }
  }, [promptToDelete, promptsData, activeGroup, setPromptsData, refetch, intl]);

  return (
    <div className="p-6">
      {showForm ? (
        <PromptForm isOpen={showForm} onToggle={handleFormCancel} onSuccess={handleFormSuccess} />
      ) : (
        <>
          <h1 className="mb-6 text-base font-semibold text-neutral-900 dark:text-white">
            {intl.formatMessage({ id: "prompts.title" })}
          </h1>

          {isLoading ? (
            <div
              role="status"
              aria-live="polite"
              aria-busy="true"
              className="flex items-center justify-center p-12"
            >
              <span className="sr-only">{intl.formatMessage({ id: "prompts.loading" })}</span>
              <div className="h-8 w-8 animate-spin rounded-full border-4 border-gray-200 border-t-blue-600 dark:border-gray-700 dark:border-t-blue-400" />
            </div>
          ) : (
            <>
              <div className="grid grid-cols-1 gap-6 lg:grid-cols-2 2xl:grid-cols-3">
                <AddPromptsCard onActivate={handleAddPrompt} cardRef={addPromptsCardRef} />
                {groups.map((group) => (
                  <PromptGroupCard key={group.key} group={group} onViewDetails={setActiveGroup} />
                ))}
              </div>
              {error && (
                <div
                  className="mb-6 rounded-lg border border-red-200 bg-red-50 p-4 dark:border-red-800 dark:bg-red-900/20"
                  role="alert"
                  aria-live="assertive"
                >
                  <h3 className="mb-1 font-semibold">
                    {intl.formatMessage({ id: "prompts.error.loading" })}
                  </h3>
                  <p className="text-red-800 dark:text-red-200">{error.message}</p>
                </div>
              )}
            </>
          )}
        </>
      )}

      <PromptDetailsPanel
        prompts={displayGroup?.prompts ?? []}
        title={displayGroup?.label ?? ""}
        open={activeGroup !== null}
        onClose={() => setActiveGroup(null)}
        onAddTag={handleAddPromptTag}
        onEdit={handleEditPrompt}
        onDelete={handleDeletePrompt}
      />

      <ConfirmDialog
        open={deleteDialogOpen}
        onOpenChange={setDeleteDialogOpen}
        onConfirm={confirmDeletePrompt}
        title={intl.formatMessage({ id: "prompts.delete.confirm.title" })}
        description={intl.formatMessage(
          { id: "prompts.delete.confirm.description" },
          { name: promptToDelete ? getPromptLabel(promptToDelete) || promptToDelete.id : "" },
        )}
        confirmLabel={intl.formatMessage({ id: "prompts.delete.confirm.button" })}
        variant="destructive"
      />
    </div>
  );
}
