import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { z } from "zod";
import * as RadioGroupPrimitive from "@radix-ui/react-radio-group";
import { CircleCheck, CircleAlert, Copy, Info, Loader2, TestTubeDiagonal } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../ui/dialog";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { RadioGroup } from "../ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../ui/select";
import { Textarea } from "../ui/textarea";
import { JsonHighlighter } from "../ui/json-highlighter";
import { copyToClipboard } from "@/lib/clipboard";
import { serversApi } from "@/api/servers";
import type { GatewayTestRequest, GatewayTestResponse } from "@/generated/types";
import { parseApiError } from "@/lib/errorUtils";
import { cn } from "@/lib/utils";

interface TestConnectionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  serverName: string;
  serverUrl: string;
}

type TestStatus = "idle" | "testing" | "success" | "error";

const HTTP_METHODS = ["Get", "Post", "Put", "Delete", "Patch"] as const;

// Matches the URL validation convention used in useMCPServerForm/useToolForm:
// required, and constrained to http/https schemes.
const testUrlSchema = z
  .string()
  .trim()
  .min(1, "URL is required.")
  .refine(
    (value) => {
      try {
        const parsed = new URL(value);
        return parsed.protocol === "http:" || parsed.protocol === "https:";
      } catch {
        return false;
      }
    },
    { message: "URL must start with http:// or https://." },
  );

type FieldErrors = {
  url?: string;
  path?: string;
  headers?: string;
  body?: string;
};

// Field-level validators. Each returns an error message, or undefined when the
// value is acceptable. Shared by the on-blur checks and the pre-submit sweep so
// the two never drift.
function validateUrl(value: string): string | undefined {
  const result = testUrlSchema.safeParse(value);
  return result.success ? undefined : result.error.issues[0].message;
}

// Path is a suffix appended to the base URL; the backend normalizes leading and
// trailing slashes, so we don't police those. This is a soft guard against the
// common fat-finger of pasting a full URL (scheme + host) into the Path field.
function validatePath(value: string): string | undefined {
  return value.includes("://")
    ? "Path shouldn't include a scheme or host (e.g. https://…)."
    : undefined;
}

function validateHeaders(value: string): string | undefined {
  if (!value.trim()) return undefined;
  try {
    const parsed = JSON.parse(value);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      return "Headers must be a JSON object.";
    }
  } catch (e) {
    return `Invalid headers JSON: ${e instanceof Error ? e.message : "Parse error"}`;
  }
  return undefined;
}

function sendsBodyFor(method: string): boolean {
  return method !== "Get" && method !== "HEAD";
}

// Only JSON bodies are validated; form-encoded (and other) content types are
// sent verbatim, so there is nothing to parse.
function validateBody(value: string, method: string, contentType: string): string | undefined {
  if (!sendsBodyFor(method) || !value.trim() || contentType !== "application/json") {
    return undefined;
  }
  try {
    JSON.parse(value);
  } catch (e) {
    return `Invalid body JSON: ${e instanceof Error ? e.message : "Parse error"}`;
  }
  return undefined;
}

function FieldLabel({
  htmlFor,
  children,
  required,
  hint,
}: {
  htmlFor?: string;
  children: React.ReactNode;
  required?: boolean;
  hint?: string;
}) {
  return (
    <Label htmlFor={htmlFor} className="flex items-center gap-1 text-sm font-medium">
      <span>
        {children}
        {required && <span className="ml-0.5 text-destructive">*</span>}
      </span>
      {hint && (
        <Info className="size-3.5 text-muted-foreground">
          <title>{hint}</title>
        </Info>
      )}
    </Label>
  );
}

