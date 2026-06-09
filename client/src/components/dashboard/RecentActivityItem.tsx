import { AlertTriangle, CheckCircle2, CircleX, Info } from "lucide-react";
import type { ComponentType, SVGProps } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { cn } from "@/lib/utils";
import type { ActivityItem, ActivityStatus } from "@/types/activity";

type AlertVariant = "default" | "destructive" | "success" | "warning" | "info" | "error";
type IconComponent = ComponentType<SVGProps<SVGSVGElement>>;

const STATUS_PRESENTATION: Record<ActivityStatus, { variant: AlertVariant; Icon: IconComponent }> =
  {
    success: { variant: "success", Icon: CheckCircle2 },
    info: { variant: "info", Icon: Info },
    warning: { variant: "warning", Icon: AlertTriangle },
    error: { variant: "error", Icon: CircleX },
  };

function formatTimestamp(iso: string): string {
  // Mockup shows the ISO timestamp truncated at seconds (no trailing Z) —
  // also the most copy/paste-friendly form for an operator scanning the feed.
  return iso.replace(/(\.\d+)?Z?$/, "").slice(0, 19);
}

export function RecentActivityItem({ item }: { item: ActivityItem }) {
  const { variant, Icon } = STATUS_PRESENTATION[item.status];

  return (
    <Alert
      variant={variant}
      data-testid={`activity-item-${item.id}`}
      className={cn(
        "items-start gap-x-3 rounded-md border-border/40 bg-muted/30 px-4 py-2.5",
        "has-[>svg]:grid-cols-[auto_1fr_auto] has-[>svg]:gap-x-3",
      )}
    >
      <Icon aria-hidden="true" />
      <AlertTitle className="col-start-2 row-start-1 text-foreground">{item.title}</AlertTitle>
      <time
        dateTime={item.timestamp}
        className="col-start-3 row-start-1 self-start pl-4 text-xs whitespace-nowrap text-muted-foreground tabular-nums"
      >
        {formatTimestamp(item.timestamp)}
      </time>
      <AlertDescription className="col-span-2 col-start-2 row-start-2">
        {item.description}
      </AlertDescription>
    </Alert>
  );
}
