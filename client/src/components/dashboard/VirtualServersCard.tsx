/**
 * VirtualServersCard (#5942) — reliability summary for virtual servers.
 *
 * - Active/total comes from `GET /servers` (counted client-side).
 * - Success rate + latency come from the `servers` aggregate in `GET /metrics`,
 *   pooled across all virtual servers and all-time (see `systemMetrics.ts`).
 */

import { useIntl } from "react-intl";

import {
  formatResponseTime,
  formatSuccessRate,
  UNAVAILABLE,
  type ActiveTotal,
} from "./systemMetrics";
import { StatRow } from "./SystemStat";

interface VirtualServersCardProps {
  counts: ActiveTotal | null;
  /** `failureRate` in [0, 1] from the servers metrics aggregate, or null. */
  failureRate: number | null;
  /** `avgResponseTime` from the servers metrics aggregate, or null. */
  avgResponseTime: number | null;
  loading?: boolean;
}

export function VirtualServersCard({
  counts,
  failureRate,
  avgResponseTime,
  loading,
}: VirtualServersCardProps) {
  const intl = useIntl();

  const activeValue = counts
    ? intl.formatMessage(
        { id: "dashboard.home.system.activeCount" },
        { active: counts.active, total: counts.total },
      )
    : UNAVAILABLE;

  return (
    <div className="flex h-full flex-col gap-4 rounded-lg bg-card px-5 py-4 shadow-xs ring-1 ring-foreground/10">
      <h2 className="font-heading text-sm font-semibold leading-5 text-secondary-foreground">
        {intl.formatMessage({ id: "dashboard.home.system.virtualServers" })}
      </h2>
      <div className="flex flex-col gap-3">
        <StatRow
          label={intl.formatMessage({ id: "dashboard.home.system.active" })}
          value={activeValue}
          loading={loading}
        />
        <StatRow
          label={intl.formatMessage({ id: "dashboard.home.system.successRate" })}
          value={formatSuccessRate(failureRate)}
          loading={loading}
        />
        <StatRow
          label={intl.formatMessage({ id: "dashboard.home.system.latency" })}
          value={formatResponseTime(avgResponseTime)}
          loading={loading}
        />
      </div>
    </div>
  );
}
