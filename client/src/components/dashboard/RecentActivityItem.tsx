import { AlertTriangle, CheckCircle2, CircleX, Info } from "lucide-react";
import type { ComponentType, SVGProps } from "react";

import { Alert, AlertAction, AlertDescription, AlertTitle } from "@/components/ui/alert";
import type { ActivityItem, ActivityStatus } from "@/types/activity";

type AlertVariant = "default" | "destructive" | "success" | "warning" | "info";
type IconComponent = ComponentType<SVGProps<SVGSVGElement>>;

const STATUS_PRESENTATION: Record<ActivityStatus, { variant: AlertVariant; Icon: IconComponent }> =
  {
    success: { variant: "success", Icon: CheckCircle2 },
    info: { variant: "info", Icon: Info },
    warning: { variant: "warning", Icon: AlertTriangle },
    error: { variant: "destructive", Icon: CircleX },
  };

function formatTimestamp(iso: string): string {
  // The mockup shows the ISO timestamp truncated at seconds (no trailing Z),
  // which is also the most copy/paste-friendly format for an operator's eye.
  return iso.replace(/(\.\d+)?Z?$/, "").slice(0, 19);
}

export function RecentActivityItem({ item }: { item: ActivityItem }) {
  const { variant, Icon } = STATUS_PRESENTATION[item.status];

  return (
    <Alert variant={variant} data-testid={`activity-item-${item.id}`}>
      <Icon aria-hidden="true" />
      <AlertTitle>{item.title}</AlertTitle>
      <AlertDescription>{item.description}</AlertDescription>
      <AlertAction className="static top-auto right-auto col-start-2 row-start-1 self-start justify-self-end pl-4 text-xs whitespace-nowrap text-muted-foreground tabular-nums">
        <time dateTime={item.timestamp}>{formatTimestamp(item.timestamp)}</time>
      </AlertAction>
    </Alert>
  );
}
