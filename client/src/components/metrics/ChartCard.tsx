import type { ReactNode } from "react";
import { useIntl } from "react-intl";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

interface ChartCardProps {
  title: string;
  /** True when first load is in-flight and there is no prior data to show. */
  isLoading: boolean;
  error: Error | null;
  /** True when the response succeeded but no buckets came back. */
  isEmpty: boolean;
  onRetry: () => void;
  children: ReactNode;
  /** Extra classes forwarded to the outer Card (e.g. `lg:col-span-2` in a grid). */
  className?: string;
  /** Optional caption rendered under the chart body — for coverage caveats
   *  or scope notes that stay visible when the chart is populated. */
  footer?: ReactNode;
}

export function ChartCard({
  title,
  isLoading,
  error,
  isEmpty,
  onRetry,
  children,
  className,
  footer,
}: ChartCardProps) {
  const intl = useIntl();

  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent className="px-6 pb-6">
        {isLoading ? (
          <Skeleton className="aspect-video w-full" />
        ) : error ? (
          <div className="flex aspect-video flex-col items-center justify-center gap-3 text-center">
            <p className="text-sm text-muted-foreground">
              {intl.formatMessage({ id: "dashboard.charts.error" })}
            </p>
            <Button variant="outline" size="sm" onClick={onRetry}>
              {intl.formatMessage({ id: "dashboard.charts.retry" })}
            </Button>
          </div>
        ) : isEmpty ? (
          <div className="flex aspect-video flex-col items-center justify-center gap-1 px-4 text-center">
            <p className="text-sm text-muted-foreground">
              {intl.formatMessage({ id: "dashboard.charts.empty.message" })}
            </p>
            <p className="text-xs text-muted-foreground">
              {intl.formatMessage({ id: "dashboard.charts.empty.hint" })}
            </p>
          </div>
        ) : (
          children
        )}
        {footer ? <p className="mt-3 text-xs text-muted-foreground">{footer}</p> : null}
      </CardContent>
    </Card>
  );
}
