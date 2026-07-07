import { useMemo } from "react";
import { useIntl } from "react-intl";
import { Bar, CartesianGrid, ComposedChart, Line, XAxis, YAxis } from "recharts";
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import type { TokenSpendResponse } from "@/api/metrics";
import type { TimeWindow } from "@/hooks/useMetrics";
import { formatBucketTick } from "./formatBucket";

interface TokenSpendChartProps {
  data: TokenSpendResponse;
  window: TimeWindow;
}

// Compact abbreviation for the left (tokens) Y-axis: 1200 → "1.2K", 3_400_000 → "3.4M".
// Uses Intl.NumberFormat's "compact" notation so it localizes automatically.
function makeTokensTickFormatter(locale: string): (value: number) => string {
  const fmt = new Intl.NumberFormat(locale, { notation: "compact", maximumFractionDigits: 1 });
  return (value: number) => fmt.format(value);
}

export function TokenSpendChart({ data, window }: TokenSpendChartProps) {
  const intl = useIntl();

  const config = useMemo<ChartConfig>(
    () => ({
      input_tokens: {
        label: intl.formatMessage({ id: "dashboard.charts.tokenSpend.legend.input" }),
        color: "var(--color-chart-tokens-input)",
      },
      output_tokens: {
        label: intl.formatMessage({ id: "dashboard.charts.tokenSpend.legend.output" }),
        color: "var(--color-chart-tokens-output)",
      },
      cost_usd: {
        label: intl.formatMessage({ id: "dashboard.charts.tokenSpend.legend.cost" }),
        color: "var(--color-chart-cost)",
      },
    }),
    [intl],
  );

  const chartData = useMemo(
    () =>
      data.timestamps.map((timestamp, i) => ({
        timestamp,
        input_tokens: data.input_tokens[i] ?? 0,
        output_tokens: data.output_tokens[i] ?? 0,
        cost_usd: data.cost_usd[i] ?? 0,
      })),
    [data],
  );

  const formatTokens = useMemo(() => makeTokensTickFormatter(intl.locale), [intl.locale]);
  const formatCost = useMemo(
    () => (value: number) =>
      intl.formatNumber(value, {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: value < 1 ? 4 : 2,
      }),
    [intl],
  );

  return (
    <ChartContainer config={config} className="h-[260px] w-full">
      <ComposedChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
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
          yAxisId="tokens"
          orientation="left"
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          width={48}
          allowDecimals={false}
          tickFormatter={formatTokens}
        />
        <YAxis
          yAxisId="cost"
          orientation="right"
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          width={64}
          tickFormatter={formatCost}
        />
        <ChartTooltip content={<ChartTooltipContent />} />
        <ChartLegend content={<ChartLegendContent />} />
        <Bar
          yAxisId="tokens"
          dataKey="input_tokens"
          stackId="tokens"
          fill="var(--color-input_tokens)"
          isAnimationActive={false}
        />
        <Bar
          yAxisId="tokens"
          dataKey="output_tokens"
          stackId="tokens"
          fill="var(--color-output_tokens)"
          isAnimationActive={false}
        />
        <Line
          yAxisId="cost"
          dataKey="cost_usd"
          type="linear"
          stroke="var(--color-cost_usd)"
          strokeWidth={2}
          dot={false}
          isAnimationActive={false}
        />
      </ComposedChart>
    </ChartContainer>
  );
}
