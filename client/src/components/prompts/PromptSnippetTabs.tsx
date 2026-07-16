import { useMemo, type ReactNode } from "react";
import { useIntl } from "react-intl";

import { CodeBlock, type CodeBlockLanguage } from "@/components/ui/code-block";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { buildCurl } from "./snippets/buildCurl";
import { buildJsonRpc } from "./snippets/buildJsonRpc";
import { buildPython } from "./snippets/buildPython";
import { buildTypescript } from "./snippets/buildTypescript";

export interface PromptSnippetTabsProps {
  promptName: string;
  args: Record<string, string>;
  /** Currently-active language tab. Controlled by the parent. */
  value: string;
  /** Fired when the user activates a different language tab. */
  onValueChange: (value: string) => void;
  /** Rendered to the right of the tab row — typically the Preview button. */
  actions?: ReactNode;
}

interface SnippetSpec {
  value: string;
  labelId: string;
  language: string;
  prismLanguage: CodeBlockLanguage;
  build: (input: { promptName: string; args: Record<string, string> }) => string;
}

const SNIPPETS: SnippetSpec[] = [
  {
    value: "curl",
    labelId: "prompts.details.code.tab.curl",
    language: "curl",
    prismLanguage: "bash",
    build: buildCurl,
  },
  {
    value: "jsonRpc",
    labelId: "prompts.details.code.tab.jsonRpc",
    language: "JSON-RPC",
    prismLanguage: "json",
    build: buildJsonRpc,
  },
  {
    value: "python",
    labelId: "prompts.details.code.tab.python",
    language: "Python",
    prismLanguage: "python",
    build: buildPython,
  },
  {
    value: "typescript",
    labelId: "prompts.details.code.tab.typescript",
    language: "TypeScript",
    prismLanguage: "tsx",
    build: buildTypescript,
  },
];

export function PromptSnippetTabs({
  promptName,
  args,
  value,
  onValueChange,
  actions,
}: PromptSnippetTabsProps) {
  const intl = useIntl();

  const rendered = useMemo(
    () => SNIPPETS.map((spec) => ({ ...spec, text: spec.build({ promptName, args }) })),
    [promptName, args],
  );

  const copiedLabel = intl.formatMessage({ id: "prompts.details.code.copySuccess" });

  return (
    <Tabs value={value} onValueChange={onValueChange}>
      <div className="mb-2 flex items-center justify-between gap-4">
        <TabsList>
          {SNIPPETS.map((spec) => (
            <TabsTrigger key={spec.value} value={spec.value}>
              {intl.formatMessage({ id: spec.labelId })}
            </TabsTrigger>
          ))}
        </TabsList>
        {actions}
      </div>

      {rendered.map((snippet) => (
        <TabsContent key={snippet.value} value={snippet.value}>
          <CodeBlock
            code={snippet.text}
            language={snippet.prismLanguage}
            copyLabel={intl.formatMessage(
              { id: "prompts.details.code.copyAriaLabel" },
              { language: snippet.language },
            )}
            copiedLabel={copiedLabel}
          />
        </TabsContent>
      ))}
    </Tabs>
  );
}
