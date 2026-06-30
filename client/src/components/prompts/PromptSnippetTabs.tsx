import { useMemo } from "react";
import { useIntl } from "react-intl";
import { Copy } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { copyToClipboard } from "@/components/gateways/utils";
import { TOKEN_ENV, URL_ENV } from "./snippets/constants";
import { buildCurl } from "./snippets/buildCurl";
import { buildJsonRpc } from "./snippets/buildJsonRpc";
import { buildPython } from "./snippets/buildPython";
import { buildTypescript } from "./snippets/buildTypescript";

export interface PromptSnippetTabsProps {
  promptName: string;
  args: Record<string, string>;
}

interface SnippetSpec {
  value: string;
  labelId: string;
  language: string;
  build: (input: { promptName: string; args: Record<string, string> }) => string;
}

const SNIPPETS: SnippetSpec[] = [
  {
    value: "curl",
    labelId: "prompts.details.code.tab.curl",
    language: "curl",
    build: buildCurl,
  },
  {
    value: "jsonRpc",
    labelId: "prompts.details.code.tab.jsonRpc",
    language: "JSON-RPC",
    build: buildJsonRpc,
  },
  {
    value: "python",
    labelId: "prompts.details.code.tab.python",
    language: "Python",
    build: buildPython,
  },
  {
    value: "typescript",
    labelId: "prompts.details.code.tab.typescript",
    language: "TypeScript",
    build: buildTypescript,
  },
];

export function PromptSnippetTabs({ promptName, args }: PromptSnippetTabsProps) {
  const intl = useIntl();

  const rendered = useMemo(
    () => SNIPPETS.map((spec) => ({ ...spec, text: spec.build({ promptName, args }) })),
    [promptName, args],
  );

  return (
    <Tabs defaultValue="curl" className="gap-3">
      <TabsList className="w-fit">
        {SNIPPETS.map((spec) => (
          <TabsTrigger key={spec.value} value={spec.value}>
            {intl.formatMessage({ id: spec.labelId })}
          </TabsTrigger>
        ))}
      </TabsList>

      {rendered.map((snippet) => (
        <TabsContent key={snippet.value} value={snippet.value} className="space-y-2">
          <div className="relative">
            <pre className="max-h-[320px] overflow-auto rounded-md border border-border bg-neutral-50 p-3 pr-12 font-mono text-[12px] leading-relaxed text-foreground dark:bg-neutral-900">
              <code>{snippet.text}</code>
            </pre>
            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              className="absolute right-2 top-2 size-7 text-muted-foreground"
              aria-label={intl.formatMessage(
                { id: "prompts.details.code.copyAriaLabel" },
                { language: snippet.language },
              )}
              onClick={() => {
                copyToClipboard(snippet.text);
                toast.success(
                  intl.formatMessage(
                    { id: "prompts.details.code.copySuccess" },
                    { language: snippet.language },
                  ),
                );
              }}
            >
              <Copy className="size-3.5" />
            </Button>
          </div>

          <SnippetFooter />
        </TabsContent>
      ))}
    </Tabs>
  );
}

function SnippetFooter() {
  const intl = useIntl();
  return (
    <dl className="grid grid-cols-[max-content_minmax(0,1fr)] gap-x-3 gap-y-0.5 text-[11px] text-muted-foreground">
      <dt>{intl.formatMessage({ id: "prompts.details.code.endpoint" })}</dt>
      <dd className="font-mono">
        ${URL_ENV}/prompts/{`{name}`}
      </dd>
      <dt>{intl.formatMessage({ id: "prompts.details.code.auth" })}</dt>
      <dd className="font-mono">${TOKEN_ENV}</dd>
    </dl>
  );
}
