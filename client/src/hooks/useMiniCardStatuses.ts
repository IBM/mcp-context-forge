/**
 * useMiniCardStatuses — gathers the data behind the home mini-card statuses and
 * the status headline, mapping the shared `/version` health signal to both the
 * pure `computeMiniCardStatuses` model and the `resolveHeadline` condition.
 *
 * Sources: `/version` (backend health, via useSystemHealth), cheap presence
 * probes for MCP servers and A2A agents, and recent activity for error/warning
 * counts. Activity is fetched once (no polling) to keep the resting home quiet;
 * it is empty until the activity backend (#5944) lands.
 *
 * `/version` is polled once here (the hook is resolved at the page level) and
 * feeds both the mini cards and the headline, so the home never double-polls the
 * diagnostics endpoint.
 */

import { useMemo } from "react";

import type { MiniCardId } from "@/components/dashboard/homeStates";
import {
  computeMiniCardStatuses,
  type MiniCardStatus,
} from "@/components/dashboard/miniCardStatus";
import type { HeadlineCondition } from "@/components/dashboard/resolveHeadline";
import { useQuery } from "@/hooks/useQuery";
import { useRecentActivity } from "@/hooks/useRecentActivity";
import { deriveMcpHealthy, useSystemHealth, type VersionInfo } from "@/hooks/useSystemHealth";

const MCP_PRESENCE_PATH = "/gateways?limit=1";
const A2A_PRESENCE_PATH = "/a2a?limit=1";

export interface HomeStatus {
  statuses: Record<MiniCardId, MiniCardStatus>;
  headlineCondition: HeadlineCondition;
}

/**
 * Health is "unknown" (null) until `/version` resolves, and stays unknown if the
 * payload is malformed — a bad diagnostics response must not crash the home.
 */
function safeHealthy(health: VersionInfo | undefined): boolean | null {
  if (!health) return null;
  try {
    return deriveMcpHealthy(health);
  } catch {
    return null;
  }
}

export function useMiniCardStatuses(): HomeStatus {
  const { data: health, error: healthError } = useSystemHealth();
  const { data: gateways } = useQuery<unknown[]>(MCP_PRESENCE_PATH);
  const { data: a2aAgents, error: a2aError } = useQuery<unknown[]>(A2A_PRESENCE_PATH);
  const { items } = useRecentActivity({ pollIntervalMs: 0 });

  return useMemo(() => {
    const healthy = safeHealthy(health);
    // undefined data = "still loading" -> null (unknown), so cards don't flash a
    // premature "Not configured" before the presence probe resolves. An A2A error
    // is a definitive "disabled/unavailable" -> not configured.
    const mcpConfigured = gateways === undefined ? null : gateways.length > 0;
    const a2aConfigured = a2aError ? false : a2aAgents === undefined ? null : a2aAgents.length > 0;
    // A `/version` response (any shape) means the backend is reachable -> Running.
    const systemRunning = health ? true : null;

    const statuses = computeMiniCardStatuses({
      systemRunning,
      mcpConfigured,
      a2aConfigured,
      healthy,
      errors: items.filter((item) => item.status === "error").length,
      warnings: items.filter((item) => item.status === "warning").length,
    });

    // Headline health axis, derived from the same `/version` query. A query
    // error is a definitive "unreachable"; loading (no data, no error) leaves
    // both fields undefined so the headline stays optimistic. `null` health
    // (loading or malformed) maps to `undefined`, not `false`.
    const headlineCondition: HeadlineCondition = {
      reachable: healthError ? false : health ? true : undefined,
      dependenciesHealthy: healthy ?? undefined,
    };

    return { statuses, headlineCondition };
  }, [health, healthError, gateways, a2aAgents, a2aError, items]);
}
