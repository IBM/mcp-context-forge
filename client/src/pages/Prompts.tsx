import { useMemo, useState } from "react";
import { MessageSquareCode, MoreHorizontal, Plus } from "lucide-react";
import { useIntl } from "react-intl";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { CardTag } from "@/components/ui/card-tag";
import { Button } from "@/components/ui/button";
import { useQuery } from "@/hooks/useQuery";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { CursorPaginatedPromptsResponse, PromptRead } from "@/generated/types";
import type { PromptGroup } from "@/types/prompts";
import { PromptDetailsPanel } from "@/components/prompts";

const MAX_VISIBLE_PROMPTS = 8;

function getPromptItems(data: CursorPaginatedPromptsResponse): NonNullable<PromptRead>[] {
  return (data?.prompts ?? []).filter((p): p is NonNullable<PromptRead> => p !== null);
}

function getPromptLabel(prompt: NonNullable<PromptRead>): string {
  return prompt.displayName ?? prompt.originalName ?? prompt.name ?? "";
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

function PromptGroupCard({ group }: { group: PromptGroup<NonNullable<PromptRead>> }) {
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
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem>
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

function AddPromptsCard() {
  const intl = useIntl();

  return (
    <Card size="sm" className="cursor-pointer transition-opacity hover:opacity-90">
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
  const [open, setOpen] = useState(false);

  const {
    data: promptsData,
    error,
    isLoading,
  } = useQuery<CursorPaginatedPromptsResponse>("/prompts?limit=1000&include_inactive=true");

  const prompts = getPromptItems(promptsData ?? { prompts: [] });
  const restPromptsLabel = intl.formatMessage({ id: "prompts.restPromptsGroup" });
  const groups = useMemo(
    () => buildPromptGroups(prompts, restPromptsLabel),
    [prompts, restPromptsLabel],
  );

  return (
    <div className="p-6">
      <h1 className="mb-6 text-base font-semibold text-neutral-900 dark:text-white">
        {intl.formatMessage({ id: "prompts.title" })}
      </h1>

      {isLoading && (
        <div
          role="status"
          aria-live="polite"
          aria-busy="true"
          className="flex items-center justify-center p-12"
        >
          <span className="sr-only">{intl.formatMessage({ id: "prompts.loading" })}</span>
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
            {intl.formatMessage({ id: "prompts.error.loading" })}
          </h3>
          <p className="text-red-800 dark:text-red-200">{error.message}</p>
        </div>
      )}

      {!isLoading && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2 2xl:grid-cols-3">
          <AddPromptsCard />
          {groups.map((group) => (
            <PromptGroupCard key={group.key} group={group} />
          ))}
        </div>
      )}

      <div className="flex items-center gap-3">
        <Button
          type="button"
          onClick={() => setOpen(true)}
          disabled={isLoading || prompts.length === 0}
        >
          {isLoading
            ? "Loading prompts..."
            : prompts.length === 0
              ? "No prompts available"
              : "Open prompt details"}
        </Button>
        {error && (
          <p className="text-[12px] text-destructive">Failed to load prompts: {error.message}</p>
        )}
      </div>
      <PromptDetailsPanel prompts={prompts} open={open} onClose={() => setOpen(false)} />
    </div>
  );
}
