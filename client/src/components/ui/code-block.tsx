import { Highlight, themes, type Language } from "prism-react-renderer";
import { useIntl } from "react-intl";
import { Copy } from "lucide-react";

import { Button } from "@/components/ui/button";
import { copyToClipboard } from "@/components/gateways/utils";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

export type CodeBlockLanguage = "bash" | "json" | "python" | "tsx" | "typescript";

export interface CodeBlockProps {
  code: string;
  language: CodeBlockLanguage;
  /** Optional human-readable label used in the Copy button aria-label and toast. */
  copyLabel?: string;
  /** Hide the built-in Copy affordance. */
  hideCopy?: boolean;
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
 */
export function CodeBlock({
  code,
  language,
  copyLabel,
  hideCopy = false,
  className,
  padding = "p-4",
}: CodeBlockProps) {
  const intl = useIntl();
  const prismLanguage = TOKEN_LANGUAGE[language];

  const onCopy = () => {
    copyToClipboard(code);
    if (copyLabel) {
      toast.success(
        intl.formatMessage(
          { id: "prompts.details.code.copySuccess" },
          { language: copyLabel },
        ),
      );
    }
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
                // prism-react-renderer types `key` loosely as `{}`; use the
                // map index instead and strip the prop off the spread.
                const { key: _lineKey, ...lineRest } = getLineProps({ line });
                void _lineKey;
                return (
                  <div key={i} {...lineRest}>
                    {line.map((token, j) => {
                      const { key: _tokenKey, ...tokenRest } = getTokenProps({ token });
                      void _tokenKey;
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
          aria-label={
            copyLabel
              ? intl.formatMessage(
                  { id: "prompts.details.code.copyAriaLabel" },
                  { language: copyLabel },
                )
              : intl.formatMessage({ id: "prompts.details.code.copy" })
          }
          onClick={onCopy}
        >
          <Copy className="size-3.5" />
        </Button>
      )}
    </div>
  );
}
