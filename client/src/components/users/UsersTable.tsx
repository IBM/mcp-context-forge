import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../ui/table";
import { Badge } from "../ui/badge";
import type { User } from "../../types/user";
import type { IntlShape } from "react-intl";
import { useIntl } from "react-intl";

function formatDate(intl: IntlShape, value?: string | null): string {
  if (!value) return intl.formatMessage({ id: "users.date.never" });

  try {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return value;
    }
    return date.toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return value;
  }
}

function getDisplayName(user: User): string {
  return user.full_name?.trim() || "Unnamed user";
}

interface UsersTableProps {
  users: User[];
  isLoading: boolean;
}

export function UsersTable({ users, isLoading }: UsersTableProps) {
  const intl = useIntl();

  if (isLoading) {
    return (
      <div
        className="flex items-center justify-center py-12"
        role="status"
        aria-live="polite"
        aria-busy="true"
      >
        <span className="sr-only">{intl.formatMessage({ id: "users.loading.sr" })}</span>
        <div className="text-gray-600 dark:text-gray-400">
          {intl.formatMessage({ id: "users.loading" })}
        </div>
      </div>
    );
  }

  return (
    <Table>
      <TableCaption className="sr-only">
        {intl.formatMessage({ id: "users.table.caption" })}
      </TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead>{intl.formatMessage({ id: "users.table.user" })}</TableHead>
          <TableHead>{intl.formatMessage({ id: "users.table.role" })}</TableHead>
          <TableHead>{intl.formatMessage({ id: "users.table.status" })}</TableHead>
          <TableHead>{intl.formatMessage({ id: "users.table.provider" })}</TableHead>
          <TableHead>{intl.formatMessage({ id: "users.table.security" })}</TableHead>
          <TableHead>{intl.formatMessage({ id: "users.table.created" })}</TableHead>
          <TableHead>{intl.formatMessage({ id: "users.table.lastLogin" })}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {users.map((user) => (
          <TableRow key={user.email} className="hover:bg-gray-50 dark:hover:bg-gray-800">
            <TableCell>
              <div className="flex flex-col">
                <span className="font-medium text-gray-900 dark:text-gray-100">
                  {getDisplayName(user) === "Unnamed user"
                    ? intl.formatMessage({ id: "users.unnamed" })
                    : getDisplayName(user)}
                </span>
                <span className="text-sm text-gray-600 dark:text-gray-400">{user.email}</span>
              </div>
            </TableCell>
            <TableCell>
              <Badge variant={user.is_admin ? "default" : "secondary"}>
                {intl.formatMessage({ id: user.is_admin ? "users.role.admin" : "users.role.user" })}
              </Badge>
            </TableCell>
            <TableCell>
              <Badge variant={user.is_active ? "success" : "draft"}>
                {intl.formatMessage({
                  id: user.is_active ? "users.status.active" : "users.status.inactive",
                })}
              </Badge>
            </TableCell>
            <TableCell className="text-gray-600 dark:text-gray-400">{user.auth_provider}</TableCell>
            <TableCell>
              <div className="flex flex-wrap gap-1.5">
                {user.email_verified && (
                  <Badge variant="outline">
                    {intl.formatMessage({ id: "users.security.verified" })}
                  </Badge>
                )}
                {user.password_change_required && (
                  <Badge variant="warning">
                    {intl.formatMessage({ id: "users.security.passwordReset" })}
                  </Badge>
                )}
                {user.is_locked && (
                  <Badge variant="destructive">
                    {intl.formatMessage({ id: "users.security.locked" })}
                  </Badge>
                )}
                {!user.email_verified && !user.password_change_required && !user.is_locked && (
                  <span className="text-gray-600 dark:text-gray-400">
                    {intl.formatMessage({ id: "users.security.noFlags" })}
                  </span>
                )}
              </div>
            </TableCell>
            <TableCell className="text-gray-600 dark:text-gray-400">
              {formatDate(intl, user.created_at)}
            </TableCell>
            <TableCell className="text-gray-600 dark:text-gray-400">
              {formatDate(intl, user.last_login)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
