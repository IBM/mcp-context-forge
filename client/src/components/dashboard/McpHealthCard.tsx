/**
 * McpHealthCard (#5842).
 *
 * Durable MCP health view: overall Healthy/Unhealthy plus Postgres/Redis
 * dependency chips, sourced from the authenticated `GET /version` diagnostics
 * endpoint. Reframed from the deprecated Rust "MCP runtime" card: no runtime
 * cores and no transport badge (the Rust MCP runtime sunset on 2026-07-07).
 *
 * The endpoint enforces admin server-side; the mcp view already gates its
 * render on real permissions. A 403 here (e.g. a permission race) falls back to
 * PermissionDenied rather than a crash.
 */

import { useIntl } from "react-intl";

import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { deriveMcpHealthy, isRedisConfigured, useSystemHealth } from "@/hooks/useSystemHealth";
import { PermissionDenied } from "./PermissionDenied";
import { StatusDot } from "./StatusDot";

export function McpHealthCard() {
  const intl = useIntl();
  const { data, error, isLoading } = useSystemHealth();

  if (isLoading && !data) {
    return <Skeleton className="h-32 w-full rounded-lg" />;
  }

  if (error?.status === 403) {
    return <PermissionDenied />;
  }

  if (error || !data) {
    return (
      <Card size="sm">
        <CardContent className="text-sm text-muted-foreground" role="alert">
          {intl.formatMessage({ id: "dashboard.home.mcp.error" })}
        </CardContent>
      </Card>
    );
  }

  const healthy = deriveMcpHealthy(data);
  const redisConfigured = isRedisConfigured(data);

  return (
    <Card size="sm">
      <CardContent className="space-y-4">
        <StatusDot tone={healthy ? "success" : "error"}>
          <span className="text-sm font-medium text-foreground">
            {intl.formatMessage({
              id: healthy ? "dashboard.home.mcp.healthy" : "dashboard.home.mcp.unhealthy",
            })}
          </span>
        </StatusDot>

        <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm text-muted-foreground">
          <StatusDot tone={data.database.reachable ? "success" : "error"}>
            {intl.formatMessage({ id: "dashboard.home.mcp.postgres" })}
          </StatusDot>
          {redisConfigured ? (
            <StatusDot tone={data.redis.reachable ? "success" : "error"}>
              {intl.formatMessage({ id: "dashboard.home.mcp.redis" })}
            </StatusDot>
          ) : (
            <StatusDot tone="muted">
              {intl.formatMessage({ id: "dashboard.home.mcp.redis" })}
              <span className="text-muted-foreground">
                {" "}
                ({intl.formatMessage({ id: "dashboard.home.mcp.notConfigured" })})
              </span>
            </StatusDot>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
