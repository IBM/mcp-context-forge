/**
 * StatusHeadline — the status-summary region (#5847 shell).
 *
 * Renders the message resolved by the rules mapping (`resolveHeadline`) with a
 * severity icon from a lookup table. The UI maps severity -> icon shape here; it
 * does not derive presentation strings (server-owns-presentation). `summary` and
 * `action` are slots the fuller #5847 / default-state content fills in.
 */

import { Activity, AlertTriangle, Info } from "lucide-react";
import type { ComponentType, ReactNode } from "react";
import { useIntl } from "react-intl";

import { cn } from "@/lib/utils";
import type { Severity } from "./homeStates";
import { resolveHeadline, type HeadlineCondition } from "./resolveHeadline";

const SEVERITY_ICON: Record<Severity, ComponentType<{ className?: string }>> = {
  success: Activity,
  info: Info,
  warning: AlertTriangle,
  error: AlertTriangle,
};

// Severity is conveyed by the icon shape and the message, not by colour: the
// status icon is always the brand-cyan accent (--status-icon / #70f9ff).
const STATUS_ICON_CLASS = "text-status-icon";

interface StatusHeadlineProps {
  condition?: HeadlineCondition;
  /** Prose summary slot (default-state summary sentence, once §9/#5847 lands). */
  summary?: ReactNode;
  /** Right-aligned action slot (e.g. the activity-feed button in the default state). */
  action?: ReactNode;
  className?: string;
}

export function StatusHeadline({ condition, summary, action, className }: StatusHeadlineProps) {
  const intl = useIntl();
  const { messageId, severity } = resolveHeadline(condition);
  const Icon = SEVERITY_ICON[severity];

  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-2">
          <Icon className={cn("size-5 shrink-0", STATUS_ICON_CLASS)} />
          <h1 className="font-heading text-lg font-medium text-foreground">
            {intl.formatMessage({ id: messageId })}
          </h1>
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
      {summary ? <div className="text-sm text-muted-foreground">{summary}</div> : null}
    </div>
  );
}