export function TestConnectionDialog({ open, onOpenChange, serverUrl }: TestConnectionDialogProps) {
  const [status, setStatus] = useState<TestStatus>("idle");
  const [method, setMethod] = useState<string>("Get");
  const [url, setUrl] = useState<string>("");
  const [path, setPath] = useState<string>("");
  const [headers, setHeaders] = useState<string>("");
  const [contentType, setContentType] = useState<string>("application/json");
  const [body, setBody] = useState<string>("");
  const [response, setResponse] = useState<GatewayTestResponse>(null);
  const [error, setError] = useState<string>("");
  const [errors, setErrors] = useState<FieldErrors>({});
  const titleRef = useRef<HTMLHeadingElement>(null);
  // Tracks the in-flight test request so it can be cancelled when the dialog is
  // closed, reopened, or unmounted (prevents state updates on a stale request).
  const abortRef = useRef<AbortController | null>(null);

  // Cancel any in-flight request whenever the dialog opens or closes (covers the
  // footer Close button, Escape, and overlay-dismiss uniformly), then reset state
  // on open.
  useEffect(() => {
    abortRef.current?.abort();
    if (!open) {
      return;
    }
    setStatus("idle");
    setMethod("Get");
    setUrl(serverUrl);
    setPath("");
    setHeaders("");
    setContentType("application/json");
    setBody("");
    setResponse(null);
    setError("");
    setErrors({});
  }, [open, serverUrl]);

  // Drop a field's inline error as soon as the user edits it; validation runs
  // again on blur and on submit.
  const clearError = useCallback((field: keyof FieldErrors) => {
    setErrors((prev) => (prev[field] ? { ...prev, [field]: undefined } : prev));
  }, []);

  // Cancel any in-flight request on unmount.
  useEffect(() => () => abortRef.current?.abort(), []);

  const handleTest = useCallback(async () => {
    setResponse(null);
    setError("");

    // Validate every field up front and surface problems inline; don't send a
    // request while anything is invalid.
    const nextErrors: FieldErrors = {
      url: validateUrl(url),
      path: validatePath(path),
      headers: validateHeaders(headers),
      body: validateBody(body, method, contentType),
    };
    setErrors(nextErrors);
    if (nextErrors.url || nextErrors.path || nextErrors.headers || nextErrors.body) {
      return;
    }

    // Fields are valid — parse the JSON payloads for sending. JSON bodies are
    // parsed to an object so the backend forwards them as JSON; form-encoded
    // bodies are sent as-is.
    const parsedHeaders: Record<string, string> | undefined = headers.trim()
      ? (JSON.parse(headers) as Record<string, string>)
      : undefined;

    let parsedBody: string | Record<string, unknown> | undefined;
    if (sendsBodyFor(method) && body.trim()) {
      parsedBody =
        contentType === "application/json" ? (JSON.parse(body) as Record<string, unknown>) : body;
    }

    const payload: GatewayTestRequest = {
      method: method.toUpperCase(),
      baseUrl: url.trim(),
      path: path.trim(),
      contentType,
      ...(parsedHeaders ? { headers: parsedHeaders } : {}),
      ...(parsedBody !== undefined ? { body: parsedBody } : {}),
    };

    // Cancel any previous in-flight request before starting a new one.
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setStatus("testing");
    try {
      const result = await serversApi.testConnectivity(payload, controller.signal);
      if (controller.signal.aborted) {
        return;
      }
      const statusCode = result?.statusCode ?? 0;
      const succeeded = statusCode >= 200 && statusCode < 300;
      setResponse(result);
      setStatus(succeeded ? "success" : "error");
    } catch (e) {
      if (controller.signal.aborted) {
        return;
      }
      setResponse(null);
      setStatus("error");
      setError(parseApiError(e, "Connection test failed. Please try again."));
    }
  }, [url, headers, body, method, path, contentType]);

  const handleClose = useCallback(() => {
    // The open→false effect cancels any in-flight request; just close here.
    onOpenChange(false);
  }, [onOpenChange]);

  const responseBodyText = useMemo(() => {
    if (!response?.body) return "";
    return typeof response.body === "string"
      ? response.body
      : JSON.stringify(response.body, null, 2);
  }, [response]);

  const headline = response
    ? `Status: ${response.statusCode} ${status === "success" ? "OK" : "error"}`
    : error || "Connection failed";

  const isTesting = status === "testing";
  const hasResult = status === "success" || status === "error";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-h-[90vh] w-[95vw] max-w-[1000px] overflow-y-auto"
        onOpenAutoFocus={(e) => {
          // Move focus into the dialog (so it is announced and the focus trap
          // is seeded) without landing on the pre-filled URL field.
          e.preventDefault();
          titleRef.current?.focus();
        }}
      >
        <DialogHeader>
          <div className="flex items-center gap-2">
            <div className="flex h-6 w-6 items-center justify-center rounded-sm bg-[#ffd200] text-neutral-950 shadow-sm">
              <TestTubeDiagonal className="h-4 w-4" />
            </div>
            <DialogTitle ref={titleRef} tabIndex={-1} className="outline-none">
              Test connection
            </DialogTitle>
          </div>
          <DialogDescription className="sr-only">
            Send a test request to the MCP server and inspect the response.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-6 py-2 md:grid-cols-2">
          {/* Left column — request form */}
          <div className="space-y-4">
            {/* URL */}
            <div className="space-y-2">
              <FieldLabel htmlFor="url" required hint="The full URL of the MCP server to test.">
                URL
              </FieldLabel>
              <Input
                id="url"
                value={url}
                onChange={(e) => {
                  setUrl(e.target.value);
                  clearError("url");
                }}
                onBlur={() => setErrors((prev) => ({ ...prev, url: validateUrl(url) }))}
                placeholder="https://mcp.github.com/mcp"
                disabled={isTesting}
                aria-invalid={!!errors.url}
                aria-describedby={errors.url ? "url-error" : undefined}
                className="bg-transparent dark:bg-transparent"
              />
              {errors.url && (
                <p id="url-error" className="text-sm text-red-500">
                  {errors.url}
                </p>
              )}
            </div>

            {/* Method */}
            <div className="space-y-2">
              <FieldLabel>Method</FieldLabel>
              <RadioGroup
                value={method}
                onValueChange={setMethod}
                disabled={isTesting}
                aria-label="Method"
                className="flex w-full gap-1 rounded-md bg-muted p-1"
              >
                {HTTP_METHODS.map((m) => (
                  <RadioGroupPrimitive.Item
                    key={m}
                    value={m}
                    className={cn(
                      "flex-1 rounded-sm px-3 py-1.5 text-sm font-medium transition-colors",
                      "text-muted-foreground hover:text-foreground",
                      "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
                      "disabled:pointer-events-none disabled:opacity-50",
                      "data-[state=checked]:bg-background data-[state=checked]:text-foreground data-[state=checked]:shadow-sm",
                    )}
                  >
                    {m}
                  </RadioGroupPrimitive.Item>
                ))}
              </RadioGroup>
            </div>

            {/* Path */}
            <div className="space-y-2">
              <FieldLabel htmlFor="path" hint="Optional path appended to the URL.">
                Path
              </FieldLabel>
              <Input
                id="path"
                value={path}
                onChange={(e) => {
                  setPath(e.target.value);
                  clearError("path");
                }}
                onBlur={() => setErrors((prev) => ({ ...prev, path: validatePath(path) }))}
                placeholder="/health"
                disabled={isTesting}
                aria-invalid={!!errors.path}
                aria-describedby={errors.path ? "path-error" : undefined}
                className="bg-transparent dark:bg-transparent"
              />
              {errors.path && (
                <p id="path-error" className="text-sm text-red-500">
                  {errors.path}
                </p>
              )}
            </div>

            {/* Content type */}
            <div className="space-y-2">
              <FieldLabel htmlFor="content-type">Content type</FieldLabel>
              <Select value={contentType} onValueChange={setContentType} disabled={isTesting}>
                <SelectTrigger
                  id="content-type"
                  className="w-full bg-transparent dark:bg-transparent dark:hover:bg-transparent"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="application/json">application/json</SelectItem>
                  <SelectItem value="application/x-www-form-urlencoded">
                    application/x-www-form-urlencoded
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Headers */}
            <div className="space-y-2">
              <FieldLabel htmlFor="headers" hint="Request headers as a JSON object.">
                Headers
              </FieldLabel>
              <Textarea
                id="headers"
                value={headers}
                onChange={(e) => {
                  setHeaders(e.target.value);
                  clearError("headers");
                }}
                onBlur={() => setErrors((prev) => ({ ...prev, headers: validateHeaders(headers) }))}
                placeholder="Add request headers as JSON..."
                className="min-h-[96px] bg-transparent font-mono text-sm focus-visible:ring-1 focus-visible:ring-offset-0"
                disabled={isTesting}
                aria-invalid={!!errors.headers}
                aria-describedby={errors.headers ? "headers-error" : undefined}
              />
              {errors.headers && (
                <p id="headers-error" className="text-sm text-red-500">
                  {errors.headers}
                </p>
              )}
            </div>

            {/* Body — not applicable to GET requests */}
            {method !== "Get" && (
              <div className="space-y-2">
                <FieldLabel htmlFor="body" hint="Request body sent with non-GET methods.">
                  Body
                </FieldLabel>
                <Textarea
                  id="body"
                  value={body}
                  onChange={(e) => {
                    setBody(e.target.value);
                    clearError("body");
                  }}
                  onBlur={() =>
                    setErrors((prev) => ({
                      ...prev,
                      body: validateBody(body, method, contentType),
                    }))
                  }
                  placeholder="Add request body as JSON..."
                  className="min-h-[116px] bg-transparent font-mono text-sm focus-visible:ring-1 focus-visible:ring-offset-0"
                  disabled={isTesting}
                  aria-invalid={!!errors.body}
                  aria-describedby={errors.body ? "body-error" : undefined}
                />
                {errors.body && (
                  <p id="body-error" className="text-sm text-red-500">
                    {errors.body}
                  </p>
                )}
              </div>
            )}
          </div>

          {/* Right column — response panel */}
          <div className="flex min-h-[300px] flex-col overflow-hidden rounded-md border border-input bg-transparent">
            {status === "idle" && (
              <div className="flex flex-1 items-center justify-center p-6 text-center">
                <p className="text-sm text-muted-foreground">
                  Run a test to see the response here.
                </p>
              </div>
            )}

            {isTesting && (
              <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                <p className="text-sm text-muted-foreground">Running test…</p>
              </div>
            )}

            {hasResult && (
              <div
                className="relative flex flex-1 flex-col gap-2 overflow-auto p-4"
                role={status === "error" ? "alert" : "status"}
                aria-live="polite"
              >
                {responseBodyText && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-xs"
                    aria-label="Copy response body"
                    className="absolute right-2 top-2 size-6 bg-neutral-800/80 text-neutral-400 hover:bg-neutral-700 hover:text-neutral-100"
                    onClick={() => copyToClipboard(responseBodyText)}
                  >
                    <Copy className="size-3.5" />
                  </Button>
                )}

                <div className="flex items-start gap-2 pr-8">
                  {status === "success" ? (
                    <CircleCheck className="mt-0.5 size-4 shrink-0 text-green-500" />
                  ) : (
                    <CircleAlert className="mt-0.5 size-4 shrink-0 text-destructive" />
                  )}
                  <span className="text-sm font-medium break-words text-foreground">
                    {headline}
                  </span>
                </div>

                {response && (
                  <p className="pl-6 text-[13px] text-muted-foreground">
                    Latency: {response.latencyMs} ms
                  </p>
                )}

                {responseBodyText && (
                  <div className="mt-2 space-y-1">
                    <p className="text-[13px] text-muted-foreground">Response body:</p>
                    <pre className="overflow-auto text-[13px] leading-relaxed break-words whitespace-pre-wrap text-foreground">
                      <code className="break-words">
                        <JsonHighlighter text={responseBodyText} />
                      </code>
                    </pre>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        <DialogFooter className="flex-row items-center justify-between sm:justify-between sm:space-x-0">
          <Button onClick={handleTest} disabled={isTesting}>
            {isTesting ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Running test…
              </>
            ) : (
              "Test connection"
            )}
          </Button>

          {/* Stays enabled during a test so it can cancel the in-flight request
              (closing the dialog aborts it via the open→false effect); relabels
              to "Cancel" to signal that action. */}
          <Button variant="ghost" onClick={handleClose}>
            {isTesting ? "Cancel" : "Close"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
