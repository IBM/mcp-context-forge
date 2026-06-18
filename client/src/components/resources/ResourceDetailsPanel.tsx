import { X, Trash2, FileText } from "lucide-react";
import type { Resource } from "@/types/resource";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";

interface ResourceDetailsPanelProps {
  resources: Resource[];
  gatewaySlug: string;
  open: boolean;
  onClose: () => void;
  onDeleteResource: (id: string) => void;
}

/**
 * Side panel for displaying detailed information about resources in a gateway group
 * Shows resource metadata including URI, description, MIME type, size, and tags
 *
 * @param resources - Array of resources to display
 * @param gatewaySlug - Gateway identifier for the panel title
 * @param open - Whether the panel is visible
 * @param onClose - Callback to close the panel
 * @param onDeleteResource - Callback when delete button is clicked (placeholder for future CRUD)
 */
export function ResourceDetailsPanel({
  resources,
  gatewaySlug,
  open,
  onClose,
  onDeleteResource,
}: ResourceDetailsPanelProps) {
  return (
    <Sheet open={open} onOpenChange={onClose}>
      <SheetContent side="right" className="w-full sm:max-w-2xl overflow-y-auto">
        <SheetHeader className="mb-6">
          <div className="flex items-center justify-between">
            <SheetTitle className="text-lg font-semibold">{gatewaySlug} Resources</SheetTitle>
            <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close panel">
              <X className="h-4 w-4" />
            </Button>
          </div>
        </SheetHeader>

        <div className="space-y-4">
          {resources.map((resource) => (
            <div
              key={resource.id}
              className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900"
            >
              <div className="mb-3 flex items-start justify-between">
                <div className="flex items-center gap-2">
                  <FileText className="h-4 w-4 text-neutral-500" />
                  <h3 className="font-semibold text-neutral-900 dark:text-white">
                    {resource.name}
                  </h3>
                  <span
                    className={`h-2 w-2 rounded-full ${
                      resource.enabled ? "bg-green-500" : "bg-neutral-400"
                    }`}
                  />
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onDeleteResource(resource.id)}
                  aria-label={`Delete ${resource.name}`}
                  className="text-red-600 hover:text-red-700 dark:text-red-400"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>

              <div className="space-y-2 text-sm">
                <div>
                  <span className="font-medium text-neutral-700 dark:text-neutral-300">URI:</span>
                  <code className="ml-2 rounded bg-neutral-100 px-1.5 py-0.5 text-xs dark:bg-neutral-800">
                    {resource.uri}
                  </code>
                </div>

                {resource.description && (
                  <div>
                    <span className="font-medium text-neutral-700 dark:text-neutral-300">
                      Description:
                    </span>
                    <p className="mt-1 text-neutral-600 dark:text-neutral-400">
                      {resource.description}
                    </p>
                  </div>
                )}

                {resource.mimeType && (
                  <div>
                    <span className="font-medium text-neutral-700 dark:text-neutral-300">
                      MIME Type:
                    </span>
                    <code className="ml-2 rounded bg-neutral-100 px-1.5 py-0.5 text-xs dark:bg-neutral-800">
                      {resource.mimeType}
                    </code>
                  </div>
                )}

                {resource.size && (
                  <div>
                    <span className="font-medium text-neutral-700 dark:text-neutral-300">
                      Size:
                    </span>
                    <span className="ml-2 text-neutral-600 dark:text-neutral-400">
                      {formatBytes(resource.size)}
                    </span>
                  </div>
                )}

                {resource.tags && resource.tags.length > 0 && (
                  <div>
                    <span className="font-medium text-neutral-700 dark:text-neutral-300">
                      Tags:
                    </span>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {resource.tags.map((tag) => (
                        <Badge key={tag} variant="secondary" className="text-xs">
                          {tag}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 Bytes";
  const k = 1024;
  const sizes = ["Bytes", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
}
