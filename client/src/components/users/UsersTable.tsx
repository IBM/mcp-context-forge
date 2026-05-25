import { Check, Laptop, Lock, MoreVertical, User as UserIcon } from "lucide-react";
import type { IntlShape } from "react-intl";
import { useIntl } from "react-intl";

import type { User } from "../../types/user";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../ui/table";

function formatDate(intl: IntlShape, value?: string | null): string {
  if (!value) return intl.formatMessage({ id: "users.date.never" });

  try {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return value;
    }

    const pad = (part: number) => part.toString().padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
  } catch {
    return value;
  }
}

function getDisplayName(user: User, intl: IntlShape): string {
  return user.full_name?.trim() || intl.formatMessage({ id: "users.unnamed" });
}

interface UsersTableProps {
  users: User[];
}

export function UsersTable({ users }: UsersTableProps) {
  const intl = useIntl();

  return (
    <div className="rounded-2xl shadow-sm">
      <Table className="border-separate border-spacing-y-2">
        <TableCaption className="sr-only">
          {intl.formatMessage({ id: "users.table.caption" })}
        </TableCaption>
        <TableHeader>
          <TableRow className="hover:bg-transparent data-[state=selected]:bg-transparent">
            <TableHead className="border-b border-border h-[52px] px-2 pl-3 text-[13px] font-normal leading-4 text-[#a3a3a3]">
              {intl.formatMessage({ id: "users.table.user" })}
            </TableHead>
            <TableHead className="border-b border-border h-[52px] px-2 text-[13px] font-normal leading-4 text-[#a3a3a3]">
              {intl.formatMessage({ id: "users.table.role" })}
            </TableHead>
            <TableHead className="border-b border-border h-[52px] px-2 text-[13px] font-normal leading-4 text-[#a3a3a3]">
              {intl.formatMessage({ id: "users.table.status" })}
            </TableHead>
            <TableHead className="border-b border-border h-[52px] px-2 text-[13px] font-normal leading-4 text-[#a3a3a3]">
              {intl.formatMessage({ id: "users.table.provider" })}
            </TableHead>
            <TableHead className="border-b border-border h-[52px] px-2 text-[13px] font-normal leading-4 text-[#a3a3a3]">
              {intl.formatMessage({ id: "users.table.security" })}
            </TableHead>
            <TableHead className="border-b border-border h-[52px] px-2 text-[13px] font-normal leading-4 text-[#a3a3a3]">
              {intl.formatMessage({ id: "users.table.created" })}
            </TableHead>
            <TableHead className="border-b border-border h-[52px] px-2 text-[13px] font-normal leading-4 text-[#a3a3a3]">
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
              securityIconClass = "text-[#34d399]";
            }

            return (
              <TableRow
                key={user.email}
                className="overflow-hidden border-0 bg-[#262626] hover:bg-[#2b2b2b] data-[state=selected]:bg-[#2b2b2b]"
              >
                <TableCell className="rounded-l-lg px-3 py-2.5">
                  <div className="flex items-center gap-2">
                    <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-[#6fff9f]">
                      <UserIcon className="h-[18px] w-[18px] text-black" strokeWidth={1.5} />
                    </div>
                    <div className="min-w-0">
                      <div className="truncate text-sm leading-5 text-white">{displayName}</div>
                      <div className="truncate text-xs leading-4 text-[#a3a3a3]">{user.email}</div>
                    </div>
                  </div>
                </TableCell>
                <TableCell className="px-3 py-2.5 text-sm leading-5 text-[#a3a3a3]">
                  {roleLabel}
                </TableCell>
                <TableCell className="px-3 py-2.5">
                  <div className="flex items-center gap-1.5 text-[13px] leading-4 text-[#a3a3a3]">
                    <Check
                      className={user.is_active ? "h-3 w-3 text-[#34d399]" : "h-3 w-3 text-[#737373]"}
                      strokeWidth={1.5}
                    />
                    <span>{statusLabel}</span>
                  </div>
                </TableCell>
                <TableCell className="px-3 py-2.5">
                  <div className="flex items-center gap-2 text-xs leading-4 text-[#a3a3a3]">
                    <Laptop className="h-3 w-3 shrink-0" strokeWidth={1.5} />
                    <span>{providerLabel}</span>
                  </div>
                </TableCell>
                <TableCell className="px-3 py-2.5">
                  <div className="flex items-center gap-2 text-xs leading-4 text-[#a3a3a3]">
                    <Lock className={`h-3 w-3 shrink-0 ${securityIconClass}`} strokeWidth={1.5} />
                    <span>{securityLabel}</span>
                  </div>
                </TableCell>
                <TableCell className="px-3 py-2.5 font-mono text-[13px] leading-4 text-[#a3a3a3]">
                  {formatDate(intl, user.created_at)}
                </TableCell>
                <TableCell className="px-3 py-2.5 font-mono text-[13px] leading-4 text-[#a3a3a3]">
                  {formatDate(intl, user.last_login)}
                </TableCell>
                <TableCell className="rounded-r-lg px-3 py-2.5 text-[#a3a3a3]">
                  <button
                    type="button"
                    className="inline-flex h-5 w-5 items-center justify-center rounded-sm transition-colors hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    aria-label={`${displayName} actions`}
                  >
                    <MoreVertical className="h-5 w-5" strokeWidth={1.25} />
                  </button>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
