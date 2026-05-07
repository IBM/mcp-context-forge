import { useMemo } from "react";
import { Plus, MoreHorizontal, Wrench } from "lucide-react";
import { useQuery } from "@/hooks/useQuery";
import type { Tool, ToolGroup } from "@/types/tool";
import { Card, CardHeader, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

function buildGroups(tools: Tool[]): ToolGroup[] {
  const map = new Map<string, ToolGroup>();
  for (const tool of tools) {
    const slug = tool.gatewaySlug || "standalone";
    if (!map.has(slug)) {
      map.set(slug, { gatewaySlug: slug, gatewayId: tool.gatewayId, tools: [], isActive: false });
    }
    const group = map.get(slug)!;
    group.tools.push(tool);
    if (tool.enabled && tool.reachable) group.isActive = true;
  }
  return Array.from(map.values());
}

function ToolGroupCard({ group }: { group: ToolGroup }) {
  return (
    <Card size="sm">
      <CardHeader>
        <div className="flex items-center gap-3">
          <div className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded bg-fuchsia-400">
            <Wrench className="h-3.5 w-3.5 text-black" />
          </div>

          <div className="flex min-w-0 flex-1 items-center gap-2">
            <span className="truncate text-sm font-semibold text-neutral-500 dark:text-neutral-400">
              {group.gatewaySlug}
            </span>
            <span className="whitespace-nowrap text-sm font-semibold text-neutral-900 dark:text-white">
              {group.tools.length} {group.tools.length === 1 ? "tool" : "tools"}
            </span>
            <span
              className={`h-1.5 w-1.5 flex-shrink-0 rounded-full ${group.isActive ? "bg-emerald-500" : "bg-gray-500"}`}
            />
          </div>

          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-label={`More options for ${group.gatewaySlug}`}
            className="h-7 w-7 p-0"
          >
            <MoreHorizontal className="h-4 w-4" />
          </Button>
        </div>
      </CardHeader>

      <CardContent>
        <div className="flex flex-wrap gap-1">
          {group.tools.map((tool) => (
            <span
              key={tool.id}
              className="inline-flex items-center rounded bg-neutral-800 px-1.5 py-0.5 text-[10px] font-medium leading-none text-white"
              title={tool.description}
            >
              {tool.name}
            </span>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function AddToolsCard({ onAddServer }: { onAddServer: () => void }) {
  return (
    <Card
      size="sm"
      className="cursor-pointer transition-opacity hover:opacity-90"
      onClick={onAddServer}
    >
      <CardHeader>
        <div className="flex items-center gap-3">
          <div className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded bg-neutral-900 shadow-sm dark:bg-white">
            <Plus className="h-3.5 w-3.5 text-white dark:text-neutral-900" />
          </div>
          <span className="text-sm font-semibold text-neutral-900 dark:text-white">Add tools</span>
        </div>
      </CardHeader>
      <CardContent>
        <p className="text-sm leading-relaxed text-neutral-500 dark:text-neutral-400">
          Tools will appear automatically when you connect a MCP server. Or, register a REST
          endpoint as a standalone tool.
        </p>
      </CardContent>
    </Card>
  );
}

export function Tools() {
  const { data: toolsData, error, isLoading } = useQuery<Tool[]>("/tools?limit=0");

  const groups = useMemo(() => buildGroups(toolsData ?? []), [toolsData]);

  return (
    <div className="p-6">
      <h1 className="mb-6 text-base font-semibold text-neutral-900 dark:text-white">Tools</h1>

      {isLoading && (
        <div
          role="status"
          aria-live="polite"
          aria-busy="true"
          className="flex items-center justify-center p-12"
        >
          <span className="sr-only">Loading tools, please wait...</span>
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-gray-200 border-t-blue-600 dark:border-gray-700 dark:border-t-blue-400" />
        </div>
      )}

      {error && (
        <div
          className="mb-6 rounded-lg border border-red-200 bg-red-50 p-4 dark:border-red-800 dark:bg-red-900/20"
          role="alert"
          aria-live="assertive"
        >
          <h3 className="mb-1 font-semibold">Error loading tools</h3>
          <p className="text-red-800 dark:text-red-200">{error.message}</p>
        </div>
      )}

      {!isLoading && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2 xl:grid-cols-2 2xl:grid-cols-3">
          <AddToolsCard onAddServer={() => {}} />
          {groups.map((group) => (
            <ToolGroupCard key={group.gatewaySlug} group={group} />
          ))}
        </div>
      )}
    </div>
  );
}
