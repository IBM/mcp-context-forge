import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../ui/select";
import { Textarea } from "../ui/textarea";
import { JsonHighlighter } from "../ui/json-highlighter";
import { copyToClipboard } from "@/components/gateways/utils";
import { cn } from "@/lib/utils";

interface TestConnectionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  serverName: string;
  serverUrl: string;
}

type TestStatus = "idle" | "testing" | "success" | "error";

interface TestResponse {
  status_code: number;
  latency_ms: number;
  body?: string | Record<string, unknown>;
}

const HTTP_METHODS = ["Get", "Post", "Put", "Delete", "Patch"] as const;

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
  const [response, setResponse] = useState<TestResponse | null>(null);
  const [error, setError] = useState<string>("");
  const titleRef = useRef<HTMLHeadingElement>(null);

  // Reset state when dialog opens
  useEffect(() => {
    if (open) {
      setStatus("idle");
      setMethod("Get");
      setUrl(serverUrl);
      setPath("");
      setHeaders("");
      setContentType("application/json");
      setBody("");
      setResponse(null);
      setError("");
    }
  }, [open, serverUrl]);

  const handleTest = useCallback(() => {
    setResponse(null);
    setError("");

    // Validate JSON fields before they would be sent.
    if (headers.trim()) {
      try {
        const parsed = JSON.parse(headers);
        if (typeof parsed !== "object" || Array.isArray(parsed)) {
          throw new Error("Headers must be a JSON object");
        }
      } catch (e) {
        setStatus("error");
        setError(`Invalid headers JSON: ${e instanceof Error ? e.message : "Parse error"}`);
        return;
      }
    }

    if (body.trim() && method !== "Get" && method !== "HEAD") {
      try {
        JSON.parse(body);
      } catch (e) {
        setStatus("error");
        setError(`Invalid body JSON: ${e instanceof Error ? e.message : "Parse error"}`);
        return;
      }
    }

    // TODO(#5326): Send the request to `POST /v1/mcp-servers/test` once that
    // endpoint exists. The React UI must not call the legacy `/admin/**` routes
    // (reserved for the HTMX admin UI), so live connection testing is disabled
    // until the v1 endpoint is implemented.
    // https://github.com/IBM/mcp-context-forge/issues/5326
    setStatus("error");
    setError("Connection testing isn't available yet — the API endpoint is pending (#5326).");
  }, [headers, body, method]);

  const handleClose = useCallback(() => {
    onOpenChange(false);
  }, [onOpenChange]);

  const responseBodyText = useMemo(() => {
    if (!response?.body) return "";
    return typeof response.body === "string"
      ? response.body
      : JSON.stringify(response.body, null, 2);
  }, [response]);

  const headline = response
    ? `Status: ${response.status_code} ${status === "success" ? "OK" : "error"}`
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
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://mcp.github.com/mcp"
                disabled={isTesting}
                className="bg-transparent dark:bg-transparent"
              />
            </div>

            {/* Method */}
            <div className="space-y-2">
              <FieldLabel>Method</FieldLabel>
              <div
                role="radiogroup"
                aria-label="Method"
                className="flex w-full gap-1 rounded-md bg-muted p-1"
              >
                {HTTP_METHODS.map((m) => (
                  <button
                    key={m}
                    type="button"
                    role="radio"
                    aria-checked={method === m}
                    onClick={() => setMethod(m)}
                    disabled={isTesting}
                    className={cn(
                      "flex-1 rounded-sm px-3 py-1.5 text-sm font-medium transition-colors disabled:pointer-events-none disabled:opacity-50",
                      method === m
                        ? "bg-background text-foreground shadow-sm"
                        : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {m}
                  </button>
                ))}
              </div>
            </div>

            {/* Path */}
            <div className="space-y-2">
              <FieldLabel htmlFor="path" hint="Optional path appended to the URL.">
                Path
              </FieldLabel>
              <Input
                id="path"
                value={path}
                onChange={(e) => setPath(e.target.value)}
                placeholder="/health"
                disabled={isTesting}
                className="bg-transparent dark:bg-transparent"
              />
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
                onChange={(e) => setHeaders(e.target.value)}
                placeholder="Add request headers as JSON..."
                className="min-h-[96px] bg-transparent font-mono text-sm focus-visible:ring-1 focus-visible:ring-offset-0"
                disabled={isTesting}
              />
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
                  onChange={(e) => setBody(e.target.value)}
                  placeholder="Add request body as JSON..."
                  className="min-h-[116px] bg-transparent font-mono text-sm focus-visible:ring-1 focus-visible:ring-offset-0"
                  disabled={isTesting}
                />
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
                    Latency: {response.latency_ms} ms
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

          <Button variant="ghost" onClick={handleClose} disabled={isTesting}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
