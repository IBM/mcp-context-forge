import { useEffect, useRef, useState } from "react";
import { Highlight, themes, type Language } from "prism-react-renderer";
import { Copy } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { copyToClipboard } from "@/lib/clipboard";
import { cn } from "@/lib/utils";

const COPY_FEEDBACK_DURATION_MS = 1500;

export type CodeBlockLanguage = "bash" | "json" | "python" | "tsx" | "typescript";

export interface CodeBlockProps {
  code: string;
  language: CodeBlockLanguage;
  /** aria-label for the Copy button. */
  copyLabel?: string;
  /** When set, clicking Copy writes to the clipboard and shows this label in a tooltip. */
  copiedLabel?: string;
  /** Invoked when the user clicks Copy. Ignored when `copiedLabel` is set. */
  onCopy?: (code: string) => void;
  /** Hide the built-in Copy affordance. */
  hideCopy?: boolean;
  /** aria-label fallback when `copyLabel` is not supplied. */
  copyAriaLabel?: string;
  className?: string;
  /** Pre-element padding override (defaults to p-4). */
  padding?: string;
}

const TOKEN_LANGUAGE: Record<CodeBlockLanguage, Language> = {
  bash: "bash",
  json: "json",
  python: "python",
  tsx: "tsx",
  typescript: "tsx",
};

/**
 * Always-dark monospace code block with prism-react-renderer syntax
 * highlighting. Use anywhere a `<pre><code>` snippet appears in the UI;
 * code blocks are intentionally dark in light mode too (a common docs/IDE
 * convention).
 *
 * Token coloring comes from the `vsDark` theme; that pairs reasonably well
 * with the rewrite's neutral-900/950 backgrounds without per-token overrides.
 *
 * This component is intentionally i18n-free — callers pass a translated
 * `copiedLabel` when they want tooltip feedback on copy.
 */
export function CodeBlock({
  code,
  language,
  copyLabel,
  copiedLabel,
  onCopy,
  hideCopy = false,
  copyAriaLabel,
  className,
  padding = "p-4",
}: CodeBlockProps) {
  const [copied, setCopied] = useState(false);
  const timeoutRef = useRef<number | null>(null);
  const prismLanguage = TOKEN_LANGUAGE[language];
  const ariaLabel = copyLabel ?? copyAriaLabel ?? "Copy code";

  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        window.clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  const handleCopy = () => {
    if (copiedLabel) {
      copyToClipboard(code);
      setCopied(true);
      if (timeoutRef.current) {
        window.clearTimeout(timeoutRef.current);
      }
      timeoutRef.current = window.setTimeout(() => {
        setCopied(false);
        timeoutRef.current = null;
      }, COPY_FEEDBACK_DURATION_MS);
      return;
    }
    onCopy?.(code);
  };

  return (
    <div className={cn("relative", className)}>
      <Highlight code={code} language={prismLanguage} theme={themes.vsDark}>
        {({ className: prismClassName, style, tokens, getLineProps, getTokenProps }) => (
          <pre
            className={cn(
              "max-h-[420px] overflow-auto rounded-md border border-border bg-neutral-900 font-mono text-[12px] leading-relaxed dark:bg-neutral-950",
              padding,
              !hideCopy && "pr-12",
              prismClassName,
            )}
            style={style}
          >
            <code>
              {tokens.map((line, i) => {
                // prism-react-renderer types `key` loosely as `{}`; strip it
                // out of the spread so React uses our map index instead.
                const { key: _lineKey, ...lineRest } = getLineProps({ line });
                return (
                  <div key={i} {...lineRest}>
                    {line.map((token, j) => {
                      const { key: _tokenKey, ...tokenRest } = getTokenProps({ token });
                      return <span key={j} {...tokenRest} />;
                    })}
                  </div>
                );
              })}
            </code>
          </pre>
        )}
      </Highlight>
      {!hideCopy && (
        <div className="absolute right-2 top-2">
          {copiedLabel ? (
            <TooltipProvider delayDuration={0}>
              <Tooltip open={copied}>
                <TooltipTrigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-xs"
                    className="size-7 text-neutral-400 hover:bg-neutral-800 hover:text-neutral-100"
                    aria-label={ariaLabel}
                    onClick={handleCopy}
                  >
                    <Copy className="size-3.5" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="top">{copiedLabel}</TooltipContent>
              </Tooltip>
            </TooltipProvider>
          ) : (
            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              className="size-7 text-neutral-400 hover:bg-neutral-800 hover:text-neutral-100"
              aria-label={ariaLabel}
              onClick={handleCopy}
            >
              <Copy className="size-3.5" />
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
