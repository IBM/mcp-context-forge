import { useCallback, useEffect, useState } from "react";
import { useIntl } from "react-intl";
import { toast } from "sonner";

import { ApiError } from "@/api/client";
import { promptsApi, type RenderedPrompt } from "@/api/prompts";

export interface PreviewSuccess {
  rendered: RenderedPrompt;
  renderTimeMs: number;
  status: number;
}

export interface PreviewFailure {
  message: string;
  renderTimeMs: number;
  status: number | null;
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
 *
 * Addresses the prompt by name (matches what the Code-tab snippets show and
 * what MCP-spec clients use on the wire).
 */
export function usePromptPreview(
  promptName: string,
  args: Record<string, string>,
): PromptPreviewState {
  const intl = useIntl();
  const [isLoading, setLoading] = useState(false);
  const [result, setResult] = useState<PreviewSuccess | null>(null);
  const [error, setError] = useState<PreviewFailure | null>(null);

  // Clear stale result/error when the caller switches to a different prompt.
  // Without this, a drawer that re-uses one instance across prompts would show
  // prompt A's rendered messages after the user navigates to prompt B.
  useEffect(() => {
    setResult(null);
    setError(null);
  }, [promptName]);

  const run = useCallback(async () => {
    setLoading(true);
    setError(null);
    const startedAt = performance.now();
    try {
      const { rendered, status } = await promptsApi.render(promptName, args);
      const renderTimeMs = Math.round(performance.now() - startedAt);
      setResult({ rendered, renderTimeMs, status });
    } catch (err) {
      const renderTimeMs = Math.round(performance.now() - startedAt);
      const status = err instanceof ApiError ? err.status : null;
      const message =
        err instanceof ApiError
          ? typeof err.body === "object" && err.body !== null && "detail" in err.body
            ? String((err.body as { detail: unknown }).detail)
            : err.message
          : err instanceof Error
            ? err.message
            : "Unknown error";
      setError({ message, renderTimeMs, status });
      setResult(null);
      toast.error(intl.formatMessage({ id: "prompts.details.preview.error" }));
    } finally {
      setLoading(false);
    }
  }, [promptName, args, intl]);

  return {
    run,
    isLoading,
    result,
    error,
    hasRun: result !== null || error !== null,
  };
}
