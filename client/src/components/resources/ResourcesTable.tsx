import { useIntl } from "react-intl";
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
import type { ResourceRead } from "@/generated/types";
import { copyToClipboard, truncateMiddle } from "@/components/gateways/utils";

export function ResourcesTable({
  resources,
  selectedResourceId,
  onSelectResource,
  onEditResource,
  onDeleteResource,
}: {
  resources: NonNullable<ResourceRead>[];
  selectedResourceId?: string | null;
  onSelectResource: (resource: NonNullable<ResourceRead>) => void;
  onEditResource?: (resource: NonNullable<ResourceRead>) => void;
  onDeleteResource?: (resourceId: string) => void;
}) {
  const intl = useIntl();

  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="h-9 px-4 py-2.5 text-xs font-medium">
            {intl.formatMessage({ id: "resources.table.resource" })}
          </TableHead>
          <TableHead className="h-9 px-4 py-2.5 text-xs font-medium">
            {intl.formatMessage({ id: "resources.table.uri" })}
          </TableHead>
          <TableHead className="h-9 px-4 py-2.5 text-xs font-medium">
            {intl.formatMessage({ id: "resources.table.resourceId" })}
          </TableHead>
          <TableHead className="h-9 w-[40px] px-4 py-2.5" />
        </TableRow>
      </TableHeader>
      <TableBody className="[&_tr]:border-0">
        {resources.map((resource) => (
          <TableRow
            key={resource.id}
            data-state={selectedResourceId === resource.id ? "selected" : undefined}
            onClick={() => onSelectResource(resource)}
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onSelectResource(resource);
              }
            }}
            className="cursor-pointer focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-inset"
          >
            <TableCell className="px-4 py-3 text-sm text-foreground">
              <span className="line-clamp-1">{resource.title || resource.name}</span>
            </TableCell>

            <TableCell className="px-4 py-3">
              <div className="flex min-w-0 items-center">
                <span className="min-w-0 truncate font-mono text-xs text-muted-foreground">
                  {truncateMiddle(resource.uriTemplate || resource.uri, 28)}
                </span>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  aria-label={intl.formatMessage(
                    { id: "resources.table.copyUri" },
                    { uri: resource.uriTemplate || resource.uri },
                  )}
                  className="ml-4 size-4 shrink-0 text-muted-foreground hover:text-foreground"
                  onClick={(e) => {
                    e.stopPropagation();
                    copyToClipboard(resource.uriTemplate || resource.uri);
                  }}
                >
                  <Copy className="size-3" />
                </Button>
              </div>
            </TableCell>

            <TableCell className="px-4 py-3">
              <div className="flex min-w-0 items-center">
                <span className="min-w-0 truncate font-mono text-xs text-muted-foreground">
                  {truncateMiddle(resource.id, 18)}
                </span>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  aria-label={intl.formatMessage({ id: "resources.table.copyResourceId" })}
                  className="ml-4 size-4 shrink-0 text-muted-foreground hover:text-foreground"
                  onClick={(e) => {
                    e.stopPropagation();
                    copyToClipboard(resource.id);
                  }}
                >
                  <Copy className="size-3" />
                </Button>
              </div>
            </TableCell>

            <TableCell className="px-4 py-3 text-center">
              {onEditResource || onDeleteResource ? (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-xs"
                      aria-label={intl.formatMessage(
                        { id: "resources.table.moreOptionsFor" },
                        { name: resource.title || resource.name },
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
                    {onEditResource && (
                      <DropdownMenuItem
                        onClick={(e) => {
                          e.stopPropagation();
                          onEditResource(resource);
                        }}
                      >
                        {intl.formatMessage({ id: "resources.table.edit" })}
                      </DropdownMenuItem>
                    )}
                    {onDeleteResource && (
                      <DropdownMenuItem
                        onClick={(e) => {
                          e.stopPropagation();
                          onDeleteResource(resource.id);
                        }}
                      >
                        {intl.formatMessage({ id: "resources.table.delete" })}
                      </DropdownMenuItem>
                    )}
                  </DropdownMenuContent>
                </DropdownMenu>
              ) : (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  aria-label={intl.formatMessage(
                    { id: "resources.table.moreOptionsFor" },
                    { name: resource.title || resource.name },
                  )}
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
  );
}
