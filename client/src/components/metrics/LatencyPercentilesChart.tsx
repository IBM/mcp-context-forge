import { useMemo } from "react";
import { useIntl } from "react-intl";
import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import type { PercentilesResponse } from "@/api/metrics";
import type { TimeWindow } from "@/hooks/useMetrics";
import { formatBucketTick } from "./formatBucket";

interface LatencyPercentilesChartProps {
  data: PercentilesResponse;
  window: TimeWindow;
}

export function LatencyPercentilesChart({ data, window }: LatencyPercentilesChartProps) {
  const intl = useIntl();

  const config = useMemo<ChartConfig>(
    () => ({
      p50: {
        label: intl.formatMessage({ id: "dashboard.charts.latency.p50" }),
        color: "var(--color-chart-latency-p50)",
      },
      p95: {
        label: intl.formatMessage({ id: "dashboard.charts.latency.p95" }),
        color: "var(--color-chart-latency-p95)",
      },
      p99: {
        label: intl.formatMessage({ id: "dashboard.charts.latency.p99" }),
        color: "var(--color-chart-latency-p99)",
      },
    }),
    [intl],
  );

  const chartData = useMemo(
    () =>
      data.timestamps.map((timestamp, i) => ({
        timestamp,
        p50: data.p50[i] ?? 0,
        p95: data.p95[i] ?? 0,
        p99: data.p99[i] ?? 0,
      })),
    [data],
  );

  return (
    <ChartContainer config={config} className="h-[260px] w-full">
      <LineChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid vertical={false} />
        <XAxis
          dataKey="timestamp"
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          minTickGap={32}
          tickFormatter={(value: string) => formatBucketTick(value, window)}
        />
        <YAxis
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          width={48}
          unit="ms"
          allowDecimals={false}
        />
        <ChartTooltip content={<ChartTooltipContent />} />
        <ChartLegend content={<ChartLegendContent />} />
        <Line
          dataKey="p50"
          type="linear"
          stroke="var(--color-p50)"
          strokeWidth={2}
          dot={false}
          isAnimationActive={false}
        />
        <Line
          dataKey="p95"
          type="linear"
          stroke="var(--color-p95)"
          strokeWidth={2}
          dot={false}
          isAnimationActive={false}
        />
        <Line
          dataKey="p99"
          type="linear"
          stroke="var(--color-p99)"
          strokeWidth={2}
          dot={false}
          isAnimationActive={false}
        />
      </LineChart>
    </ChartContainer>
  );
}
