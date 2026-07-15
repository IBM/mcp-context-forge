import { useCallback, useEffect, useRef, useState } from "react";
import { useIntl } from "react-intl";
import { toast } from "sonner";

import { ApiError } from "@/api/client";
import { promptsApi, type RenderedPrompt } from "@/api/prompts";
import { parseApiError } from "@/lib/errorUtils";

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
  const abortRef = useRef<AbortController | null>(null);

  // Clear stale result/error when the caller switches to a different prompt.
  // Without this, a drawer that re-uses one instance across prompts would show
  // prompt A's rendered messages after the user navigates to prompt B.
  useEffect(() => {
    setResult(null);
    setError(null);
  }, [promptName]);

  // Abort any in-flight preview when the hook unmounts. PromptCodeTab is keyed
  // by prompt id, so this also fires on prompt switch — resolutions that arrive
  // after the switch never touch state on the unmounted instance.
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const run = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setError(null);
    const startedAt = performance.now();
    try {
      const { rendered, status } = await promptsApi.render(promptName, args, {
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      const renderTimeMs = Math.round(performance.now() - startedAt);
      setResult({ rendered, renderTimeMs, status });
    } catch (err) {
      if (controller.signal.aborted) return;
      const renderTimeMs = Math.round(performance.now() - startedAt);
      const status = err instanceof ApiError ? err.status : null;
      const message = parseApiError(err, err instanceof Error ? err.message : "Unknown error");
      setError({ message, renderTimeMs, status });
      setResult(null);
      toast.error(intl.formatMessage({ id: "prompts.details.preview.error" }));
    } finally {
      if (!controller.signal.aborted) {
        setLoading(false);
      }
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
