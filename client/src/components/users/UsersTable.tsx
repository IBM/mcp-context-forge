import { Check, Laptop, Lock, User as UserIcon } from "lucide-react";
import type { IntlShape } from "react-intl";
import { useIntl } from "react-intl";

import type { User } from "../../types/user";
import { UserActionsMenu } from "./UserActionsMenu";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../ui/table";
import { formatLocalDateTime } from "../../utils/formatDate";

function getDisplayName(user: User, intl: IntlShape): string {
  return user.full_name?.trim() || intl.formatMessage({ id: "users.unnamed" });
}

interface UsersTableProps {
  users: User[];
  onDeleteClick: (user: User) => void;
  onEditClick: (user: User) => void;
}

export function UsersTable({ users, onDeleteClick, onEditClick }: UsersTableProps) {
  const intl = useIntl();

  return (
    <div className="rounded-2xl">
      <Table
        className="border-separate border-spacing-y-2"
        aria-label={intl.formatMessage({ id: "users.table.caption" })}
      >
        <TableCaption className="sr-only">
          {intl.formatMessage({ id: "users.table.caption" })}
        </TableCaption>
        <TableHeader>
          <TableRow className="hover:bg-transparent data-[state=selected]:bg-transparent">
            <TableHead className="border-b border-border h-[52px] px-2 pl-3 text-[13px] font-normal leading-4 text-muted-foreground">
              {intl.formatMessage({ id: "users.table.user" })}
            </TableHead>
            <TableHead className="border-b border-border h-[52px] px-2 text-[13px] font-normal leading-4 text-muted-foreground">
              {intl.formatMessage({ id: "users.table.role" })}
            </TableHead>
            <TableHead className="border-b border-border h-[52px] px-2 text-[13px] font-normal leading-4 text-muted-foreground">
              {intl.formatMessage({ id: "users.table.status" })}
            </TableHead>
            <TableHead className="border-b border-border h-[52px] px-2 text-[13px] font-normal leading-4 text-muted-foreground">
              {intl.formatMessage({ id: "users.table.provider" })}
            </TableHead>
            <TableHead className="border-b border-border h-[52px] px-2 text-[13px] font-normal leading-4 text-muted-foreground">
              {intl.formatMessage({ id: "users.table.security" })}
            </TableHead>
            <TableHead className="border-b border-border h-[52px] px-2 text-[13px] font-normal leading-4 text-muted-foreground">
              {intl.formatMessage({ id: "users.table.created" })}
            </TableHead>
            <TableHead className="border-b border-border h-[52px] px-2 text-[13px] font-normal leading-4 text-muted-foreground">
              {intl.formatMessage({ id: "users.table.lastLogin" })}
            </TableHead>
            <TableHead className="border-b border-border h-[52px] w-10 px-2 pr-3">
              <span className="sr-only">Actions</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {users.map((user) => {
            const displayName = getDisplayName(user, intl);
            const roleLabel = intl.formatMessage({
              id: user.is_admin ? "users.role.admin" : "users.role.user",
            });
            const statusLabel = intl.formatMessage({
              id: user.is_active ? "users.status.active" : "users.status.inactive",
            });
            const providerLabel =
              user.auth_provider.charAt(0).toUpperCase() + user.auth_provider.slice(1);

            let securityLabel = intl.formatMessage({ id: "users.security.noFlags" });
            let securityIconClass = "text-muted-foreground";

            if (user.is_locked) {
              securityLabel = intl.formatMessage({ id: "users.security.locked" });
              securityIconClass = "text-destructive";
            } else if (user.password_change_required) {
              securityLabel = intl.formatMessage({ id: "users.security.passwordReset" });
              securityIconClass = "text-amber-400";
            } else if (user.email_verified) {
              securityLabel = intl.formatMessage({ id: "users.security.verified" });
              securityIconClass = "text-accent-foreground";
            }

            return (
              <TableRow
                key={user.email}
                className="overflow-hidden border-0 bg-card hover:bg-muted data-[state=selected]:bg-muted"
              >
                <TableCell className="rounded-l-lg px-3 py-2.5">
                  <div className="flex items-center gap-2">
                    <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-accent">
                      <UserIcon
                        className="h-[18px] w-[18px] text-accent-foreground"
                        strokeWidth={1.5}
                      />
                    </div>
                    <div className="min-w-0">
                      <div className="truncate text-sm leading-5 text-card-foreground">
                        {displayName}
                      </div>
                      <div className="truncate text-xs leading-4 text-muted-foreground">
                        {user.email}
                      </div>
                    </div>
                  </div>
                </TableCell>
                <TableCell className="px-3 py-2.5 text-sm leading-5 text-muted-foreground">
                  {roleLabel}
                </TableCell>
                <TableCell className="px-3 py-2.5">
                  <div className="flex items-center gap-1.5 text-[13px] leading-4 text-muted-foreground">
                    <Check
                      className={
                        user.is_active ? "h-3 w-3 text-accent-foreground" : "h-3 w-3 text-muted"
                      }
                      strokeWidth={1.5}
                      aria-hidden="true"
                    />
                    <span>{statusLabel}</span>
                  </div>
                </TableCell>
                <TableCell className="px-3 py-2.5">
                  <div className="flex items-center gap-2 text-xs leading-4 text-muted-foreground">
                    <Laptop className="h-3 w-3 shrink-0" strokeWidth={1.5} aria-hidden="true" />
                    <span>{providerLabel}</span>
                  </div>
                </TableCell>
                <TableCell className="px-3 py-2.5">
                  <div className="flex items-center gap-2 text-xs leading-4 text-muted-foreground">
                    <Lock
                      className={`h-3 w-3 shrink-0 ${securityIconClass}`}
                      strokeWidth={1.5}
                      aria-hidden="true"
                    />
                    <span>{securityLabel}</span>
                  </div>
                </TableCell>
                <TableCell className="px-3 py-2.5 font-mono text-[13px] leading-4 text-muted-foreground">
                  {formatLocalDateTime(user.created_at, intl.formatMessage({ id: "users.date.never" }))}
                </TableCell>
                <TableCell className="px-3 py-2.5 font-mono text-[13px] leading-4 text-muted-foreground">
                  {formatLocalDateTime(user.last_login, intl.formatMessage({ id: "users.date.never" }))}
                </TableCell>
                <TableCell className="rounded-r-lg px-3 py-2.5 text-muted-foreground">
                  <UserActionsMenu
                    user={user}
                    displayName={displayName}
                    onEdit={(u) => onEditClick(u)}
                    onDelete={(email) => {
                      const userToDelete = users.find((u) => u.email === email);
                      if (userToDelete) {
                        onDeleteClick(userToDelete);
                      }
                    }}
                  />
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
