/**
 * ServerRosterRow (#5842).
 *
 * A row in the MCP reachability roster, rendered in one of two shapes that
 * McpHealthCard picks by measuring the card's own width (see useElementWidth):
 *
 * - ServerRosterRow (wide): a <tr> in a real <table>, so status/name, component
 *   count, transport, and the right-aligned meta line up as columns across rows
 *   with proper table semantics for screen readers.
 * - ServerRosterRowStacked (narrow): a <li> that stacks the same four cells in a
 *   single left-aligned column (name, components, transport, then meta), with the
 *   name truncating rather than clipping.
 *
 * Rendering the ideal DOM per width (instead of morphing one DOM with
 * display:contents or subgrid) keeps semantics clean and support universal. The
 * dot tone and every string come from the pure classification in
 * `mcpServerRoster.ts`.
 *
 * Meta by state:
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

/** Resolve the meta line for a row from its classified state. */
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

/** Shared, presentation-agnostic view model for both row shapes. */
function useRosterRow(classified: ClassifiedServer) {
  const intl = useIntl();
  const { server, state } = classified;

  // Never-probed rows have no trustworthy component/transport data to show.
  const showDetails = state !== "checking";
  const componentCount =
    (server.toolCount ?? 0) + (server.resourceCount ?? 0) + (server.promptCount ?? 0);

  return {
    name: server.name,
    tone: rowTone(state),
    meta: useMetaText(classified),
    showDetails,
    componentsText: intl.formatMessage(
      { id: "dashboard.home.mcp.rowComponents" },
      { count: componentCount },
    ),
    transportText: intl.formatMessage({ id: `dashboard.home.mcp.transport.${server.transport}` }),
  };
}

interface ServerRosterRowProps {
  classified: ClassifiedServer;
}

/** Wide shape: a table row whose cells align into shared columns across rows. */
export function ServerRosterRow({ classified }: ServerRosterRowProps) {
  const { name, tone, meta, showDetails, componentsText, transportText } = useRosterRow(classified);

  return (
    <tr>
      <td className="whitespace-nowrap py-1.5 pr-6">
        <StatusDot tone={tone}>
          <span className="text-foreground">{name}</span>
        </StatusDot>
      </td>
      <td className="whitespace-nowrap py-1.5 pr-6 text-muted-foreground">
        {showDetails ? componentsText : null}
      </td>
      {/* w-full makes this column absorb the slack, so transport sits left and
          the meta column stays flush right. */}
      <td className="w-full whitespace-nowrap py-1.5 pr-6 text-muted-foreground">
        {showDetails ? transportText : null}
      </td>
      <td className="whitespace-nowrap py-1.5 text-right text-muted-foreground">{meta}</td>
    </tr>
  );
}

/** Narrow shape: a stacked list item, one left-aligned cell per line. */
export function ServerRosterRowStacked({ classified }: ServerRosterRowProps) {
  const { name, tone, meta, showDetails, componentsText, transportText } = useRosterRow(classified);

  return (
    <li className="flex flex-col gap-y-0.5 text-sm">
      <StatusDot tone={tone} className="flex min-w-0">
        <span className="min-w-0 truncate text-foreground">{name}</span>
      </StatusDot>
      {showDetails && <span className="text-muted-foreground">{componentsText}</span>}
      {showDetails && <span className="text-muted-foreground">{transportText}</span>}
      <span className="text-muted-foreground">{meta}</span>
    </li>
  );
}
