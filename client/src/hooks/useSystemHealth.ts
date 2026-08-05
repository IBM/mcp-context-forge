/**
 * useSystemHealth (#5842).
 *
 * Reads the authenticated diagnostics endpoint `GET /version` (backend enforces
 * admin) for the MCP health card: overall reachability plus Postgres/Redis
 * dependency state. Polls modestly and pauses while the tab is hidden, to keep
 * the diagnostics endpoint's cost bounded.
 *
 * Only the subset of the `/version` payload the card needs is typed here; extra
 * fields on the response are ignored.
 */

import { useEffect } from "react";

import { useQuery } from "@/hooks/useQuery";

export interface VersionInfo {
  app?: { name?: string; version?: string; mcp_protocol_version?: string };
  database: { dialect: string; reachable: boolean; server_version: string | null };
  redis: { available: boolean; reachable: boolean; server_version: string | null };
  settings: { cache_type: string };
}

/** Request JSON explicitly (/version content-negotiates HTML otherwise). */
const VERSION_HEADERS: Record<string, string> = { Accept: "application/json" };

export const SYSTEM_HEALTH_POLL_INTERVAL_MS = 60_000;

/**
 * @param pollIntervalMs - Poll cadence; <= 0 disables polling (initial fetch still runs).
 * @param enabled - When false, no request is made at all. Callers use this to
 *   fetch-gate `/version` (admin-only) so non-admins never spam it with 403s.
 */
export function useSystemHealth(
  pollIntervalMs: number = SYSTEM_HEALTH_POLL_INTERVAL_MS,
  enabled: boolean = true,
) {
  const query = useQuery<VersionInfo>(enabled ? "/version" : null, { headers: VERSION_HEADERS });
  const { refetch } = query;

  useEffect(() => {
    if (!enabled || pollIntervalMs <= 0) return;

    const tick = () => {
      // Pause polling while the tab is hidden.
      if (typeof document !== "undefined" && document.hidden) return;
      void refetch().catch(() => {
        /* error surfaced via query.error */
      });
    };

    const id = setInterval(tick, pollIntervalMs);
    const onVisible = () => {
      if (typeof document !== "undefined" && !document.hidden) tick();
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [enabled, pollIntervalMs, refetch]);

  return query;
}

/** The `useSystemHealth` result, exposed so a parent can share one poll. */
export type SystemHealthResult = ReturnType<typeof useSystemHealth>;

/**
 * Redis is only a required dependency when it is the configured cache backend.
 * Overall health is DB reachability plus Redis reachability when Redis is in use.
 */
export function deriveMcpHealthy(info: VersionInfo): boolean {
  const redisRequired = info.settings.cache_type === "redis";
  return info.database.reachable && (!redisRequired || info.redis.reachable);
}

export function isRedisConfigured(info: VersionInfo): boolean {
  // `redis.available` only means the Python library is installed, not that Redis
  // is the configured backend. Gate on cache_type, matching /version's own probe
  // (it never marks Redis reachable unless cache_type === "redis") and
  // deriveMcpHealthy above; otherwise the chip shows a spurious red dot.
  return info.settings.cache_type === "redis";
}
