import { Copy, MoreHorizontal } from "lucide-react";
import { useIntl } from "react-intl";

import type { PromptRead } from "@/generated/types";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { copyToClipboard } from "@/lib/clipboard";
import { truncateMiddle } from "@/components/gateways/utils";

export interface PromptDefinitionTableProps {
  prompts: NonNullable<PromptRead>[];
  selectedPromptId?: string;
  onSelectPrompt: (prompt: NonNullable<PromptRead>) => void;
  onEdit?: (prompt: NonNullable<PromptRead>) => void;
  onDelete?: (prompt: NonNullable<PromptRead>) => void;
}

/**
 * "Definition" tab content for the prompt details drawer. Styled to match the
 * Tools/Resources tables: lists every prompt in the group with its name and a
 * copyable ID, plus a per-row overflow menu (Edit/Delete). Selecting a row
 * updates the Prompt details sidebar. The overflow menu replaces the one that
 * previously sat beside the panel title.
 *
 * a11y: row selection is conveyed visually via `data-state` only, matching the
 * Tools/Resources tables. Exposing it to assistive tech (grid role +
 * aria-selected) is a cross-cutting follow-up across all three tables.
 */
export function PromptDefinitionTable({
  prompts,
  selectedPromptId,
  onSelectPrompt,
  onEdit,
  onDelete,
}: PromptDefinitionTableProps) {
  const intl = useIntl();

  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="h-9 w-[30%] px-4 py-2.5 text-xs font-medium">
            {intl.formatMessage({ id: "prompts.details.label.name" })}
          </TableHead>
          <TableHead className="h-9 px-4 py-2.5 text-xs font-medium">
            {intl.formatMessage({ id: "prompts.details.label.promptId" })}
          </TableHead>
          <TableHead className="h-9 w-[40px] px-4 py-2.5" />
        </TableRow>
      </TableHeader>
      <TableBody className="[&_tr]:border-0">
        {prompts.map((prompt) => (
          <TableRow
            key={prompt.id}
            data-state={selectedPromptId === prompt.id ? "selected" : undefined}
            onClick={() => onSelectPrompt(prompt)}
            tabIndex={0}
            onKeyDown={(e) => {
              // Ignore keys bubbling up from in-row controls (copy / menu) so
              // activating them doesn't also select the row.
              if (e.target !== e.currentTarget) return;
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onSelectPrompt(prompt);
              }
            }}
            className="cursor-pointer focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-inset"
          >
            <TableCell className="px-4 py-3 text-sm text-foreground">
              <span className="line-clamp-1">{prompt.displayName || prompt.name}</span>
            </TableCell>

            <TableCell className="px-4 py-3">
              <div className="flex min-w-0 items-center">
                <span className="min-w-0 truncate font-mono text-xs text-muted-foreground">
                  {truncateMiddle(prompt.id, 40)}
                </span>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  aria-label={intl.formatMessage(
                    { id: "prompts.details.table.copyPromptId" },
                    { name: prompt.name },
                  )}
                  className="ml-4 size-4 shrink-0 text-muted-foreground hover:text-foreground"
                  onClick={(e) => {
                    e.stopPropagation();
                    copyToClipboard(prompt.id);
                  }}
                >
                  <Copy className="size-3" />
                </Button>
              </div>
            </TableCell>

            <TableCell className="px-4 py-3 text-center">
              {(onEdit || onDelete) && (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-xs"
                      aria-label={intl.formatMessage(
                        { id: "prompts.details.moreOptionsFor" },
                        { name: prompt.name },
                      )}
                      className="size-5 text-muted-foreground hover:text-foreground"
                      onClick={(e) => {
                        e.stopPropagation();
                      }}
                    >
                      <MoreHorizontal className="size-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    {onEdit && (
                      <DropdownMenuItem
                        onClick={(e) => {
                          e.stopPropagation();
                          onEdit(prompt);
                        }}
                      >
                        {intl.formatMessage({ id: "prompts.details.action.edit" })}
                      </DropdownMenuItem>
                    )}
                    {onDelete && (
                      <DropdownMenuItem
                        onClick={(e) => {
                          e.stopPropagation();
                          onDelete(prompt);
                        }}
                      >
                        {intl.formatMessage({ id: "prompts.details.action.delete" })}
                      </DropdownMenuItem>
                    )}
                  </DropdownMenuContent>
                </DropdownMenu>
              )}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
