import { useIntl } from "react-intl";
import { AlertCircle, CheckCircle2 } from "lucide-react";

import { CodeBlock } from "@/components/ui/code-block";
import { cn } from "@/lib/utils";
import type { PromptPreviewState } from "./usePromptPreview";

export interface PromptPreviewResultProps {
  preview: Pick<PromptPreviewState, "result" | "error" | "hasRun">;
}

/**
 * Status row + rendered-messages block. Renders nothing before the first
 * Preview run; the design intentionally has no empty-state placeholder.
 */
export function PromptPreviewResult({ preview }: PromptPreviewResultProps) {
  const intl = useIntl();
  const { result, error, hasRun } = preview;

  if (!hasRun) return null;

  const renderTimeMs = result?.renderTimeMs ?? error?.renderTimeMs ?? 0;
  const succeeded = result !== null;

  return (
    <div className="space-y-3">
      <div
        role="status"
        aria-live="polite"
        className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px]"
      >
        {succeeded ? (
          <CheckCircle2 className="size-4 text-emerald-500" />
        ) : (
          <AlertCircle className="size-4 text-destructive" />
        )}
        <span className={cn("font-medium", succeeded ? "text-foreground" : "text-destructive")}>
          {intl.formatMessage({
            id: succeeded
              ? "prompts.details.preview.statusOk"
              : "prompts.details.preview.statusError",
          })}
        </span>
        <span className="text-muted-foreground" aria-hidden="true">
          ·
        </span>
        <span className="text-muted-foreground">
          {intl.formatMessage({ id: "prompts.details.preview.renderMs" }, { ms: renderTimeMs })}
        </span>
        {/* TODO(#5448 followup): render `Plugins passed (N)` once the backend
            response exposes a plugin trace. */}
      </div>

      {result && (
        <CodeBlock
          code={JSON.stringify({ messages: result.rendered.messages ?? [] }, null, 2)}
          language="json"
          copyLabel="JSON"
          copiedLabel={intl.formatMessage({ id: "prompts.details.code.copySuccess" })}
        />
      )}

      {error && (
        <pre className="overflow-auto rounded-md border border-destructive/40 bg-destructive/5 p-4 font-mono text-[12px] leading-relaxed text-destructive">
          {error.message}
        </pre>
      )}
    </div>
  );
}
