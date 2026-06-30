import { useEffect, useState } from "react";

import type { PromptRead } from "@/generated/types";
import { PromptArgsForm } from "./PromptArgsForm";
import { PromptPreviewPanel } from "./PromptPreviewPanel";
import { PromptSnippetTabs } from "./PromptSnippetTabs";

export interface PromptCodeTabProps {
  prompt: NonNullable<PromptRead>;
}

/**
 * The Code tab for the prompt details drawer. Composes the args form, the
 * language-snippet sub-tabs, and the render-only Preview panel.
 *
 * Public seam for issue #5323: the drawer engineer drops this into the Code
 * tab content slot with `<PromptCodeTab prompt={selected} />` — it owns its
 * own args state and exposes no callbacks.
 */
export function PromptCodeTab({ prompt }: PromptCodeTabProps) {
  const [args, setArgs] = useState<Record<string, string>>(() => seedArgs(prompt));

  // Reset args when the user switches to a different prompt within the same
  // drawer instance. Keyed on id so renames don't wipe in-progress input.
  useEffect(() => {
    setArgs(seedArgs(prompt));
  }, [prompt.id]);

  return (
    <div className="space-y-6">
      <PromptArgsForm args={args} schema={prompt.arguments} onChange={setArgs} />
      <PromptSnippetTabs promptName={prompt.name} args={args} />
      <PromptPreviewPanel promptId={prompt.id} args={args} />
    </div>
  );
}

function seedArgs(prompt: NonNullable<PromptRead>): Record<string, string> {
  const seed: Record<string, string> = {};
  for (const arg of prompt.arguments) {
    if (arg) seed[arg.name] = "";
  }
  return seed;
}
