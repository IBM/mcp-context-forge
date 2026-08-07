/**
 * ComponentsEcosystemCard (#5943) — inventory of the platform's building blocks.
 *
 * Sources (all list-count based, `limit=0`):
 * - MCP servers / A2A: active-of-total from `GET /gateways` and `GET /a2a`.
 * - Tools / Resources / Prompts: registered counts.
 * - REST API / gRPC: honest zeros (transport not built yet).
 * - Plugins: unavailable ("—") until the `GET /v1/plugins` backend (#5667) ships.
 *
 * A2A counts are unavailable when the feature is disabled; that row falls back
 * to "—" rather than a misleading zero.
 */

import { useIntl } from "react-intl";

import { formatCount, UNAVAILABLE, type ActiveTotal } from "./systemMetrics";
import { StatRow } from "./SystemStat";

interface ComponentsEcosystemCardProps {
  mcpServers: ActiveTotal | null;
  a2a: ActiveTotal | null;
  toolsCount: number | null;
  resourcesCount: number | null;
  promptsCount: number | null;
  /** Null until the plugins-count backend (#5667) exists. */
  pluginsCount: number | null;
  loading?: boolean;
}

export function ComponentsEcosystemCard({
  mcpServers,
  a2a,
  toolsCount,
  resourcesCount,
  promptsCount,
  pluginsCount,
  loading,
}: ComponentsEcosystemCardProps) {
  const intl = useIntl();

  const activeOfTotal = (counts: ActiveTotal | null): string =>
    counts
      ? intl.formatMessage(
          { id: "dashboard.home.system.activeOfTotal" },
          { active: counts.active, total: counts.total },
        )
      : UNAVAILABLE;

  return (
    <div className="flex h-full flex-col gap-4 rounded-lg bg-card px-5 py-4 shadow-xs ring-1 ring-foreground/10">
      <h2 className="font-heading text-sm font-semibold leading-5 text-secondary-foreground">
        {intl.formatMessage({ id: "dashboard.home.system.components" })}
      </h2>
      <div className="grid grid-cols-1 gap-x-8 gap-y-3 sm:grid-cols-2">
        <StatRow
          label={intl.formatMessage({ id: "dashboard.home.system.mcpServers" })}
          value={activeOfTotal(mcpServers)}
          loading={loading}
        />
        <StatRow
          label={intl.formatMessage({ id: "dashboard.home.system.tools" })}
          value={formatCount(toolsCount)}
          loading={loading}
        />
        <StatRow
          label={intl.formatMessage({ id: "dashboard.home.system.a2a" })}
          value={activeOfTotal(a2a)}
          loading={loading}
        />
        <StatRow
          label={intl.formatMessage({ id: "dashboard.home.system.resources" })}
          value={formatCount(resourcesCount)}
          loading={loading}
        />
        <StatRow
          label={intl.formatMessage({ id: "dashboard.home.system.rest" })}
          value={formatCount(0)}
          loading={loading}
        />
        <StatRow
          label={intl.formatMessage({ id: "dashboard.home.system.prompts" })}
          value={formatCount(promptsCount)}
          loading={loading}
        />
        <StatRow
          label={intl.formatMessage({ id: "dashboard.home.system.grpc" })}
          value={formatCount(0)}
          loading={loading}
        />
        <StatRow
          label={intl.formatMessage({ id: "dashboard.home.system.plugins" })}
          value={formatCount(pluginsCount)}
          loading={loading}
        />
      </div>
    </div>
  );
}
