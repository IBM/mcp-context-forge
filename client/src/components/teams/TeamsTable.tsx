import { useIntl } from "react-intl";
import { MoreVertical, SquareMenu } from "lucide-react";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../ui/table";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "../ui/dropdown-menu";
import { Button } from "../ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "../ui/popover";
import type { Team } from "../../types/team";
import { Loading } from "../ui/loading";
import { formatLocalDateTime } from "../../utils/formatDate";

function getTeamIcon(name: string): string {
  return name.charAt(0).toUpperCase();
}

interface TeamsTableProps {
  teams: Team[];
  isLoading: boolean;
  onEdit?: (id: string) => void;
  onDelete?: (id: string) => void;
  onManageMembers?: (id: string) => void;
}

export function TeamsTable({
  teams,
  isLoading,
  onEdit,
  onDelete,
  onManageMembers,
}: TeamsTableProps) {
  const intl = useIntl();
  const invalidDateLabel = intl.formatMessage({ id: "teams.table.invalidDate" });

  if (isLoading) {
    return (
      <div
        className="flex items-center justify-center py-12"
        role="status"
        aria-live="polite"
        aria-busy="true"
      >
        <Loading />
        <span className="sr-only">{intl.formatMessage({ id: "teams.loading.sr" })}</span>
      </div>
    );
  }

  return (
    <div className="overflow-hidden">
      <Table className="min-w-full border-separate border-spacing-y-1.5">
        <TableCaption className="sr-only">
          {intl.formatMessage({ id: "teams.table.caption" })}
        </TableCaption>
        <TableHeader className="bg-white dark:bg-transparent">
          <TableRow className="border-none hover:bg-transparent">
            <TableHead className="border-b border-border h-12 px-4 text-xs font-medium text-neutral-600 dark:text-neutral-400">
              {intl.formatMessage({ id: "teams.table.name" })}
            </TableHead>
            <TableHead className="border-b border-border h-12 px-4 text-xs font-medium text-neutral-600 dark:text-neutral-400">
              {intl.formatMessage({ id: "teams.table.visibility" })}
            </TableHead>
            <TableHead className="border-b border-border h-12 px-4 text-xs font-medium text-neutral-600 dark:text-neutral-400">
              {intl.formatMessage({ id: "teams.table.members" })}
            </TableHead>
            <TableHead className="border-b border-border h-12 px-4 text-xs font-medium text-neutral-600 dark:text-neutral-400">
              {intl.formatMessage({ id: "teams.table.created" })}
            </TableHead>
            <TableHead className="border-b border-border h-12 px-4 text-xs font-medium text-neutral-600 dark:text-neutral-400">
              {intl.formatMessage({ id: "teams.table.updated" })}
            </TableHead>
            <TableHead className="border-b border-border h-12 px-4 text-xs font-medium text-neutral-600 dark:text-neutral-400 text-right">
              {intl.formatMessage({ id: "teams.table.actions" })}
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {teams.map((team) => {
            const icon = getTeamIcon(team.name);

            return (
              <TableRow
                key={team.id}
                className="bg-neutral-50 dark:bg-neutral-800 hover:bg-neutral-100 dark:hover:bg-neutral-700/60 [&>td:first-child]:rounded-l-lg [&>td:last-child]:rounded-r-lg"
              >
                <TableCell className="px-4 py-2.5">
                  <div className="flex items-center gap-3">
                    <div className="flex h-6 w-6 items-center justify-center rounded bg-yellow-500">
                      <span className="text-xs font-semibold text-black">{icon}</span>
                    </div>
                    <span className="font-medium text-neutral-900 dark:text-neutral-100">
                      {team.name}
                    </span>
                  </div>
                </TableCell>
                <TableCell className="px-4 py-2.5 text-xs text-neutral-600 dark:text-neutral-400">
                  {team.visibility}
                </TableCell>
                <TableCell className="px-4 py-2.5 text-xs text-neutral-600 dark:text-neutral-400">
                  {team.member_count}
                </TableCell>
                <TableCell className="px-4 py-2.5 text-xs text-neutral-600 dark:text-neutral-400">
                  {formatLocalDateTime(team.created_at, invalidDateLabel)}
                </TableCell>
                <TableCell className="px-4 py-2.5 text-xs text-neutral-600 dark:text-neutral-400">
                  {formatLocalDateTime(team.updated_at, invalidDateLabel)}
                </TableCell>
                <TableCell className="px-4 py-2.5 text-right">
                  <div className="flex items-center justify-end gap-1">
                    {team.description && (
                      <Popover>
                        <PopoverTrigger asChild>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-8 w-8 p-0"
                            aria-label={intl.formatMessage(
                              { id: "teams.table.description.view" },
                              { name: team.name },
                            )}
                          >
                            <SquareMenu className="h-4 w-4" />
                          </Button>
                        </PopoverTrigger>
                        <PopoverContent
                          align="end"
                          className="w-64 border-0 p-3 text-sm shadow-lg dark:bg-neutral-700 dark:text-neutral-100"
                        >
                          {team.description}
                        </PopoverContent>
                      </Popover>
                    )}
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-8 w-8 p-0"
                          aria-label={intl.formatMessage(
                            { id: "teams.table.actions.label" },
                            { name: team.name },
                          )}
                        >
                          <MoreVertical className="h-4 w-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" className="w-48">
                        <DropdownMenuItem
                          onClick={() => {
                            // TODO: wire up edit team action
                            onEdit?.(team.id);
                          }}
                        >
                          {intl.formatMessage({ id: "teams.table.actions.edit" })}
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          onClick={() => {
                            onManageMembers?.(team.id);
                          }}
                        >
                          {intl.formatMessage({ id: "teams.table.actions.manageMembers" })}
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          onClick={() => {
                            // TODO: wire up delete team action
                            onDelete?.(team.id);
                          }}
                        >
                          {intl.formatMessage({ id: "teams.table.actions.delete" })}
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
