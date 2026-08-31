/**
 * useMcpServers (#5842).
 *
 * Polls `GET /gateways` (React "MCP servers") for the home MCP reachability
 * roster. Includes inactive servers so the roster can show disabled rows, and
 * requests pagination metadata for the structured `{ gateways: [...] }` shape.
 *
 * Polls modestly and pauses while the tab is hidden (mirrors `useSystemHealth`),
 * and tracks `lastUpdated` so the card can render a "Refreshed Xs ago" hint.
 *
 * The backend RBAC-scopes `/gateways` (`gateways.read` + token-team scoping), so
 * a scoped caller only ever sees their own servers and a caller without
 * `gateways.read` gets a 403 the card surfaces as PermissionDenied.
 */

import { useEffect, useState } from "react";

import { useQuery } from "@/hooks/useQuery";
import type { MCPServer, ServersResponse } from "@/types/server";

// limit is clamped to 100 server-side (see api/servers.ts); fleets larger than
// 100 undercount until pagination is added. Adequate for the home summary today.
const MCP_SERVERS_PATH = "/gateways?limit=100&include_inactive=true&include_pagination=true";

export const MCP_SERVERS_POLL_INTERVAL_MS = 60_000;

export interface UseMcpServersResult {
  servers: MCPServer[] | undefined;
  error: ReturnType<typeof useQuery<ServersResponse>>["error"];
  isLoading: boolean;
  /** Epoch millis of the last successful load, or null before the first one. */
  lastUpdated: number | null;
}

export function useMcpServers(
  pollIntervalMs: number = MCP_SERVERS_POLL_INTERVAL_MS,
): UseMcpServersResult {
  const query = useQuery<ServersResponse>(MCP_SERVERS_PATH);
  const { data, refetch } = query;
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);

  useEffect(() => {
    if (data) setLastUpdated(Date.now());
  }, [data]);

  useEffect(() => {
    if (pollIntervalMs <= 0) return;

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
  }, [pollIntervalMs, refetch]);

  return {
    servers: data?.gateways,
    error: query.error,
    isLoading: query.isLoading,
    lastUpdated,
  };
}
