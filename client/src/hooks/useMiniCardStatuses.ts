/**
 * useMiniCardStatuses — gathers the data behind the home mini-card statuses and
 * maps it to the pure `computeMiniCardStatuses` model.
 *
 * Sources: `/version` (backend health, via useSystemHealth), cheap presence
 * probes for MCP servers and A2A agents, and recent activity for error/warning
 * counts. Activity is fetched once (no polling) to keep the resting home quiet;
 * it is empty until the activity backend (#5944) lands.
 */

import { useMemo } from "react";

import type { MiniCardId } from "@/components/dashboard/homeStates";
import {
  computeMiniCardStatuses,
  type MiniCardStatus,
} from "@/components/dashboard/miniCardStatus";
import { useQuery } from "@/hooks/useQuery";
import { useRecentActivity } from "@/hooks/useRecentActivity";
import { deriveMcpHealthy, useSystemHealth, type VersionInfo } from "@/hooks/useSystemHealth";

const MCP_PRESENCE_PATH = "/gateways?limit=1";
const A2A_PRESENCE_PATH = "/a2a?limit=1";

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

export function useMiniCardStatuses(): Record<MiniCardId, MiniCardStatus> {
  const { data: health } = useSystemHealth();
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
    return computeMiniCardStatuses({
      systemRunning,
      mcpConfigured,
      a2aConfigured,
      healthy,
      errors: items.filter((item) => item.status === "error").length,
      warnings: items.filter((item) => item.status === "warning").length,
    });
  }, [health, gateways, a2aAgents, a2aError, items]);
}
