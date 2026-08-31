/**
 * McpHealthCard (#5842).
 *
 * Per-server MCP reachability roster over `GET /gateways` (React "MCP servers"):
 * a "Servers" title with a "Refreshed X ago" hint, a top-right fleet status
 * ("Reachable" / "Reduced coverage" / "Unreachable" / "Disabled"), an inline
 * "X of N" summary with component totals, one row per server, and Postgres/Redis
 * dependency chips.
 *
 * Two-tone only (green = enabled + reachable, grey = everything else); errors
 * live in the Activity feed, not here. See `mcpServerRoster.ts` for the pure
 * classification logic.
 *
 * Permissions: `/gateways` is RBAC-scoped server-side (`gateways.read` + token
 * teams), so the card self-gates — a caller without `gateways.read` gets a 403
 * we surface as PermissionDenied, and a scoped caller only ever sees (and counts)
 * their own servers. The footer chips come from the admin-only `/version`
 * endpoint, so we fetch it only when the caller has `admin.system_config` and
 * swallow any 403 locally (the chips just disappear; the card stays healthy).
 */

import { Database, Server } from "lucide-react";
import { useMemo } from "react";
import { useIntl } from "react-intl";

import { useAuth } from "@/auth/useAuth";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  isRedisConfigured,
  useSystemHealth,
  type SystemHealthResult,
  type VersionInfo,
} from "@/hooks/useSystemHealth";
import { useMcpServers } from "@/hooks/useMcpServers";
import { useElementWidth } from "@/hooks/useElementWidth";
import { cn } from "@/lib/utils";
import { formatLastSeen } from "@/utils/format";
import {
  computeRoster,
  headerTone,
  type RosterHeaderKind,
  type SummarySegment,
} from "./mcpServerRoster";
import { PermissionDenied } from "./PermissionDenied";
import { ServerRosterRow, ServerRosterRowStacked } from "./ServerRosterRow";
import { StatusDot } from "./StatusDot";

const HEADER_MESSAGE_ID: Record<RosterHeaderKind, string> = {
  reachable: "dashboard.home.mcp.header.reachable",
  reducedCoverage: "dashboard.home.mcp.header.reducedCoverage",
  unreachable: "dashboard.home.mcp.header.unreachable",
  disabled: "dashboard.home.mcp.header.disabled",
};

const SEGMENT_MESSAGE_ID: Record<SummarySegment["kind"], string> = {
  unreachable: "dashboard.home.mcp.summary.unreachable",
  disabled: "dashboard.home.mcp.summary.disabled",
  reachable: "dashboard.home.mcp.summary.reachable",
  pending: "dashboard.home.mcp.summary.pending",
};

/**
 * Postgres/Redis dependency chips from the admin-only `/version` diagnostics.
 * Icons stay muted in the healthy/not-configured case (matching the design) and
 * only turn red when a configured dependency is unreachable.
 */
function FooterChips({ data }: { data: VersionInfo }) {
  const intl = useIntl();
  const redisConfigured = isRedisConfigured(data);

  return (
    <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm text-muted-foreground">
      <span className="inline-flex items-center gap-1.5">
        <Database
          className={cn("size-3.5 shrink-0", !data.database.reachable && "text-destructive")}
          aria-hidden
        />
        {intl.formatMessage({ id: "dashboard.home.mcp.postgres" })}
      </span>
      <span className="inline-flex items-center gap-1.5">
        <Server
          className={cn(
            "size-3.5 shrink-0",
            redisConfigured && !data.redis.reachable && "text-destructive",
          )}
          aria-hidden
        />
        {intl.formatMessage({ id: "dashboard.home.mcp.redis" })}
        {!redisConfigured && (
          <span> ({intl.formatMessage({ id: "dashboard.home.mcp.notConfigured" })})</span>
        )}
      </span>
    </div>
  );
}

/**
 * Placeholder for the footer chips while `/version` is in flight. Reserves the
 * chips' height so the card does not grow when the real chips arrive — the
 * footer resolves after the body (separate request, gated behind the async
 * permission load), so without this the chips would pop in.
 */
function FooterChipsSkeleton() {
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
      <Skeleton className="h-4 w-28" />
      <Skeleton className="h-4 w-20" />
    </div>
  );
}

// Below this card width the single-line table can't fit name + counts +
// transport + last-seen without clipping, so the roster switches to the stacked
// list. Measured on the card, not the viewport. Set just above the table's
// minimum fitting width (~627px) so the table shows across the card's real
// desktop range (the dashboard main column caps its content near ~700px); the
// overflow-x-auto scroller is the safety net for unusually long server names.
const ROSTER_WIDE_MIN_PX = 640;

