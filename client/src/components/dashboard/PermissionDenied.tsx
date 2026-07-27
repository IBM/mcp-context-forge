/**
 * PermissionDenied — shared empty state for a card whose data the caller is not
 * authorized to see. Rendered when a gated card is shown but the endpoint 403s
 * (stale/coarser client permissions, or a team-switch race), or when a gate
 * fails closed. Never crashes; shows generic copy (never a raw server body).
 */

import { Lock } from "lucide-react";
import { useIntl } from "react-intl";

import { ApiError } from "@/api/client";
import { cn } from "@/lib/utils";

/** True when an error is a 403 from the API (insufficient permissions). */
export function isPermissionDenied(err: unknown): boolean {
  return err instanceof ApiError && err.status === 403;
}

interface PermissionDeniedProps {
  /** i18n message id; defaults to generic insufficient-permission copy. */
  messageId?: string;
  className?: string;
}

export function PermissionDenied({
  messageId = "dashboard.home.permissionDenied",
  className,
}: PermissionDeniedProps) {
  const intl = useIntl();
  return (
    <div
      className={cn(
        "flex items-center gap-2 rounded-lg bg-muted/40 px-6 py-8 text-sm text-muted-foreground ring-1 ring-foreground/10",
        className,
      )}
    >
      <Lock className="size-4 shrink-0" />
      {intl.formatMessage({ id: messageId })}
    </div>
  );
}
