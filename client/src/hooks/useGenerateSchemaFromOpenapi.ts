import { useCallback, useState } from "react";
import { useIntl } from "react-intl";
import { ApiError } from "@/api/client";
import { toolsApi } from "@/api/tools";

/**
 * Result handed to {@link GenerateArgs.onSuccess} when generation succeeds.
 *
 * `inputSchema` / `outputSchema` are pretty-printed JSON strings ready to drop
 * straight into the form's textareas (empty string when the backend returned
 * `null` for that schema).
 */
export interface GeneratedSchemas {
  inputSchema: string;
  outputSchema: string;
  specUrl: string;
}

export interface GenerateArgs {
  /** The tool URL (identifies the OpenAPI path + host). */
  url: string;
  /** HTTP method to look up in the spec. */
  requestType: string;
  /** Called with the pretty-printed schemas when generation succeeds. */
  onSuccess: (result: GeneratedSchemas) => void;
  /** Called with a localized, user-facing message when generation fails. */
  onError?: (message: string) => void;
  /** Called when the backend reports the spec host needs authentication. */
  onRequiresAuth?: () => void;
}

export interface UseGenerateSchemaFromOpenapiReturn {
  isGenerating: boolean;
  /** The `spec_url` the backend used, once generation has succeeded. */
  generatedSpecUrl: string;
  /** Optional direct OpenAPI spec URL the user can supply as a fallback. */
  openApiSpecUrl: string;
  setOpenApiSpecUrl: (value: string) => void;
  /** Whether the direct-spec-URL fallback input should be shown. */
  showSpecUrlInput: boolean;
  generate: (args: GenerateArgs) => Promise<void>;
  reset: () => void;
}

/**
 * Returns a validated `https?:` URL string, or `undefined` when the input is
 * empty or not a fetchable web URL.
 */
function safeHttpUrl(value: string): string | undefined {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  try {
    const parsed = new URL(trimmed);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? trimmed : undefined;
  } catch {
    return undefined;
  }
}

/**
 * Encapsulates the "Generate schemas from OpenAPI" async flow: URL guarding,
 * the API call, and mapping the backend's typed HTTP status codes to clear
 * copy. Outcomes are reported through callbacks so the caller (the tool form)
 * stays the single owner of the editable schema fields.
 */
export function useGenerateSchemaFromOpenapi(): UseGenerateSchemaFromOpenapiReturn {
  const intl = useIntl();
  const [isGenerating, setIsGenerating] = useState(false);
  const [generatedSpecUrl, setGeneratedSpecUrl] = useState("");
  const [openApiSpecUrl, setOpenApiSpecUrl] = useState("");
  const [showSpecUrlInput, setShowSpecUrlInput] = useState(false);

  const reset = useCallback(() => {
    setIsGenerating(false);
    setGeneratedSpecUrl("");
    setOpenApiSpecUrl("");
    setShowSpecUrlInput(false);
  }, []);

  const generate = useCallback(
    async ({ url, requestType, onSuccess, onError, onRequiresAuth }: GenerateArgs) => {
      // Guard: only ever call the backend for a fetchable web URL. Bail out
      // silently (no error) for empty/non-http/malformed URLs.
      const safeUrl = safeHttpUrl(url);
      if (!safeUrl) return;

      const safeSpecUrl = safeHttpUrl(openApiSpecUrl);

      setIsGenerating(true);
      try {
        const result = await toolsApi.generateSchemasFromOpenapi({
          url: safeUrl,
          request_type: requestType,
          ...(safeSpecUrl ? { openapi_url: safeSpecUrl } : {}),
        });

        if (result.success) {
          setGeneratedSpecUrl(result.spec_url ?? "");
          onSuccess({
            inputSchema: result.input_schema ? JSON.stringify(result.input_schema, null, 2) : "",
            outputSchema: result.output_schema ? JSON.stringify(result.output_schema, null, 2) : "",
            specUrl: result.spec_url ?? "",
          });
        } else {
          setGeneratedSpecUrl("");
          setShowSpecUrlInput(true);
          onError?.(
            result.message || intl.formatMessage({ id: "tools.form.error.generateSchemaFailed" }),
          );
        }
      } catch (error) {
        setGeneratedSpecUrl("");
        // Offer the direct-spec-URL fallback whenever generation fails, so the
        // user can point at a reachable OpenAPI document and retry.
        setShowSpecUrlInput(true);

        // Map the backend's typed HTTP status codes to clear, actionable copy.
        let message = intl.formatMessage({ id: "tools.form.error.generateSchemaUrl" });
        if (error instanceof ApiError) {
          const body = error.body as { message?: string; requires_auth?: boolean } | undefined;
          if (body?.requires_auth) {
            onRequiresAuth?.();
          }
          switch (error.status) {
            case 400:
              message = intl.formatMessage({ id: "tools.form.error.generateSchema.ssrf" });
              break;
            case 404: {
              let path = safeUrl;
              try {
                path = new URL(safeUrl).pathname || path;
              } catch {
                // Keep the raw URL when it cannot be parsed.
              }
              message = intl.formatMessage(
                { id: "tools.form.error.generateSchema.notFound" },
                { path, method: requestType },
              );
              break;
            }
            case 502: {
              // The backend wraps an upstream 401/403 from the spec host as a
              // 502 ("OpenAPI spec server returned HTTP 401"). Surface that as
              // an auth problem rather than a generic "unreachable" message.
              const upstream = body?.message ?? "";
              message = /\bHTTP (401|403)\b/.test(upstream)
                ? intl.formatMessage({ id: "tools.form.error.generateSchema.specAuthRequired" })
                : intl.formatMessage({ id: "tools.form.error.generateSchema.fetchFailed" });
              break;
            }
            case 500:
              message = intl.formatMessage({ id: "tools.form.error.generateSchema.generic" });
              break;
            default:
              if (body?.message) {
                message = body.message;
              }
          }
        }
        onError?.(message);
      } finally {
        setIsGenerating(false);
      }
    },
    [openApiSpecUrl, intl],
  );

  return {
    isGenerating,
    generatedSpecUrl,
    openApiSpecUrl,
    setOpenApiSpecUrl,
    showSpecUrlInput,
    generate,
    reset,
  };
}
