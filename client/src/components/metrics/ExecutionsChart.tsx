import { useMemo } from "react";
import { useIntl } from "react-intl";
import { Area, AreaChart, CartesianGrid, XAxis, YAxis } from "recharts";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import type { TimeseriesResponse } from "@/api/metrics";
import type { TimeWindow } from "@/hooks/useMetrics";
import { formatBucketTick } from "./formatBucket";

interface ExecutionsChartProps {
  data: TimeseriesResponse;
  window: TimeWindow;
}

export function ExecutionsChart({ data, window }: ExecutionsChartProps) {
  const intl = useIntl();

  const config = useMemo<ChartConfig>(
    () => ({
      request_count: {
        label: intl.formatMessage({ id: "dashboard.charts.executions.yAxis" }),
        color: "var(--color-chart-volume)",
      },
    }),
    [intl],
  );

  const chartData = useMemo(
    () =>
      data.timestamps.map((timestamp, i) => ({
        timestamp,
        request_count: data.request_count[i] ?? 0,
      })),
    [data],
  );

  return (
    <ChartContainer config={config} className="h-[260px] w-full">
      <AreaChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid vertical={false} />
        <XAxis
          dataKey="timestamp"
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          minTickGap={32}
          tickFormatter={(value: string) => formatBucketTick(value, window)}
        />
        <YAxis tickLine={false} axisLine={false} tickMargin={8} width={40} allowDecimals={false} />
        <ChartTooltip content={<ChartTooltipContent />} />
        <Area
          dataKey="request_count"
          type="linear"
          stroke="var(--color-request_count)"
          fill="var(--color-request_count)"
          fillOpacity={0.2}
          strokeWidth={2}
          isAnimationActive={false}
        />
      </AreaChart>
    </ChartContainer>
  );
}
