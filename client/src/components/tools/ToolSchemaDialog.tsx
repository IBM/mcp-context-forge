import { Copy, Code } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { copyToClipboard } from "@/lib/clipboard";
import { JsonHighlighter } from "@/components/ui/json-highlighter";
import type { Tool } from "@/types/tool";

interface ToolSchemaDialogProps {
  tool: Tool | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function SchemaSection({
  title,
  schema,
}: {
  title: string;
  schema: Record<string, unknown> | undefined;
}) {
  const schemaText = schema ? JSON.stringify(schema, null, 2) : "{}";

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium text-foreground">{title}</h3>
      <div className="relative">
        <pre className="max-h-[280px] overflow-auto rounded-md border border-neutral-700 bg-neutral-900 p-4 text-xs leading-relaxed text-neutral-100 whitespace-pre-wrap break-words">
          <code className="break-words">
            <JsonHighlighter text={schemaText} />
          </code>
        </pre>
        <Button
          type="button"
          variant="ghost"
          size="icon-xs"
          aria-label={`Copy ${title.toLowerCase()}`}
          className="absolute right-2 top-2 size-6 bg-neutral-800/80 text-neutral-400 hover:bg-neutral-700 hover:text-neutral-100"
          onClick={() => copyToClipboard(schemaText)}
        >
          <Copy className="size-3.5" />
        </Button>
      </div>
    </div>
  );
}

export function ToolSchemaDialog({ tool, open, onOpenChange }: ToolSchemaDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <div className="flex items-center gap-2">
            <div
              className="flex h-6 w-6 items-center justify-center rounded"
              style={{ backgroundColor: "#6FFF9F" }}
            >
              <Code className="h-4 w-4 text-black" />
            </div>
            <DialogTitle>Tool schema</DialogTitle>
          </div>
          <DialogDescription className="sr-only">
            View the input and output schemas for this tool
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-6">
          <SchemaSection title="Input" schema={tool?.inputSchema} />
          <SchemaSection title="Output" schema={tool?.outputSchema} />
        </div>

        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
