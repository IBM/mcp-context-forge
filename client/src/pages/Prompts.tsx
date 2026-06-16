import { Plus, Globe, Lock, Shield, Activity, CircleDashed, MoreVertical } from "lucide-react";
import { PromptIcon } from "@/components/icons/PromptIcon";
import { MCPIcon } from "@/components/icons/MCPIcon";
import { Button } from "@/components/ui/button";
import { useRouter } from "@/router";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useState, useEffect, useCallback } from "react";
import {
  promptsApi,
  type PaginatedResponse,
  type Prompt as ApiPrompt,
  type PromptArgument,
} from "@/api/prompts";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const DEFAULT_PAGE_SIZE = 10;
const CREATE_PROMPT_PATH = "/app/prompts/create";

interface PromptListItem {
  id: string;
  name: string;
  displayName: string | null;
  description: string | null;
  arguments: PromptArgument[];
  gatewaySlug: string | null;
  visibility: ApiPrompt["visibility"];
  enabled: boolean;
}

function toPromptListItem(prompt: ApiPrompt): PromptListItem {
  return {
    id: prompt.id,
    name: prompt.name,
    displayName: prompt.displayName,
    description: prompt.description,
    arguments: prompt.arguments,
    gatewaySlug: prompt.gatewaySlug,
    visibility: prompt.visibility,
    enabled: prompt.enabled,
  };
}

function getVisibilityConfig(visibility: PromptListItem["visibility"]) {
  switch (visibility) {
    case "private":
      return { label: "Private", Icon: Lock };
    case "team":
      return { label: "Team", Icon: Shield };
    default:
      return { label: "Public", Icon: Globe };
  }
}

