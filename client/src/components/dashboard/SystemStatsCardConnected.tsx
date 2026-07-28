/**
 * SystemStatsCardConnected — self-fetching wrapper around `SystemStatsCard`.
 *
 * Used where the card stands alone (the default/resting home state). The System
 * view composes `SystemStatsCard` directly instead, because it already fetches
 * `/metrics` once for the Virtual Servers card and passes it down.
 */

import { useQuery } from "@/hooks/useQuery";

import { SystemStatsCard } from "./SystemStatsCard";
import { aggregateSystemStats, type MetricsResponse } from "./systemMetrics";

const METRICS_PATH = "/metrics";

export function SystemStatsCardConnected() {
  const { data, isLoading } = useQuery<MetricsResponse>(METRICS_PATH);
  return <SystemStatsCard stats={aggregateSystemStats(data)} loading={isLoading} />;
}
