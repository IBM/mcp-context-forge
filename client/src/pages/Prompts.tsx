import { Plus, Globe, Lock, Shield, Activity, CircleDashed, MoreVertical } from "lucide-react";
import { PromptIcon } from "@/components/icons/PromptIcon";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useState, useEffect } from "react";
import { promptsApi, type Prompt as ApiPrompt, type PromptArgument } from "@/api/prompts";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

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
    displayName: prompt.display_name,
    description: prompt.description,
    arguments: prompt.arguments,
    gatewaySlug: prompt.gateway_slug,
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
  const [prompts, setPrompts] = useState<PromptListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchPrompts = async () => {
      try {
        setLoading(true);
        const data = await promptsApi.list();
        setPrompts(data.map(toPromptListItem));
        setError(null);
      } catch (err) {
        console.error("Failed to fetch prompts:", err);
        setError("Failed to load prompts. Please try again.");
      } finally {
        setLoading(false);
      }
    };

    fetchPrompts();
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
            <Button variant="default" className="h-7 rounded-sm px-4" disabled>
              <Plus className="h-4 w-4" />
              Add Prompt
            </Button>
          </div>

          <PromptsTable prompts={prompts} />

          <div className="mt-6 text-sm text-gray-600 dark:text-gray-400">
            Showing {prompts.length} prompt{prompts.length !== 1 ? "s" : ""}
          </div>
        </>
      ) : (
        <div className="border border-border rounded-lg p-6 flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <div className="flex size-6 shrink-0 items-center justify-center rounded-sm bg-indigo-500">
              <PromptIcon className="size-4 text-white" />
            </div>
            <h2 className="text-base font-medium">Add a prompt</h2>
          </div>

          <div className="py-5">
            <p className="text-sm text-foreground">Add a prompt template.</p>
          </div>

          <Button
            className="bg-foreground text-background hover:bg-foreground/90 h-8 w-38 rounded-sm px-2 gap-1.5 text-sm font-medium"
            disabled
          >
            <Plus className="size-3" />
            Add Prompt
          </Button>
        </div>
      )}
    </div>
  );
}
