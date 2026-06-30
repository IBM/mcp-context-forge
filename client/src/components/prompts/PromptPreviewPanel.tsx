import { useCallback, useState } from "react";
import { useIntl } from "react-intl";
import { AlertCircle, CheckCircle2, Loader2, Play, RotateCcw } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { JsonHighlighter } from "@/components/ui/json-highlighter";
import { promptsApi, type RenderedPrompt } from "@/api/prompts";
import { ApiError } from "@/api/client";
import { cn } from "@/lib/utils";

export interface PromptPreviewPanelProps {
  promptId: string;
  args: Record<string, string>;
}

interface PreviewResult {
  rendered: RenderedPrompt;
  renderTimeMs: number;
}

export function PromptPreviewPanel({ promptId, args }: PromptPreviewPanelProps) {
  const intl = useIntl();
  const [isLoading, setLoading] = useState(false);
  const [result, setResult] = useState<PreviewResult | null>(null);
  const [error, setError] = useState<{ message: string; renderTimeMs: number } | null>(null);

  const run = useCallback(async () => {
    setLoading(true);
    setError(null);
    const startedAt = performance.now();
    try {
      const rendered = await promptsApi.render(promptId, args);
      const renderTimeMs = Math.round(performance.now() - startedAt);
      setResult({ rendered, renderTimeMs });
    } catch (err) {
      const renderTimeMs = Math.round(performance.now() - startedAt);
      const message =
        err instanceof ApiError
          ? typeof err.body === "object" && err.body !== null && "detail" in err.body
            ? String((err.body as { detail: unknown }).detail)
            : err.message
          : err instanceof Error
            ? err.message
            : "Unknown error";
      setError({ message, renderTimeMs });
      setResult(null);
      toast.error(intl.formatMessage({ id: "prompts.details.preview.error" }));
    } finally {
      setLoading(false);
    }
  }, [promptId, args, intl]);

  const hasRun = result !== null || error !== null;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <Button type="button" size="sm" onClick={run} disabled={isLoading}>
          {isLoading ? (
            <>
              <Loader2 className="size-3.5 animate-spin" />
              {intl.formatMessage({ id: "prompts.details.preview.running" })}
            </>
          ) : hasRun ? (
            <>
              <RotateCcw className="size-3.5" />
              {intl.formatMessage({ id: "prompts.details.preview.rerun" })}
            </>
          ) : (
            <>
              <Play className="size-3.5" />
              {intl.formatMessage({ id: "prompts.details.preview.run" })}
            </>
          )}
        </Button>

        {hasRun && <StatusRow result={result} error={error} />}
      </div>

      {!hasRun && (
        <p className="text-sm text-muted-foreground">
          {intl.formatMessage({ id: "prompts.details.preview.empty" })}
        </p>
      )}

      {result && (
        <div className="space-y-2">
          <h4 className="text-sm font-semibold text-foreground">
            {intl.formatMessage({ id: "prompts.details.preview.messagesHeading" })}
          </h4>
          <pre className="max-h-[320px] overflow-auto rounded-md border border-border bg-neutral-50 p-3 font-mono text-[12px] leading-relaxed text-foreground dark:bg-neutral-900">
            <JsonHighlighter text={JSON.stringify(result.rendered.messages ?? [], null, 2)} />
          </pre>
        </div>
      )}

      {error && (
        <pre className="overflow-auto rounded-md border border-destructive/40 bg-destructive/5 p-3 font-mono text-[12px] leading-relaxed text-destructive">
          {error.message}
        </pre>
      )}
    </div>
  );
}

function StatusRow({
  result,
  error,
}: {
  result: PreviewResult | null;
  error: { message: string; renderTimeMs: number } | null;
}) {
  const intl = useIntl();
  const renderTimeMs = result?.renderTimeMs ?? error?.renderTimeMs ?? 0;

  return (
    <div
      role="status"
      aria-live="polite"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px]"
    >
      <span
        className={cn(
          "inline-flex items-center gap-1.5 font-medium",
          result ? "text-emerald-600 dark:text-emerald-400" : "text-destructive",
        )}
      >
        {result ? (
          <>
            <CheckCircle2 className="size-3.5" />
            {intl.formatMessage({ id: "prompts.details.preview.statusOk" })}
          </>
        ) : (
          <>
            <AlertCircle className="size-3.5" />
            {intl.formatMessage({ id: "prompts.details.preview.statusError" })}
          </>
        )}
      </span>
      <span className="text-muted-foreground">·</span>
      <span className="text-muted-foreground">
        {intl.formatMessage({ id: "prompts.details.preview.renderTime" })}:{" "}
        {intl.formatMessage(
          { id: "prompts.details.preview.renderTimeMs" },
          { ms: renderTimeMs },
        )}
      </span>
      {/* TODO(#5448 followup): render `Plugins passed (N)` once the backend
          response exposes a plugin trace — issue's open question on tagging
          preview invocations covers the same code path. */}
    </div>
  );
}
