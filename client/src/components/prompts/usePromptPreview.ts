import { useCallback, useState } from "react";
import { useIntl } from "react-intl";
import { toast } from "sonner";

import { ApiError } from "@/api/client";
import { promptsApi, type RenderedPrompt } from "@/api/prompts";

export interface PreviewSuccess {
  rendered: RenderedPrompt;
  renderTimeMs: number;
}

export interface PreviewFailure {
  message: string;
  renderTimeMs: number;
}

export interface PromptPreviewState {
  run: () => Promise<void>;
  isLoading: boolean;
  result: PreviewSuccess | null;
  error: PreviewFailure | null;
  hasRun: boolean;
}

/**
 * Owns the render-only Preview lifecycle. Keeps the network call, timing,
 * error parsing, and toast feedback in one place so the visual pieces
 * (button, status row, response body) can be composed independently.
 */
export function usePromptPreview(
  promptId: string,
  args: Record<string, string>,
): PromptPreviewState {
  const intl = useIntl();
  const [isLoading, setLoading] = useState(false);
  const [result, setResult] = useState<PreviewSuccess | null>(null);
  const [error, setError] = useState<PreviewFailure | null>(null);

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

  return {
    run,
    isLoading,
    result,
    error,
    hasRun: result !== null || error !== null,
  };
}
