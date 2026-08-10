import { KeyRound } from "lucide-react";

import { cn } from "@/lib/utils";

interface TokenIconProps {
  className?: string;
}

/**
 * The magenta key badge that brands the API tokens surface — reused in the list
 * rows, the empty-state card, and the create-form header so the mark stays
 * consistent everywhere. Matches the sizing of the Users/Teams row and form
 * badges (6×6 rounded square).
 */
export function TokenIcon({ className }: TokenIconProps) {
  return (
    <span
      className={cn(
        "flex h-6 w-6 shrink-0 items-center justify-center rounded bg-fuchsia-500 shadow-sm",
        className,
      )}
      aria-hidden="true"
    >
      <KeyRound className="h-4 w-4 text-white" strokeWidth={2} />
    </span>
  );
}
