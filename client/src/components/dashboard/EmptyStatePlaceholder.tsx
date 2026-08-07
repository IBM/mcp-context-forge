/**
 * EmptyStatePlaceholder — standard empty state used by not-yet-available views
 * (REST API, gRPC, A2A interim) and as the generic main-content stub during
 * scaffolding. Uses the same component contract as real content so swapping in
 * a real view later is a data change, not a structural one.
 */

import { useIntl } from "react-intl";

import { cn } from "@/lib/utils";

interface EmptyStatePlaceholderProps {
  /** i18n message id; defaults to the generic "Empty state (to add)" copy. */
  messageId?: string;
  className?: string;
}

export function EmptyStatePlaceholder({
  messageId = "dashboard.home.emptyState",
  className,
}: EmptyStatePlaceholderProps) {
  const intl = useIntl();
  return (
    <div
      className={cn(
        "rounded-lg bg-muted/40 px-6 py-8 text-sm text-muted-foreground ring-1 ring-foreground/10",
        className,
      )}
    >
      {intl.formatMessage({ id: messageId })}
    </div>
  );
}
