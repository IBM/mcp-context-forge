import { useMemo } from "react";
import { MessageSquareCode, MoreHorizontal, Plus } from "lucide-react";
import { useIntl } from "react-intl";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useQuery } from "@/hooks/useQuery";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { Prompt, PromptGroup, PromptsResponse } from "@/types/prompts";

const MAX_VISIBLE_PROMPTS = 8;

function getPromptItems(data: PromptsResponse): Prompt[] {
  if (Array.isArray(data)) return data;
  return data?.prompts ?? [];
}

function getPromptLabel(prompt: Prompt): string {
  return prompt.displayName || prompt.originalName || prompt.name;
}

function getPromptDescription(prompt: Prompt): string | null {
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
function buildPromptGroups(prompts: Prompt[], restPromptsLabel: string): PromptGroup[] {
  const map = new Map<string, PromptGroup>();

  for (const prompt of prompts) {
    const slug = prompt.gatewaySlug?.trim() || restPromptsLabel;
    let group = map.get(slug);
    if (!group) {
      group = {
        key: slug,
        label: slug,
        gatewayId: prompt.gatewayId,
        prompts: [],
      };
      map.set(slug, group);
    }
    group.prompts.push(prompt);
  }

  return Array.from(map.values());
}

function PromptGroupCard({ group }: { group: PromptGroup }) {
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
          {visiblePrompts.map((prompt) => (
            <span
              key={prompt.id}
              className="inline-flex items-center rounded bg-tool-badge-bg px-1.5 py-1 text-[10px] font-medium leading-none text-white"
              title={getPromptDescription(prompt) ?? undefined}
            >
              {getPromptLabel(prompt)}
            </span>
          ))}
          {remainingCount > 0 && (
            <span
              className="inline-flex items-center rounded bg-tool-badge-bg px-1.5 py-1 text-[10px] font-medium leading-none text-white"
              title={intl.formatMessage(
                { id: "prompts.card.morePromptsTitle" },
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
  const {
    data: promptsData,
    error,
    isLoading,
  } = useQuery<PromptsResponse>("/prompts?limit=1000&include_inactive=true");

  const restPromptsLabel = intl.formatMessage({ id: "prompts.restPromptsGroup" });
  const groups = useMemo(
    () => buildPromptGroups(getPromptItems(promptsData ?? []), restPromptsLabel),
    [promptsData, restPromptsLabel],
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
    </div>
  );
}
