/**
 * RecentActivityItem — one activity feed row (#5531).
 *
 * A clean divider row: a status icon, the title with the timestamp on the same
 * line, and the description beneath. The UI maps the server-owned `status` to an
 * icon + tone through STATUS_PRESENTATION only; it never derives presentation
 * from other fields.
 */

import { AlertTriangle, CircleCheck, CircleX, Info } from "lucide-react";
import type { ComponentType, SVGProps } from "react";

import { cn } from "@/lib/utils";
import type { ActivityItem, ActivityStatus } from "@/types/activity";

type IconComponent = ComponentType<SVGProps<SVGSVGElement>>;

const STATUS_PRESENTATION: Record<ActivityStatus, { Icon: IconComponent; className: string }> = {
  success: { Icon: CircleCheck, className: "text-emerald-500" },
  info: { Icon: Info, className: "text-sky-500" },
  warning: { Icon: AlertTriangle, className: "text-amber-500" },
  error: { Icon: CircleX, className: "text-destructive" },
};

function formatTimestamp(iso: string): string {
  // ISO truncated at seconds (no trailing Z): compact and copy/paste-friendly.
  return iso.replace(/(\.\d+)?Z?$/, "").slice(0, 19);
}

export function RecentActivityItem({ item }: { item: ActivityItem }) {
  const { Icon, className } = STATUS_PRESENTATION[item.status];

  return (
    <div
      data-testid={`activity-item-${item.id}`}
      className="grid grid-cols-[auto_1fr_auto] items-start gap-x-3 border-b border-border/60 py-3 last:border-b-0"
    >
      <Icon aria-hidden="true" className={cn("mt-0.5 size-4 shrink-0", className)} />
      <div className="min-w-0 space-y-0.5">
        <p className="text-sm text-foreground">{item.title}</p>
        <p className="text-xs text-muted-foreground">{item.description}</p>
      </div>
      <time
        dateTime={item.timestamp}
        className="pl-4 text-xs whitespace-nowrap text-muted-foreground tabular-nums"
      >
        {formatTimestamp(item.timestamp)}
      </time>
    </div>
  );
}