function PromptsTable({ prompts }: { prompts: PromptListItem[] }) {
  return (
    <div className="overflow-hidden bg-white dark:bg-neutral-950/60">
      <Table className="min-w-full border-separate border-spacing-y-1.5">
        <TableCaption className="sr-only">List of prompts with status and actions</TableCaption>
        <TableHeader className="bg-white dark:bg-transparent">
          <TableRow className="border-none hover:bg-transparent">
            <TableHead className="h-12 px-4 text-xs font-medium text-neutral-600 dark:text-neutral-400">
              Name
            </TableHead>
            <TableHead className="h-12 px-4 text-xs font-medium text-neutral-600 dark:text-neutral-400">
              Description
            </TableHead>
            <TableHead className="h-12 px-4 text-xs font-medium text-neutral-600 dark:text-neutral-400">
              Arguments
            </TableHead>
            <TableHead className="h-12 px-4 text-xs font-medium text-neutral-600 dark:text-neutral-400">
              Gateway
            </TableHead>
            <TableHead className="h-12 px-4 text-xs font-medium text-neutral-600 dark:text-neutral-400">
              Visibility
            </TableHead>
            <TableHead className="h-12 px-4 text-xs font-medium text-neutral-600 dark:text-neutral-400">
              Status
            </TableHead>
            <TableHead className="h-12 px-4 text-xs font-medium text-neutral-600 dark:text-neutral-400 text-right">
              Actions
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {prompts.map((prompt) => {
            const visibility = getVisibilityConfig(prompt.visibility);
            const VisibilityIcon = visibility.Icon;
            const StatusIcon = prompt.enabled ? Activity : CircleDashed;
            const statusLabel = prompt.enabled ? "Active" : "Disabled";
            const statusClass = prompt.enabled ? "text-emerald-400" : "text-neutral-500";

            return (
              <TableRow
                key={prompt.id}
                className="bg-neutral-50 dark:bg-neutral-800 hover:bg-neutral-100 dark:hover:bg-neutral-700/60 [&>td:first-child]:rounded-l-lg [&>td:last-child]:rounded-r-lg"
              >
                <TableCell className="px-4 py-2.5">
                  <div className="flex items-center gap-3">
                    <div className="flex size-6 shrink-0 items-center justify-center rounded-sm bg-indigo-100 dark:bg-indigo-900/40">
                      <PromptIcon className="size-3.5 text-indigo-600 dark:text-indigo-400" />
                    </div>
                    <span className="font-medium text-neutral-900 dark:text-neutral-100">
                      {prompt.displayName ?? prompt.name}
                    </span>
                  </div>
                </TableCell>
                <TableCell className="px-4 py-2.5 max-w-[220px]">
                  <span className="text-xs text-neutral-600 dark:text-neutral-400 line-clamp-2">
                    {prompt.description ?? "—"}
                  </span>
                </TableCell>
                <TableCell className="px-4 py-2.5">
                  <div className="flex flex-wrap items-center gap-1">
                    {prompt.arguments.map((arg) => (
                      <span
                        key={arg.name}
                        className="inline-flex items-center rounded bg-neutral-100 px-1.5 py-0.5 text-[10px] font-medium leading-none text-neutral-600 dark:bg-neutral-700 dark:text-neutral-400"
                      >
                        {arg.name}
                      </span>
                    ))}
                  </div>
                </TableCell>
                <TableCell className="px-4 py-2.5 text-xs text-neutral-600 dark:text-neutral-400">
                  {prompt.gatewaySlug ?? <span className="italic">Local</span>}
                </TableCell>
                <TableCell className="px-4 py-2.5">
                  <div className="inline-flex items-center gap-1.5 text-xs text-neutral-600 dark:text-neutral-400">
                    <VisibilityIcon className="h-3.5 w-3.5" aria-hidden="true" />
                    <span>{visibility.label}</span>
                  </div>
                </TableCell>
                <TableCell className="px-4 py-2.5">
                  <div className={`inline-flex items-center gap-1.5 text-xs ${statusClass}`}>
                    <StatusIcon className="h-3.5 w-3.5" />
                    <span className="text-neutral-600 dark:text-neutral-400">{statusLabel}</span>
                  </div>
                </TableCell>
                <TableCell className="px-4 py-2.5 text-right">
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-8 w-8 p-0"
                        aria-label={`Actions for ${prompt.displayName ?? prompt.name}`}
                        aria-haspopup="menu"
                      >
                        <MoreVertical className="h-4 w-4" aria-hidden="true" />
                        <span className="sr-only">
                          Open menu for {prompt.displayName ?? prompt.name}
                        </span>
                      </Button>
                    </DropdownMenuTrigger>
                    {/* TODO: add all actions to action menu */}
                    <DropdownMenuContent align="end" role="menu">
                      <DropdownMenuItem role="menuitem">Edit</DropdownMenuItem>
                      <DropdownMenuItem className="text-destructive" role="menuitem">
                        Delete
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

export function Prompts() {
  const { navigate } = useRouter();
  const [prompts, setPrompts] = useState<PromptListItem[]>([]);
  const [limit, setLimit] = useState(DEFAULT_PAGE_SIZE);
  const [pagination, setPagination] = useState<PaginatedResponse<ApiPrompt>["pagination"] | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchPrompts = async () => {
      try {
        setLoading(true);
        const response = await promptsApi.list({
          page: 1,
          perPage: limit,
          includeInactive: true,
        });
        setPrompts(response.data.map(toPromptListItem));
        setPagination(response.pagination);
        setError(null);
      } catch (err) {
        console.error("Failed to fetch prompts:", err);
        setError("Failed to load prompts. Please try again.");
      } finally {
        setLoading(false);
      }
    };

    fetchPrompts();
  }, [limit]);

  const handleLoadMore = useCallback(async () => {
    if (!pagination?.has_next || loadingMore) return;

    setLoadingMore(true);
    try {
      const response = await promptsApi.list({
        page: pagination.page + 1,
        perPage: limit,
        includeInactive: true,
      });
      setPrompts((currentPrompts) => [
        ...currentPrompts,
        ...response.data.map(toPromptListItem),
      ]);
      setPagination(response.pagination);
    } catch (err) {
      console.error("Failed to load more prompts:", err);
    } finally {
      setLoadingMore(false);
    }
  }, [pagination, limit, loadingMore]);

  const handleLimitChange = useCallback((newLimit: number) => {
    setLimit(newLimit);
  }, []);

  if (loading) {
    return (
      <div className="p-6">
        <div className="flex justify-center items-center h-64">
          <p className="text-sm text-gray-600 dark:text-gray-400">Loading prompts...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="flex justify-center items-center h-64">
          <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6">
      {prompts.length > 0 ? (
        <>
          <div className="flex justify-between items-center mb-6">
            <h1 className="text-base font-semibold text-foreground">Prompts</h1>
            <Button
              variant="default"
              className="h-7 rounded-sm px-4"
              onClick={() => navigate(CREATE_PROMPT_PATH)}
            >
              <Plus className="h-4 w-4" />
              Add Prompt
            </Button>
          </div>

          <PromptsTable prompts={prompts} />

          <div className="flex items-center justify-between mt-6">
            <div className="flex items-center gap-4">
              <div className="text-sm text-gray-600 dark:text-gray-400">
                Showing {prompts.length} prompt{prompts.length !== 1 ? "s" : ""}
              </div>
              <div className="flex items-center gap-2">
                <label htmlFor="limit-select" className="text-sm text-gray-600 dark:text-gray-400">
                  Per page:
                </label>
                <select
                  id="limit-select"
                  value={limit}
                  onChange={(event) => handleLimitChange(Number(event.target.value))}
                  className="rounded-md border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 px-2 py-1 text-sm"
                >
                  <option value={10}>10</option>
                  <option value={25}>25</option>
                  <option value={50}>50</option>
                  <option value={100}>100</option>
                </select>
              </div>
            </div>
            {pagination?.has_next && (
              <Button
                variant="outline"
                size="sm"
                onClick={handleLoadMore}
                disabled={loadingMore}
                aria-label="Load more prompts"
              >
                {loadingMore ? "Loading..." : "Load More"}
              </Button>
            )}
          </div>
        </>
      ) : (
        <div className="flex items-center justify-center min-h-[600px]">
          <div className="flex flex-col items-center gap-6 w-full max-w-[324px]">
            <div className="flex flex-col gap-3 items-center justify-center relative">
              <div className="flex gap-3 items-center justify-center">
                <div className="size-[54.4px] rounded-[10.2px] border border-border bg-background flex items-center justify-center" />
                <div className="size-[54.4px] rounded-[10.2px] border border-border" />
                <div className="size-[54.4px] rounded-[10.2px] border border-border bg-background flex items-center justify-center">
                  <div className="grid grid-cols-3 gap-[4px]" />
                </div>

                <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 size-[54.4px] rounded-[10.2px] bg-background border border-white/25 shadow-[0px_4px_10px_rgba(255,255,255,0.05)] flex items-center justify-center">
                  <MCPIcon className="size-6 text-foreground" />
                </div>
              </div>
            </div>

            <div className="flex flex-col items-center gap-3 w-full">
              <h2 className="text-base font-medium text-foreground">Add Prompts</h2>
              <p className="text-sm text-muted-foreground text-center">
                Connect custom servers or Browse the MCP registry.
              </p>
            </div>

            <div className="flex flex-col gap-2 w-full">
              <Button
                variant="default"
                className="w-full h-10 rounded-lg"
                onClick={() => navigate(CREATE_PROMPT_PATH)}
              >
                <Plus className="size-4" />
                Add Prompt
              </Button>
              <Button variant="secondary" className="w-full h-10 rounded-lg" disabled>
                Browse Servers
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
