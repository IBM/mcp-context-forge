import { Highlight, themes, type Language } from "prism-react-renderer";
import { Copy } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type CodeBlockLanguage = "bash" | "json" | "python" | "tsx" | "typescript";

export interface CodeBlockProps {
  code: string;
  language: CodeBlockLanguage;
  /** aria-label for the Copy button; also referenced by callers wiring toasts. */
  copyLabel?: string;
  /** Invoked when the user clicks Copy. Callers own the clipboard write and any feedback toast. */
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
 * This component is intentionally i18n-free — callers own the copy-feedback
 * toast so the message can match the caller's domain (prompt, tool, resource).
 */
export function CodeBlock({
  code,
  language,
  copyLabel,
  onCopy,
  hideCopy = false,
  copyAriaLabel,
  className,
  padding = "p-4",
}: CodeBlockProps) {
  const prismLanguage = TOKEN_LANGUAGE[language];
  const ariaLabel = copyLabel ?? copyAriaLabel ?? "Copy code";

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
        <Button
          type="button"
          variant="ghost"
          size="icon-xs"
          className="absolute right-2 top-2 size-7 text-neutral-400 hover:bg-neutral-800 hover:text-neutral-100"
          aria-label={ariaLabel}
          onClick={() => onCopy?.(code)}
        >
          <Copy className="size-3.5" />
        </Button>
      )}
    </div>
  );
}
