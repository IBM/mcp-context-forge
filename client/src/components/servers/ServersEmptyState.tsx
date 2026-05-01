import { Server } from "lucide-react";
import { Button } from "../ui/button";

interface ServersEmptyStateProps {
  onAction: () => void;
}

export function ServersEmptyState({ onAction }: ServersEmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-12 px-4">
      <div className="rounded-full bg-gray-100 dark:bg-gray-800 p-6 mb-4">
        <Server className="w-12 h-12 text-gray-400 dark:text-gray-600" />
      </div>
      <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-2">
        No MCP servers configured
      </h3>
      <p className="text-gray-600 dark:text-gray-400 text-center mb-6 max-w-md">
        Get started by adding your first MCP server to connect tools, resources, and prompts.
      </p>
      <Button onClick={onAction}>New Server</Button>
    </div>
  );
}
