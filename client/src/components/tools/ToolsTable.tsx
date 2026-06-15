import { useState } from "react";
import { Copy, MoreHorizontal } from "lucide-react";
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
import type { Tool } from "@/types/tool";
import { copyToClipboard, truncateMiddle } from "@/components/gateways/utils";
import { ToolSchemaDialog } from "@/components/tools/ToolSchemaDialog";

export function ToolsTable({
  tools,
  selectedToolId,
  onSelectTool,
  onDeleteTool,
}: {
  tools: Tool[];
  selectedToolId?: string | null;
  onSelectTool: (tool: Tool) => void;
  onDeleteTool?: (toolId: string) => void;
}) {
  const [schemaDialogTool, setSchemaDialogTool] = useState<Tool | null>(null);
  const [isSchemaDialogOpen, setIsSchemaDialogOpen] = useState(false);

  const handleSchemaClick = (tool: Tool) => {
    setSchemaDialogTool(tool);
    setIsSchemaDialogOpen(true);
  };

  return (
    <>
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="h-9 px-4 py-2.5 text-xs font-medium">Tool</TableHead>
            <TableHead className="h-9 px-4 py-2.5 text-xs font-medium">Name</TableHead>
            <TableHead className="h-9 px-4 py-2.5 text-xs font-medium">Tool ID</TableHead>
            <TableHead className="h-9 w-[80px] px-4 py-2.5 text-xs font-medium">Schema</TableHead>
            <TableHead className="h-9 w-[40px] px-4 py-2.5" />
          </TableRow>
        </TableHeader>
        <TableBody className="[&_tr]:border-0">
          {tools.map((tool) => (
            <TableRow
              key={tool.id}
              data-state={selectedToolId === tool.id ? "selected" : undefined}
              onClick={() => onSelectTool(tool)}
              className="cursor-pointer"
            >
              <TableCell className="px-4 py-3 text-sm text-foreground">
                <span className="line-clamp-1">{tool.displayName || tool.title || tool.name}</span>
              </TableCell>

              <TableCell className="px-4 py-3">
                <div className="flex min-w-0 items-center">
                  <span className="min-w-0 truncate font-mono text-xs text-muted-foreground">
                    {tool.originalName}
                  </span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-xs"
                    aria-label={`Copy ${tool.originalName}`}
                    className="ml-4 size-4 shrink-0 text-muted-foreground hover:text-foreground"
                    onClick={(e) => {
                      e.stopPropagation();
                      copyToClipboard(tool.originalName);
                    }}
                  >
                    <Copy className="size-3" />
                  </Button>
                </div>
              </TableCell>

              <TableCell className="px-4 py-3">
                <div className="flex min-w-0 items-center">
                  <span className="min-w-0 truncate font-mono text-xs text-muted-foreground">
                    {truncateMiddle(tool.id, 18)}
                  </span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-xs"
                    aria-label="Copy tool ID"
                    className="ml-4 size-4 shrink-0 text-muted-foreground hover:text-foreground"
                    onClick={(e) => {
                      e.stopPropagation();
                      copyToClipboard(tool.id);
                    }}
                  >
                    <Copy className="size-3" />
                  </Button>
                </div>
              </TableCell>

              <TableCell className="px-4 py-3 text-center">
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  aria-label="View schema"
                  className="size-5 text-muted-foreground hover:text-foreground"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleSchemaClick(tool);
                  }}
                >
                  <svg className="size-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4"
                    />
                  </svg>
                </Button>
              </TableCell>

              <TableCell className="px-4 py-3 text-center">
                {onDeleteTool ? (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-xs"
                        aria-label="More options"
                        className="size-5 text-muted-foreground hover:text-foreground"
                        onClick={(e) => {
                          e.stopPropagation();
                        }}
                      >
                        <MoreHorizontal className="size-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem
                        onClick={(e) => {
                          e.stopPropagation();
                          onDeleteTool(tool.id);
                        }}
                        className="text-destructive focus:text-destructive"
                      >
                        Delete
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                ) : (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-xs"
                    aria-label="More options"
                    className="size-5 text-muted-foreground hover:text-foreground"
                    onClick={(e) => {
                      e.stopPropagation();
                    }}
                  >
                    <MoreHorizontal className="size-4" />
                  </Button>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <ToolSchemaDialog
        tool={schemaDialogTool}
        open={isSchemaDialogOpen}
        onOpenChange={(open) => {
          setIsSchemaDialogOpen(open);
          if (!open) setSchemaDialogTool(null);
        }}
      />
    </>
  );
}