export function McpHealthCard({ health: sharedHealth }: { health?: SystemHealthResult } = {}) {
  const intl = useIntl();
  const { hasPermission } = useAuth();
  const { servers, error, isLoading, lastUpdated } = useMcpServers();
  const [rosterRef, rosterWidth] = useElementWidth<HTMLDivElement>();
  const rosterIsWide = rosterWidth >= ROSTER_WIDE_MIN_PX;

  // Footer chips need the admin-only /version endpoint. Reuse the page-level poll
  // when the home passes it in (it already polls /version for the headline), so
  // the mcp view doesn't poll it twice; otherwise fetch it here. Only fetch when
  // the caller can, so non-admins never poll a guaranteed 403.
  const canViewSystem = hasPermission("admin.system_config");
  const ownHealth = useSystemHealth(undefined, canViewSystem && sharedHealth === undefined);
  const { data: health, isLoading: healthLoading, error: healthError } = sharedHealth ?? ownHealth;
  // Show a placeholder only while the request is genuinely in flight — never
  // after a swallowed 403/other error (then the chips simply stay absent).
  const showFooterSkeleton = canViewSystem && !health && healthLoading && !healthError;

  const roster = useMemo(() => computeRoster(servers ?? []), [servers]);

  // Loading: no data yet.
  if (isLoading && !servers) {
    return (
      <Card size="sm">
        <CardContent className="text-sm text-muted-foreground">
          {intl.formatMessage({ id: "dashboard.home.mcp.loading" })}
        </CardContent>
      </Card>
    );
  }

  // No gateways.read -> 403 -> precise permission gate (authoritative even with
  // a previously-loaded roster: a lost permission should not keep showing data).
  if (error?.status === 403) {
    return <PermissionDenied />;
  }

  // Only surface the error card when there is no roster to show. Once servers
  // have loaded, a transient (non-403) refetch failure keeps the last-known
  // roster on screen rather than replacing it with an error — useQuery preserves
  // `data` across a failed refetch, and the poll will recover on its own.
  if (!servers) {
    return (
      <Card size="sm">
        <CardContent className="text-sm text-muted-foreground" role="alert">
          {intl.formatMessage({ id: "dashboard.home.mcp.error" })}
        </CardContent>
      </Card>
    );
  }

  // Empty fleet: no header, no footer chips, just the empty copy.
  if (servers.length === 0) {
    return (
      <Card size="sm">
        <CardContent className="text-sm text-muted-foreground">
          {intl.formatMessage({ id: "dashboard.home.mcp.empty" })}
        </CardContent>
      </Card>
    );
  }

  const { summary } = roster;

  // Inline summary: reachable/disabled/... segments followed by component totals,
  // all dot-separated on one line (e.g. "3 of 3 reachable · 42 tools · 3 resources").
  const summaryParts: { key: string; text: string }[] = roster.segments.map((segment) => ({
    key: segment.kind,
    text: intl.formatMessage(
      { id: SEGMENT_MESSAGE_ID[segment.kind] },
      { count: segment.count, total: segment.total },
    ),
  }));
  if (summary.toolCount + summary.resourceCount + summary.promptCount > 0) {
    summaryParts.push({
      key: "components",
      text: intl.formatMessage(
        { id: "dashboard.home.mcp.components" },
        {
          tools: summary.toolCount,
          resources: summary.resourceCount,
          prompts: summary.promptCount,
        },
      ),
    });
  }

  // "Refreshed just now" only replaces the relative formatter's "now" for a
  // just-completed poll (0 seconds ago); every other age renders the relative
  // time as before ("Refreshed 30 seconds ago", "Refreshed 5 minutes ago").
  const refreshedText = (() => {
    if (lastUpdated == null) return null;
    if (Math.round((Date.now() - lastUpdated) / 1000) === 0) {
      return intl.formatMessage({ id: "dashboard.home.mcp.refreshedJustNow" });
    }
    const relative = formatLastSeen(new Date(lastUpdated).toISOString(), { locale: intl.locale });
    return relative
      ? intl.formatMessage({ id: "dashboard.home.mcp.refreshed" }, { relative })
      : null;
  })();

  return (
    <Card size="sm">
      <CardContent className="space-y-6">
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-1">
            <div className="text-sm font-medium text-foreground">
              {intl.formatMessage({ id: "dashboard.home.mcp.title" })}
            </div>
            {refreshedText && <div className="text-xs text-muted-foreground">{refreshedText}</div>}
          </div>
          {roster.header && (
            <StatusDot
              tone={headerTone(roster.header)}
              className="shrink-0 text-sm text-muted-foreground"
            >
              {intl.formatMessage({ id: HEADER_MESSAGE_ID[roster.header] })}
            </StatusDot>
          )}
        </div>

        {summaryParts.length > 0 && (
          <div className="flex flex-wrap items-center gap-x-2 text-sm text-muted-foreground">
            {summaryParts.map((part, index) => (
              <span key={part.key} className="flex items-center gap-x-2">
                {index > 0 && <span aria-hidden>·</span>}
                {part.text}
              </span>
            ))}
          </div>
        )}

        {/*
          The roster renders as an aligned <table> when the card is wide enough
          for one line, and as a stacked list otherwise. We measure the card's
          own width (not the viewport) and render the shape that fits, rather than
          morphing one DOM — each shape keeps clean, universally-supported
          semantics (a real table / a real list; no display:contents).
        */}
        <div ref={rosterRef}>
          {rosterIsWide ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="sr-only">
                  <tr>
                    <th scope="col">
                      {intl.formatMessage({ id: "dashboard.home.mcp.column.server" })}
                    </th>
                    <th scope="col">
                      {intl.formatMessage({ id: "dashboard.home.mcp.column.components" })}
                    </th>
                    <th scope="col">
                      {intl.formatMessage({ id: "dashboard.home.mcp.column.transport" })}
                    </th>
                    <th scope="col">
                      {intl.formatMessage({ id: "dashboard.home.mcp.column.lastSeen" })}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {roster.rows.map((classified) => (
                    <ServerRosterRow key={classified.server.id} classified={classified} />
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <ul role="list" className="flex flex-col gap-3">
              {roster.rows.map((classified) => (
                <ServerRosterRowStacked key={classified.server.id} classified={classified} />
              ))}
            </ul>
          )}
        </div>

        {canViewSystem && health && <FooterChips data={health} />}
        {showFooterSkeleton && <FooterChipsSkeleton />}
      </CardContent>
    </Card>
  );
}
