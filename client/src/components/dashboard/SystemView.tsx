/**
 * SystemView (#5942 / #5943) — the active-state main content of the System home
 * view. Composes the all-time stats card, the Virtual Servers card, and the
 * Components & ecosystem card.
 *
 * Data availability (all shippable today):
 * - `GET /metrics` → the four all-time scalars + the virtual-servers success
 *   rate/latency. Degrades to "—" if it fails (e.g. missing `admin.metrics`).
 * - list endpoints with `limit=0` → active/total and inventory counts.
 * - Plugins count is unavailable until #5667; REST/gRPC are honest zeros.
 *
 * Each list is fetched with `include_inactive=true` so totals reflect the full
 * inventory; `countActiveTotal` derives the active subset.
 */

import { useQuery } from "@/hooks/useQuery";

import { ComponentsEcosystemCard } from "./ComponentsEcosystemCard";
import { SystemStatsCard } from "./SystemStatsCard";
import {
  aggregateSystemStats,
  countActiveTotal,
  type Activatable,
  type MetricsResponse,
} from "./systemMetrics";
import { VirtualServersCard } from "./VirtualServersCard";

const METRICS_PATH = "/metrics";
const SERVERS_PATH = "/servers?limit=0&include_inactive=true";
const GATEWAYS_PATH = "/gateways?limit=0&include_inactive=true";
const A2A_PATH = "/a2a?limit=0&include_inactive=true";
const TOOLS_PATH = "/tools?limit=0&include_inactive=true";
const RESOURCES_PATH = "/resources?limit=0&include_inactive=true";
const PROMPTS_PATH = "/prompts?limit=0&include_inactive=true";

export function SystemView() {
  const { data: metrics, isLoading: metricsLoading } = useQuery<MetricsResponse>(METRICS_PATH);
  const { data: servers, isLoading: serversLoading } = useQuery<Activatable[]>(SERVERS_PATH);
  const { data: gateways, isLoading: gatewaysLoading } = useQuery<Activatable[]>(GATEWAYS_PATH);
  // A2A is feature-gated; an error here (feature disabled) leaves the row as "—".
  const { data: a2a } = useQuery<Activatable[]>(A2A_PATH);
  const { data: tools, isLoading: toolsLoading } = useQuery<unknown[]>(TOOLS_PATH);
  const { data: resources, isLoading: resourcesLoading } = useQuery<unknown[]>(RESOURCES_PATH);
  const { data: prompts, isLoading: promptsLoading } = useQuery<unknown[]>(PROMPTS_PATH);

  const systemStats = aggregateSystemStats(metrics);
  const serverMetrics = metrics?.servers ?? null;

  const componentsLoading = gatewaysLoading || toolsLoading || resourcesLoading || promptsLoading;

  return (
    <div className="flex flex-col gap-4">
      <SystemStatsCard stats={systemStats} loading={metricsLoading} />
      <div className="grid grid-cols-1 items-stretch gap-4 lg:grid-cols-3">
        <div className="h-full lg:col-span-1">
          <VirtualServersCard
            counts={servers ? countActiveTotal(servers) : null}
            failureRate={serverMetrics?.failureRate ?? null}
            avgResponseTime={serverMetrics?.avgResponseTime ?? null}
            loading={metricsLoading || serversLoading}
          />
        </div>
        <div className="h-full lg:col-span-2">
          <ComponentsEcosystemCard
            mcpServers={gateways ? countActiveTotal(gateways) : null}
            a2a={a2a ? countActiveTotal(a2a) : null}
            toolsCount={tools ? tools.length : null}
            resourcesCount={resources ? resources.length : null}
            promptsCount={prompts ? prompts.length : null}
            pluginsCount={null}
            loading={componentsLoading}
          />
        </div>
      </div>
    </div>
  );
}
