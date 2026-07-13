import { useEffect, useMemo, useRef, useState, type Ref } from "react";
import { MessageSquareCode, MoreHorizontal, Plus } from "lucide-react";
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
import { useQuery } from "@/hooks/useQuery";
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
    const slug = prompt.gatewaySlug?.trim();
    // Namespace the map key so gateway-less prompts (keyed "rest") can never
    // merge into a real gateway whose slug happens to equal the localized
    // "REST prompts" label. `label` stays purely for display.
    const key = slug ? `gateway:${slug}` : "rest";
    let group = map.get(key);
    if (!group) {
      group = {
        key,
        label: slug || restPromptsLabel,
        gatewayId: prompt.gatewayId,
        prompts: [],
      };
      map.set(key, group);
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
  const addPromptsCardRef = useRef<HTMLDivElement>(null);
  const [showForm, setShowForm] = useState(false);
  const [shouldRestoreFormCloseFocus, setShouldRestoreFormCloseFocus] = useState(false);
  const {
    data: promptsData,
    error,
    isLoading,
    refetch,
  } = useQuery<PromptsResponse>("/prompts?limit=1000&include_inactive=true");

  const restPromptsLabel = intl.formatMessage({ id: "prompts.restPromptsGroup" });
  const groups = useMemo(
    () => buildPromptGroups(getPromptItems(promptsData ?? []), restPromptsLabel),
    [promptsData, restPromptsLabel],
  );

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

  return (
    <div className="p-6">
      {showForm ? (
        <PromptForm isOpen={showForm} onToggle={handleFormCancel} onSuccess={handleFormSuccess} />
      ) : (
        <>
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
              <AddPromptsCard onActivate={handleAddPrompt} cardRef={addPromptsCardRef} />
              {groups.map((group) => (
                <PromptGroupCard key={group.key} group={group} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
