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
  const { hasPermission } = useAuth();
  // `/version` is admin-only; only fetch it when the caller may see diagnostics,
  // so non-admins never poll a guaranteed 403 (and the headline never reads a
  // permission 403 as "system down").
  const canViewSystem = hasPermission("admin.system_config");
  const { data: health, error: healthError } = useSystemHealth(undefined, canViewSystem);
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
  }, [health, healthError, gateways, a2aAgents, a2aError, items]);
}
