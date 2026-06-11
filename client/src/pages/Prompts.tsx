import { Plus, Globe, Lock, Shield, Activity, CircleDashed, MoreHorizontal } from "lucide-react";
import { PromptIcon } from "@/components/icons/PromptIcon";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

type Visibility = "private" | "team" | "public";

interface PromptArgument {
  name: string;
  required: boolean;
}

interface Prompt {
  id: string;
  name: string;
  displayName: string | null;
  description: string | null;
  arguments: PromptArgument[];
  gatewaySlug: string | null;
  visibility: Visibility;
  enabled: boolean;
}

const MOCK_PROMPTS: Prompt[] = [
  {
    id: "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    name: "code_review",
    displayName: "Code Review",
    description: "Review code for bugs, security issues, and style violations.",
    arguments: [
      { name: "language", required: true },
      { name: "code", required: true },
      { name: "focus", required: false },
    ],
    gatewaySlug: "github-mcp",
    visibility: "public",
    enabled: true,
  },
  {
    id: "b2c3d4e5-f6a7-8901-bcde-f12345678901",
    name: "summarise_document",
    displayName: "Summarise Document",
    description: "Produce a concise summary of the provided document text.",
    arguments: [
      { name: "text", required: true },
      { name: "max_words", required: false },
    ],
    gatewaySlug: "docs-mcp",
    visibility: "team",
    enabled: true,
  },
  {
    id: "c3d4e5f6-a7b8-9012-cdef-123456789012",
    name: "sql_query_builder",
    displayName: "SQL Query Builder",
    description: "Generate a SQL query from a plain-language description.",
    arguments: [
      { name: "description", required: true },
      { name: "dialect", required: false },
      { name: "schema", required: false },
    ],
    gatewaySlug: null,
    visibility: "private",
    enabled: false,
  },
  {
    id: "d4e5f6a7-b8c9-0123-defa-234567890123",
    name: "test_case_generator",
    displayName: "Test Case Generator",
    description: "Generate unit test cases for a given function signature.",
    arguments: [
      { name: "function_signature", required: true },
      { name: "framework", required: false },
    ],
    gatewaySlug: "dev-tools-mcp",
    visibility: "public",
    enabled: true,
  },
];

function getVisibilityConfig(visibility: Visibility) {
  switch (visibility) {
    case "private":
      return { label: "Private", Icon: Lock };
    case "team":
      return { label: "Team", Icon: Shield };
    default:
      return { label: "Public", Icon: Globe };
  }
}

function PromptsTable({ prompts }: { prompts: Prompt[] }) {
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
                        className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium leading-none ${
                          arg.required
                            ? "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300"
                            : "bg-neutral-100 text-neutral-600 dark:bg-neutral-700 dark:text-neutral-400"
                        }`}
                        title={arg.required ? "required" : "optional"}
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
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 w-7 p-0"
                    aria-label={`Actions for ${prompt.displayName ?? prompt.name}`}
                  >
                    <MoreHorizontal className="h-4 w-4" />
                  </Button>
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
  const prompts = MOCK_PROMPTS;

  return (
    <div className="p-6">
      {prompts.length > 0 ? (
        <>
          <div className="flex justify-between items-center mb-6">
            <h1 className="text-base font-semibold text-foreground">Prompts</h1>
            <Button variant="default" className="h-7 rounded-sm px-4">
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
            <p className="text-sm text-foreground">
              Register a prompt template to make it available across virtual servers. Prompts are
              sourced from connected MCP servers or defined locally.
            </p>
          </div>

          <Button className="bg-foreground text-background hover:bg-foreground/90 h-8 w-38 rounded-sm px-2 gap-1.5 text-sm font-medium">
            <Plus className="size-3" />
            Add Prompt
          </Button>
        </div>
      )}
    </div>
  );
}
