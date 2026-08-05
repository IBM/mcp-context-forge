/**
 * SystemStatsCard (#5841 interim) — the top card of the System view.
 *
 * Shows the four all-time scalars combined from `GET /metrics`: total executions
 * and the min/avg/max response time across every entity type. These are
 * cumulative lifetime figures, not a rolling window (see `systemMetrics.ts`).
 */

import { useIntl } from "react-intl";

import { formatCount, formatResponseTime, type SystemStats } from "./systemMetrics";
import { StatBlock } from "./SystemStat";

interface SystemStatsCardProps {
  stats: SystemStats | null;
  loading?: boolean;
}

export function SystemStatsCard({ stats, loading }: SystemStatsCardProps) {
  const intl = useIntl();

  return (
    <div className="rounded-lg bg-card px-5 py-4 shadow-xs ring-1 ring-foreground/10">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatBlock
          label={intl.formatMessage({ id: "dashboard.home.system.executions" })}
          value={formatCount(stats?.executions)}
          loading={loading}
        />
        <StatBlock
          label={intl.formatMessage({ id: "dashboard.home.system.maxResponseTime" })}
          value={formatResponseTime(stats?.maxResponseTime)}
          loading={loading}
        />
        <StatBlock
          label={intl.formatMessage({ id: "dashboard.home.system.avgResponseTime" })}
          value={formatResponseTime(stats?.avgResponseTime)}
          loading={loading}
        />
        <StatBlock
          label={intl.formatMessage({ id: "dashboard.home.system.minResponseTime" })}
          value={formatResponseTime(stats?.minResponseTime)}
          loading={loading}
        />
      </div>
    </div>
  );
}
