import { MessageSquareCode, MoreHorizontal, Plus } from "lucide-react";
import { useIntl } from "react-intl";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useQuery } from "@/hooks/useQuery";
import { useRouter } from "@/router";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { Prompt, PromptsResponse } from "@/types/prompts";

export function Prompts() {
  const intl = useIntl();
  const { navigate } = useRouter();
  const {
    data: promptsData,
    error,
    isLoading,
  } = useQuery<PromptsResponse>("/prompts?limit=1000&include_inactive=true");

  const getPromptItems = (data: PromptsResponse): Prompt[] => {
    if (Array.isArray(data)) return data;
    return data?.prompts ?? [];
  };

  const getPromptLabel = (prompt: Prompt): string =>
    prompt.displayName || prompt.originalName || prompt.name;

  const getPromptDescription = (prompt: Prompt): string | null => {
    const description = prompt.description;
    if (!description || description.trim() === "" || description.trim().toLowerCase() === "none") {
      return null;
    }
    return description;
  };

  const promptItems = getPromptItems(promptsData ?? []);

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
          <Card
            size="sm"
            role="button"
            tabIndex={0}
            aria-label={intl.formatMessage({ id: "prompts.add.title" })}
            className="cursor-pointer transition-opacity hover:opacity-90"
            onClick={() => navigate("/app/prompts/add")}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                navigate("/app/prompts/add");
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

          {promptItems.map((prompt) => {
            const description = getPromptDescription(prompt);
            const promptBadges = [
              ...(prompt.tags ?? []).map((tag) => ({ id: `tag-${tag.id}`, label: tag.label })),
              ...(prompt.arguments ?? []).map((argument) => ({
                id: `argument-${argument.name}`,
                label: argument.name,
              })),
            ];

            return (
              <Card key={prompt.id} size="sm">
                <CardHeader>
                  <div className="flex items-center gap-3">
                    <div className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded bg-prompt-icon-bg">
                      <MessageSquareCode className="h-3.5 w-3.5 text-black" />
                    </div>

                    <div className="flex min-w-0 flex-1 items-center gap-2">
                      <span className="truncate text-sm font-semibold text-neutral-500 dark:text-neutral-400">
                        {getPromptLabel(prompt)}
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
                            { name: getPromptLabel(prompt) },
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

                {(description || promptBadges.length > 0) && (
                  <CardContent>
                    {description && (
                      <p className="mb-3 line-clamp-2 text-sm leading-relaxed text-neutral-500 dark:text-neutral-400">
                        {description}
                      </p>
                    )}
                    {promptBadges.length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {promptBadges.map((badge) => (
                          <span
                            key={badge.id}
                            className="inline-flex items-center rounded bg-tool-badge-bg px-1.5 py-1 text-[10px] font-medium leading-none text-tool-badge-fg"
                          >
                            {badge.label}
                          </span>
                        ))}
                      </div>
                    )}
                  </CardContent>
                )}
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
