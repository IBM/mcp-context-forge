/**
 * ServerRosterRow (#5842).
 *
 * One row in the MCP reachability roster, laid out as a single line of columns
 * (matching the Figma design): a status dot + server name, an aggregate
 * component count, the transport, and a right-aligned state meta.
 *
 * The dot tone and every string come from the pure classification in
 * `mcpServerRoster.ts`; this component only renders and maps enum kinds to i18n
 * messages.
 *
 * Right-aligned meta by state:
 * - checking    -> "checking connection…" (name only; no components/transport,
 *                  since a never-probed server has no trustworthy last-known data)
 * - disabled    -> "disabled X ago" (or a no-time fallback)
 * - reachable /
 *   unreachable -> "last seen X ago" (or a never-seen fallback)
 */

import { useIntl } from "react-intl";

import { formatLastSeen } from "@/utils/format";
import type { ClassifiedServer } from "./mcpServerRoster";
import { rowTone } from "./mcpServerRoster";
import { StatusDot } from "./StatusDot";

/** Resolve the right-aligned meta line for a row from its classified state. */
function useMetaText({ server, state }: ClassifiedServer): string {
  const intl = useIntl();

  if (state === "checking") {
    return intl.formatMessage({ id: "dashboard.home.mcp.row.checking" });
  }

  const relative = formatLastSeen(server.lastSeen, { locale: intl.locale });

  if (state === "disabled") {
    return relative
      ? intl.formatMessage({ id: "dashboard.home.mcp.row.disabled" }, { relative })
      : intl.formatMessage({ id: "dashboard.home.mcp.row.disabledNoTime" });
  }

  return relative
    ? intl.formatMessage({ id: "dashboard.home.mcp.row.lastSeen" }, { relative })
    : intl.formatMessage({ id: "dashboard.home.mcp.row.neverSeen" });
}

interface ServerRosterRowProps {
  classified: ClassifiedServer;
}

export function ServerRosterRow({ classified }: ServerRosterRowProps) {
  const intl = useIntl();
  const { server, state } = classified;
  const meta = useMetaText(classified);

  // Never-probed rows have no trustworthy component/transport data to show.
  const showDetails = state !== "checking";
  const componentCount =
    (server.toolCount ?? 0) + (server.resourceCount ?? 0) + (server.promptCount ?? 0);

  // `contents` lets each cell participate directly in the parent <ul> grid, so
  // the component and transport columns share tracks (and stay left-aligned)
  // across every row regardless of how long an individual server name is.
  return (
    <li role="listitem" className="contents text-sm">
      <StatusDot tone={rowTone(state)} className="min-w-0">
        <span className="truncate text-foreground">{server.name}</span>
      </StatusDot>

      {showDetails ? (
        <span className="whitespace-nowrap text-muted-foreground">
          {intl.formatMessage(
            { id: "dashboard.home.mcp.rowComponents" },
            { count: componentCount },
          )}
        </span>
      ) : (
        <span />
      )}

      {showDetails ? (
        <span className="truncate text-muted-foreground">
          {intl.formatMessage({ id: `dashboard.home.mcp.transport.${server.transport}` })}
        </span>
      ) : (
        <span />
      )}

      <span className="justify-self-end whitespace-nowrap text-muted-foreground">{meta}</span>
    </li>
  );
}
