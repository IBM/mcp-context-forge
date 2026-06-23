import { useState } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

interface ResourceFormProps {
  isOpen: boolean;
  onToggle: () => void;
  onSuccess: () => void;
}

/**
 * Form for creating new resources (placeholder for future CRUD functionality)
 * Currently displays UI only - submission will be implemented in a future PR
 *
 * @param isOpen - Whether the form is visible
 * @param onToggle - Callback to toggle form visibility
 * @param onSuccess - Callback after successful resource creation (future)
 */
export function ResourceForm({ isOpen, onToggle }: ResourceFormProps) {
  const [formData, setFormData] = useState({
    uri: "",
    name: "",
    description: "",
    mimeType: "",
    content: "",
    tags: "",
  });

  /**
   * @future Implement resource creation in follow-up PR
   * This form is currently display-only for UI/UX validation
   */
  const handleSubmit = () => {};

  if (!isOpen) return null;

  return (
    <div className="rounded-lg border border-neutral-200 bg-white p-6 dark:border-neutral-800 dark:bg-neutral-900">
      <div className="mb-6 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-neutral-900 dark:text-white">Add Resource</h2>
        <Button type="button" variant="ghost" size="sm" onClick={onToggle} aria-label="Close form">
          <X className="h-4 w-4" />
        </Button>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <Label htmlFor="uri">URI *</Label>
          <Input
            id="uri"
            type="text"
            required
            value={formData.uri}
            onChange={(e) => setFormData({ ...formData, uri: e.target.value })}
            placeholder="resource://example/path"
            aria-describedby="uri-help"
          />
          <p id="uri-help" className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
            Format: resource://gateway/path
          </p>
        </div>

        <div>
          <Label htmlFor="name">Name *</Label>
          <Input
            id="name"
            type="text"
            required
            value={formData.name}
            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
            placeholder="My Resource"
            aria-describedby="name-help"
          />
          <p id="name-help" className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
            Human-readable name for the resource
          </p>
        </div>

        <div>
          <Label htmlFor="description">Description</Label>
          <Textarea
            id="description"
            value={formData.description}
            onChange={(e) => setFormData({ ...formData, description: e.target.value })}
            placeholder="Resource description"
            rows={3}
            aria-describedby="description-help"
          />
          <p id="description-help" className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
            Optional detailed description of the resource
          </p>
        </div>

        <div>
          <Label htmlFor="mimeType">MIME Type</Label>
          <Input
            id="mimeType"
            type="text"
            value={formData.mimeType}
            onChange={(e) => setFormData({ ...formData, mimeType: e.target.value })}
            placeholder="text/plain"
            aria-describedby="mimeType-help"
          />
          <p id="mimeType-help" className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
            Content type (e.g., text/plain, application/json)
          </p>
        </div>

        <div>
          <Label htmlFor="content">Content *</Label>
          <Textarea
            id="content"
            required
            value={formData.content}
            onChange={(e) => setFormData({ ...formData, content: e.target.value })}
            placeholder="Resource content"
            rows={6}
            aria-describedby="content-help"
          />
          <p id="content-help" className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
            The actual content of the resource
          </p>
        </div>

        <div>
          <Label htmlFor="tags">Tags (comma-separated)</Label>
          <Input
            id="tags"
            type="text"
            value={formData.tags}
            onChange={(e) => setFormData({ ...formData, tags: e.target.value })}
            placeholder="tag1, tag2, tag3"
            aria-describedby="tags-help"
          />
          <p id="tags-help" className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
            Optional tags for categorization (comma-separated)
          </p>
        </div>

        <div className="flex gap-2">
          <Button type="submit" disabled={false}>
            {false ? "Creating..." : "Create Resource"}
          </Button>
          <Button type="button" variant="outline" onClick={onToggle}>
            Cancel
          </Button>
        </div>
      </form>
    </div>
  );
}
