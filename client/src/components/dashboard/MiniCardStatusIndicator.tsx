/**
 * MiniCardStatusIndicator — renders a `MiniCardStatus` descriptor as the node
 * for a MiniCard's status slot: a StatusDot with a label, or the activity
 * error/warning counts. Returns null for the empty status so the slot collapses.
 */

import { useIntl } from "react-intl";

import type { MiniCardStatus } from "./miniCardStatus";
import { StatusDot } from "./StatusDot";

export function MiniCardStatusIndicator({ status }: { status: MiniCardStatus }) {
  const intl = useIntl();

  if (!status) return null;

  if (status.kind === "activity") {
    return (
      <span>
        {intl.formatMessage(
          { id: "dashboard.home.status.activity" },
          { errors: status.errors, warnings: status.warnings },
        )}
      </span>
    );
  }

  return <StatusDot tone={status.tone}>{intl.formatMessage({ id: status.labelId })}</StatusDot>;
}
