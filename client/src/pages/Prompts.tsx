import { useMemo, useState } from "react";

import { useQuery } from "@/hooks/useQuery";
import { PromptDetailsPanel } from "@/components/prompts";
import type { PromptRead } from "@/generated/types";
import { Button } from "@/components/ui/button";

/**
 * Temporary preview surface for the #5323 details drawer.
 *
 * Renders a single "Open prompt details" trigger; the drawer hosts the
 * prompt-picker pill row and the Code tab inline. Throwaway — replaced when
 * #5101's grouped Prompts card layout lands and the drawer is triggered per
 * card menu instead of from a POC button.
 */
export function Prompts() {
  const { data, isLoading, error } = useQuery<(PromptRead | null)[]>("/prompts?limit=0");
  const [open, setOpen] = useState(false);

  const prompts = useMemo(
    () => (data ?? []).filter((p): p is NonNullable<PromptRead> => Boolean(p && p.enabled)),
    [data],
  );

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold text-neutral-900 dark:text-neutral-100">Prompts</h1>
        <p className="text-sm text-muted-foreground">
          POC: this page will be replaced when the UI with cards for prompts is implemented (#5101)
          and the details drawer lands (#5323).
        </p>
      </header>

      <div className="flex items-center gap-3">
        <Button
          type="button"
          onClick={() => setOpen(true)}
          disabled={isLoading || prompts.length === 0}
        >
          {isLoading
            ? "Loading prompts..."
            : prompts.length === 0
              ? "No prompts available"
              : "Open prompt details"}
        </Button>
        {error && (
          <p className="text-[12px] text-destructive">Failed to load prompts: {error.message}</p>
        )}
      </div>

      <PromptDetailsPanel prompts={prompts} open={open} onClose={() => setOpen(false)} />
    </div>
  );
}
