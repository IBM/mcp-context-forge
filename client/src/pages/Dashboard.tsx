import { useState } from "react";
import { useIntl } from "react-intl";
import { ChartCard } from "@/components/metrics/ChartCard";
import { ExecutionsChart } from "@/components/metrics/ExecutionsChart";
import { LastUpdated } from "@/components/metrics/LastUpdated";
import { LatencyPercentilesChart } from "@/components/metrics/LatencyPercentilesChart";
import { TimeRangeSelector } from "@/components/metrics/TimeRangeSelector";
import { TokenSpendChart } from "@/components/metrics/TokenSpendChart";
import { useMetrics, type TimeWindow } from "@/hooks/useMetrics";
import { useTokenSpend } from "@/hooks/useTokenSpend";

export function Dashboard() {
  const intl = useIntl();
  const [window, setWindow] = useState<TimeWindow>("day");
  const { timeseries, percentiles, isLoading, error, lastUpdated, refetch } = useMetrics(window);
  const tokenSpend = useTokenSpend(window);

  // Loading is only "first load" — once we have data for any window, keep showing
  // it across window changes so the user sees the prior chart while the new one
  // is in flight.
  const showLoading = isLoading && !timeseries && !percentiles;
  const showTokenSpendLoading = tokenSpend.isLoading && !tokenSpend.data;

  const timeseriesEmpty = !!timeseries && timeseries.timestamps.length === 0;
  const percentilesEmpty = !!percentiles && percentiles.timestamps.length === 0;
  const tokenSpendEmpty = !!tokenSpend.data && tokenSpend.data.timestamps.length === 0;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <h1 className="text-xl font-semibold text-neutral-900 dark:text-neutral-100">
          {intl.formatMessage({ id: "dashboard.title" })}
        </h1>
        <div className="flex items-center gap-3">
          <TimeRangeSelector value={window} onChange={setWindow} />
          <LastUpdated value={lastUpdated} />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ChartCard
          title={intl.formatMessage({ id: "dashboard.charts.executions.title" })}
          isLoading={showLoading}
          error={error}
          isEmpty={timeseriesEmpty}
          onRetry={refetch}
        >
          {timeseries ? <ExecutionsChart data={timeseries} window={window} /> : null}
        </ChartCard>

        <ChartCard
          title={intl.formatMessage({ id: "dashboard.charts.latency.title" })}
          isLoading={showLoading}
          error={error}
          isEmpty={percentilesEmpty}
          onRetry={refetch}
        >
          {percentiles ? <LatencyPercentilesChart data={percentiles} window={window} /> : null}
        </ChartCard>

        <ChartCard
          title={intl.formatMessage({ id: "dashboard.charts.tokenSpend.title" })}
          isLoading={showTokenSpendLoading}
          error={tokenSpend.error}
          isEmpty={tokenSpendEmpty}
          onRetry={tokenSpend.refetch}
          className="lg:col-span-2"
          footer={intl.formatMessage({ id: "dashboard.charts.tokenSpend.footer.nonStreamingOnly" })}
        >
          {tokenSpend.data ? <TokenSpendChart data={tokenSpend.data} window={window} /> : null}
        </ChartCard>
      </div>
    </div>
  );
}
