/**
 * MiniCard — reusable navigation card for the right-hand column (and the inline
 * row of source cards in the default state). Parameterized by source type,
 * label, and an optional status indicator. Clicking navigates to the card's
 * view (`?view=<id>`).
 */

import { useIntl } from "react-intl";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";
import { useRouter } from "@/router";
import { MINI_CARDS, viewHref, type MiniCardId } from "./homeStates";

interface MiniCardProps {
  id: MiniCardId;
  /** Optional status indicator slot (e.g. a StatusDot + label). */
  status?: ReactNode;
  className?: string;
}

export function MiniCard({ id, status, className }: MiniCardProps) {
  const intl = useIntl();
  const { navigate } = useRouter();
  const meta = MINI_CARDS[id];
  const Icon = meta.icon;

  return (
    <button
      type="button"
      onClick={() => navigate(viewHref(meta.view))}
      className={cn(
        "flex w-full flex-col gap-2 rounded-lg bg-card px-4 py-3 text-left text-sm ring-1 ring-foreground/10 shadow-xs",
        "transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        className,
      )}
    >
      <span className="flex items-center gap-2 font-medium text-foreground">
        <Icon className="size-4 shrink-0 text-muted-foreground" />
        {intl.formatMessage({ id: meta.labelId })}
      </span>
      {status ? <span className="text-xs text-muted-foreground">{status}</span> : null}
    </button>
  );
}
