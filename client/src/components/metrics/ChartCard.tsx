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
}

export function ChartCard({ title, isLoading, error, isEmpty, onRetry, children }: ChartCardProps) {
  const intl = useIntl();

  return (
    <Card>
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
      </CardContent>
    </Card>
  );
}
