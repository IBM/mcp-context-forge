/**
 * MiniCardStatusIndicator — renders a `MiniCardStatus` descriptor as the node
 * for a MiniCard's status slot: a StatusDot with a label, or the activity
 * error/warning counts. Every source/system card always resolves to a dot, so
 * there is no empty state to collapse.
 */

import { useIntl } from "react-intl";

import type { MiniCardStatus } from "./miniCardStatus";
import { StatusDot } from "./StatusDot";

export function MiniCardStatusIndicator({ status }: { status: MiniCardStatus }) {
  const intl = useIntl();

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
