import { SquareMenu } from "lucide-react";
import { useIntl } from "react-intl";

import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { formatLastSeen } from "@/utils/format";
import { formatLocalDateTime } from "@/utils/formatDate";
import type { TokenResponse } from "@/types/token";
import { TokenActionsMenu } from "./TokenActionsMenu";
import { TokenIcon } from "./TokenIcon";

interface TokensTableProps {
  tokens: TokenResponse[];
  /** Maps team_id -> display name so the Team column shows the name, not the id. */
  teamNames: Map<string, string>;
  onDeleteClick: (token: TokenResponse) => void;
}

/** Uppercases the first character of the localized relative-time string. */
function capitalizeFirst(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export function TokensTable({ tokens, teamNames, onDeleteClick }: TokensTableProps) {
  const intl = useIntl();
  const neverLabel = intl.formatMessage({ id: "tokens.table.never" });

  const headClass =
    "border-b border-border h-12 px-4 text-xs font-medium text-neutral-600 dark:text-neutral-400";

  return (
    <div className="overflow-hidden">
      <Table
        className="min-w-full border-separate border-spacing-y-1.5"
        aria-label={intl.formatMessage({ id: "tokens.table.caption" })}
      >
        <TableCaption className="sr-only">
          {intl.formatMessage({ id: "tokens.table.caption" })}
        </TableCaption>
        <TableHeader className="bg-main">
          <TableRow className="border-none hover:bg-transparent">
            <TableHead className={headClass}>
              {intl.formatMessage({ id: "tokens.table.name" })}
            </TableHead>
            <TableHead className={headClass}>
              {intl.formatMessage({ id: "tokens.table.team" })}
            </TableHead>
            <TableHead className={headClass}>
              {intl.formatMessage({ id: "tokens.table.expiration" })}
            </TableHead>
            <TableHead className={headClass}>
              {intl.formatMessage({ id: "tokens.table.created" })}
            </TableHead>
            <TableHead className={headClass}>
              {intl.formatMessage({ id: "tokens.table.lastUsed" })}
            </TableHead>
            <TableHead className={`${headClass} text-right`}>
              {intl.formatMessage({ id: "tokens.table.actions" })}
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {tokens.map((token) => {
            const relativeExpiry = token.expires_at ? formatLastSeen(token.expires_at) : null;
            const expiryLabel = relativeExpiry ? capitalizeFirst(relativeExpiry) : neverLabel;
            const teamLabel = token.team_id ? (teamNames.get(token.team_id) ?? token.team_id) : "—";

            return (
              <TableRow
                key={token.id}
                className="bg-white hover:bg-neutral-100 dark:bg-neutral-800 dark:hover:bg-neutral-700/60 [&>td:first-child]:rounded-l-lg [&>td:last-child]:rounded-r-lg"
              >
                <TableCell className="px-4 py-2.5">
                  <div className="flex items-center gap-3">
                    <TokenIcon />
                    <span className="font-medium text-neutral-900 dark:text-neutral-100">
                      {token.name}
                    </span>
                  </div>
                </TableCell>
                <TableCell className="px-4 py-2.5 text-xs text-neutral-600 dark:text-neutral-400">
                  {teamLabel}
                </TableCell>
                <TableCell className="px-4 py-2.5 text-xs text-neutral-600 dark:text-neutral-400">
                  {expiryLabel}
                </TableCell>
                <TableCell className="px-4 py-2.5 font-mono text-[13px] leading-4 text-neutral-600 dark:text-neutral-400">
                  {formatLocalDateTime(token.created_at, neverLabel)}
                </TableCell>
                <TableCell className="px-4 py-2.5 font-mono text-[13px] leading-4 text-neutral-600 dark:text-neutral-400">
                  {formatLocalDateTime(token.last_used, neverLabel)}
                </TableCell>
                <TableCell className="px-4 py-2.5 text-right">
                  <div className="flex items-center justify-end gap-1">
                    {token.description && (
                      <Popover>
                        <PopoverTrigger asChild>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-8 w-8 p-0"
                            aria-label={intl.formatMessage(
                              { id: "tokens.table.description.label" },
                              { name: token.name },
                            )}
                          >
                            <SquareMenu className="h-4 w-4" />
                          </Button>
                        </PopoverTrigger>
                        <PopoverContent
                          align="end"
                          className="w-64 border-0 p-3 text-sm shadow-lg dark:bg-neutral-700 dark:text-neutral-100"
                        >
                          {token.description}
                        </PopoverContent>
                      </Popover>
                    )}
                    <TokenActionsMenu token={token} onDelete={onDeleteClick} />
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
