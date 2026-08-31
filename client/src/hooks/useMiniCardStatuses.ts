/**
 * useMiniCardStatuses — gathers the data behind the home mini-card statuses and
 * the status headline, mapping the shared `/version` health signal to both the
 * pure `computeMiniCardStatuses` model and the `resolveHeadline` condition.
 *
 * Sources: `/version` (backend health, via useSystemHealth), reachability
 * probes for MCP servers (`/gateways`) and A2A agents (`/a2a`), and recent
 * activity for error/warning counts. Activity is fetched once (no polling) to
 * keep the resting home quiet; it is empty until the activity backend (#5944)
 * lands.
 *
 * `/version` is admin-only, so it is fetched only when the caller can view
 * system diagnostics (`admin.system_config`); non-admins never poll a guaranteed
 * 403. It is polled once here (the hook is resolved at the page level) and feeds
 * both the mini cards and the headline.
 */

import { useMemo } from "react";

import { useAuth } from "@/auth/useAuth";
import type { MiniCardId } from "@/components/dashboard/homeStates";
import {
  computeMiniCardStatuses,
  type MiniCardStatus,
} from "@/components/dashboard/miniCardStatus";
import type { HeadlineCondition } from "@/components/dashboard/resolveHeadline";
import { countActiveTotal, type Activatable } from "@/components/dashboard/systemMetrics";
import { useQuery } from "@/hooks/useQuery";
import { useRecentActivity } from "@/hooks/useRecentActivity";
import {
  deriveMcpHealthy,
  useSystemHealth,
  type SystemHealthResult,
  type VersionInfo,
} from "@/hooks/useSystemHealth";
import type { ServersResponse } from "@/types/server";

// Reachability only needs each instance's `reachable` flag. Gateways come back
// in the paginated `{ gateways: [...] }` shape (matching useMcpServers); A2A is a
// bare list. Capped at 100 like the roster; a reachable instance past position
// 100 is not counted.
const MCP_REACH_PATH = "/gateways?limit=100&include_pagination=true";
const A2A_REACH_PATH = "/a2a?limit=100";

export interface HomeStatus {
  statuses: Record<MiniCardId, MiniCardStatus>;
  headlineCondition: HeadlineCondition;
  /**
   * The shared `/version` query, exposed so the mcp view's McpHealthCard can
   * reuse it instead of polling the diagnostics endpoint a second time.
   */
  systemHealth: SystemHealthResult;
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
  const { hasPermission } = useAuth();
  // `/version` is admin-only; only fetch it when the caller may see diagnostics,
  // so non-admins never poll a guaranteed 403 (and the headline never reads a
  // permission 403 as "system down").
  const canViewSystem = hasPermission("admin.system_config");
  const systemHealth = useSystemHealth(undefined, canViewSystem);
  const { data: health, error: healthError } = systemHealth;
  const { data: mcpServers, error: mcpServersError } = useQuery<ServersResponse>(MCP_REACH_PATH);
  const { data: a2aAgents, error: a2aError } = useQuery<Activatable[]>(A2A_REACH_PATH);
  const { items } = useRecentActivity({ pollIntervalMs: 0 });

  const derived = useMemo(() => {
    const healthy = safeHealthy(health);

    // Two-tone reachability dots (green = something reachable, grey = everything
    // else), matching the MCP roster. A source is reachable when it has at least
    // one enabled + reachable instance (`countActiveTotal` counts those, and is
    // safe against a non-array/loading response). The system is reachable once
    // any probe returns, which works for non-admins who cannot fetch the
    // admin-only /version.
    const mcpReachable = countActiveTotal(mcpServers?.gateways).active > 0;
    const a2aReachable = countActiveTotal(a2aAgents).active > 0;
    // The backend is reachable once any probe gets a response: data, or an HTTP
    // error (`error.status` set — a 403/404 still means the server answered). A
    // network failure (no status) is the only genuine "unreachable".
    const systemReachable =
      Boolean(health) ||
      mcpServers !== undefined ||
      a2aAgents !== undefined ||
      mcpServersError?.status != null ||
      a2aError?.status != null;

    const statuses = computeMiniCardStatuses({
      systemReachable,
      mcpReachable,
      a2aReachable,
      errors: items.filter((item) => item.status === "error").length,
      warnings: items.filter((item) => item.status === "warning").length,
    });

    // Headline health axis, derived from the same `/version` query. Prefer the
    // last-known health over a transient refetch error (useQuery keeps `data` on
    // error), so a blip never flips the headline to an error state. Only report
    // "unreachable" when there is no data AND a definitive, non-permission error;
    // a 403 (caller can't see diagnostics) and loading both stay optimistic.
    const definitiveError = healthError != null && healthError.status !== 403;
    const headlineCondition: HeadlineCondition = {
      reachable: health ? true : definitiveError ? false : undefined,
      dependenciesHealthy: healthy ?? undefined,
    };

    return { statuses, headlineCondition };
  }, [health, healthError, mcpServers, mcpServersError, a2aAgents, a2aError, items]);

  return { ...derived, systemHealth };
}
