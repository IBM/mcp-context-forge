import { useEffect, useState } from "react";

import type { PromptRead } from "@/generated/types";
import { PromptArgsForm } from "./PromptArgsForm";
import { PromptPreviewButton } from "./PromptPreviewButton";
import { PromptPreviewResult } from "./PromptPreviewResult";
import { PromptSnippetTabs } from "./PromptSnippetTabs";
import { usePromptPreview } from "./usePromptPreview";

export interface PromptCodeTabProps {
  prompt: NonNullable<PromptRead>;
}

/**
 * The Code tab for the prompt details drawer. Composes the args form, the
 * language-snippet sub-tabs (with the Preview button on the tab row), and
 * the Preview result below.
 *
 * Public seam for #5323: the drawer engineer drops this into the Code tab
 * content slot with `<PromptCodeTab prompt={selected} />` — it owns its own
 * args state and exposes no callbacks.
 */
export function PromptCodeTab({ prompt }: PromptCodeTabProps) {
  const [args, setArgs] = useState<Record<string, string>>(() => seedArgs(prompt));
  // Address the prompt by name — same identifier the snippets show and what
  // MCP-spec clients use on the wire. See `promptsApi.render` for the full
  // rationale and the tracked "server-scoped MCP transport" follow-up.
  const preview = usePromptPreview(prompt.name, args);

  // Reset args when the user switches to a different prompt within the same
  // drawer instance. Keyed on id so renames don't wipe in-progress input.
  useEffect(() => {
    setArgs(seedArgs(prompt));
  }, [prompt.id]);

  return (
    <div className="space-y-6">
      <PromptArgsForm args={args} schema={prompt.arguments} onChange={setArgs} />
      <div className="space-y-4">
        <PromptSnippetTabs
          promptName={prompt.name}
          args={args}
          actions={<PromptPreviewButton preview={preview} />}
        />
        <PromptPreviewResult preview={preview} />
      </div>
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
