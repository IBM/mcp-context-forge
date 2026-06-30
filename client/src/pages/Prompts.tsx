import { useMemo, useState } from "react";

import { useQuery } from "@/hooks/useQuery";
import { PromptCodeTab } from "@/components/prompts";
import type { PromptRead } from "@/generated/types";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

/**
 * Temporary preview surface for the #5448 Code-tab prototype.
 *
 * Replaces the 3-line page stub with a minimal select-a-prompt → render
 * `<PromptCodeTab>` UI so the prototype can be exercised against the live
 * gateway before the #5323 drawer lands. Throwaway — gets removed once the
 * prompt details drawer is wired up.
 */
export function Prompts() {
  const { data, isLoading, error } = useQuery<(PromptRead | null)[]>("/prompts?limit=0");
  const [selectedId, setSelectedId] = useState<string | undefined>(undefined);

  const prompts = useMemo(
    () =>
      (data ?? []).filter((p): p is NonNullable<PromptRead> => Boolean(p && p.enabled)),
    [data],
  );
  const selected = prompts.find((p) => p.id === selectedId);

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold text-neutral-900 dark:text-neutral-100">
          Prompts
        </h1>
        <p className="text-sm text-muted-foreground">
          POC scaffold — pick a prompt to exercise the Code tab and Preview action.
          This page is replaced when the details drawer lands (#5323).
        </p>
      </header>

      <div className="max-w-sm space-y-1.5">
        <label className="text-sm font-medium text-foreground" htmlFor="prompt-picker">
          Prompt
        </label>
        <Select value={selectedId ?? ""} onValueChange={setSelectedId}>
          <SelectTrigger id="prompt-picker" disabled={isLoading || prompts.length === 0}>
            <SelectValue
              placeholder={
                isLoading
                  ? "Loading prompts..."
                  : prompts.length === 0
                    ? "No prompts available"
                    : "Select a prompt"
              }
            />
          </SelectTrigger>
          <SelectContent>
            {prompts.map((prompt) => (
              <SelectItem key={prompt.id} value={prompt.id}>
                <span className="font-mono text-[12px]">{prompt.name}</span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {error && (
          <p className="text-[12px] text-destructive">Failed to load prompts: {error.message}</p>
        )}
      </div>

      {selected && (
        <section className="max-w-3xl rounded-lg border border-border bg-background p-6">
          <PromptCodeTab prompt={selected} />
        </section>
      )}
    </div>
  );
}
