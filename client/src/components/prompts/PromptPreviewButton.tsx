import { useIntl } from "react-intl";
import { Loader2, Play } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { PromptPreviewState } from "./usePromptPreview";

export interface PromptPreviewButtonProps {
  preview: Pick<PromptPreviewState, "run" | "isLoading" | "hasRun">;
}

/**
 * The Preview / Re-run / Rendering trigger. Kept separate from the response
 * components so it can live on the snippet-tab row while the status and
 * rendered messages render below.
 */
export function PromptPreviewButton({ preview }: PromptPreviewButtonProps) {
  const intl = useIntl();
  const { run, isLoading, hasRun } = preview;

  return (
    <Button type="button" variant="outline" size="sm" onClick={run} disabled={isLoading}>
      {isLoading ? (
        <>
          <Loader2 className="size-3.5 animate-spin" />
          {intl.formatMessage({ id: "prompts.details.preview.running" })}
        </>
      ) : hasRun ? (
        intl.formatMessage({ id: "prompts.details.preview.rerun" })
      ) : (
        <>
          <Play className="size-3.5" />
          {intl.formatMessage({ id: "prompts.details.preview.run" })}
        </>
      )}
    </Button>
  );
}
