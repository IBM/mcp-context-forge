import { X } from "lucide-react";
import { useIntl } from "react-intl";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useResourceForm } from "@/hooks/useResourceForm";

interface ResourceFormProps {
  isOpen: boolean;
  onToggle: () => void;
  onSuccess: () => void;
}

export function ResourceForm({ isOpen, onToggle, onSuccess }: ResourceFormProps) {
  const intl = useIntl();
  const {
    uri,
    name,
    content,
    description,
    mimeType,
    tags,
    errors,
    isSubmitting,
    setUri,
    setName,
    setContent,
    setDescription,
    setMimeType,
    setTags,
    handleSubmit,
  } = useResourceForm();

  if (!isOpen) return null;

  return (
    <div className="rounded-lg border border-neutral-200 bg-white p-6 dark:border-neutral-800 dark:bg-neutral-900">
      <div className="mb-6 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-neutral-900 dark:text-white">
          {intl.formatMessage({ id: "resources.form.title" })}
        </h2>
        <Button type="button" variant="ghost" size="sm" onClick={onToggle} aria-label="Close form">
          <X className="h-4 w-4" />
        </Button>
      </div>

      <form onSubmit={(e) => handleSubmit(e, onSuccess)} className="space-y-4">
        <div>
          <Label htmlFor="uri">{intl.formatMessage({ id: "resources.form.uri.label" })} *</Label>
          <Input
            id="uri"
            type="text"
            value={uri}
            onChange={(e) => setUri(e.target.value)}
            placeholder="resource://example/path"
            aria-describedby={errors.uri ? "uri-error" : "uri-help"}
            aria-invalid={!!errors.uri}
          />
          {errors.uri ? (
            <p id="uri-error" role="alert" className="mt-1 text-xs text-red-600 dark:text-red-400">
              {errors.uri}
            </p>
          ) : (
            <p id="uri-help" className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
              {intl.formatMessage({ id: "resources.form.uri.help" })}
            </p>
          )}
        </div>

        <div>
          <Label htmlFor="name">{intl.formatMessage({ id: "resources.form.name.label" })} *</Label>
          <Input
            id="name"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="My Resource"
            aria-describedby={errors.name ? "name-error" : "name-help"}
            aria-invalid={!!errors.name}
          />
          {errors.name ? (
            <p id="name-error" role="alert" className="mt-1 text-xs text-red-600 dark:text-red-400">
              {errors.name}
            </p>
          ) : (
            <p id="name-help" className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
              {intl.formatMessage({ id: "resources.form.name.help" })}
            </p>
          )}
        </div>

        <div>
          <Label htmlFor="description">
            {intl.formatMessage({ id: "resources.form.description.label" })}
          </Label>
          <Textarea
            id="description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Resource description"
            rows={3}
            aria-describedby={errors.description ? "description-error" : "description-help"}
            aria-invalid={!!errors.description}
          />
          {errors.description ? (
            <p
              id="description-error"
              role="alert"
              className="mt-1 text-xs text-red-600 dark:text-red-400"
            >
              {errors.description}
            </p>
          ) : (
            <p
              id="description-help"
              className="mt-1 text-xs text-neutral-500 dark:text-neutral-400"
            >
              {intl.formatMessage({ id: "resources.form.description.help" })}
            </p>
          )}
        </div>

        <div>
          <Label htmlFor="mimeType">
            {intl.formatMessage({ id: "resources.form.mimeType.label" })}
          </Label>
          <Input
            id="mimeType"
            type="text"
            value={mimeType}
            onChange={(e) => setMimeType(e.target.value)}
            placeholder="text/plain"
            aria-describedby="mimeType-help"
          />
          <p id="mimeType-help" className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
            {intl.formatMessage({ id: "resources.form.mimeType.help" })}
          </p>
        </div>

        <div>
          <Label htmlFor="content">
            {intl.formatMessage({ id: "resources.form.content.label" })} *
          </Label>
          <Textarea
            id="content"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="Resource content"
            rows={6}
            aria-describedby={errors.content ? "content-error" : "content-help"}
            aria-invalid={!!errors.content}
          />
          {errors.content ? (
            <p
              id="content-error"
              role="alert"
              className="mt-1 text-xs text-red-600 dark:text-red-400"
            >
              {errors.content}
            </p>
          ) : (
            <p id="content-help" className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
              {intl.formatMessage({ id: "resources.form.content.help" })}
            </p>
          )}
        </div>

        <div>
          <Label htmlFor="tags">{intl.formatMessage({ id: "resources.form.tags.label" })}</Label>
          <Input
            id="tags"
            type="text"
            value={tags}
            onChange={(e) => setTags(e.target.value)}
            placeholder="tag1, tag2, tag3"
            aria-describedby="tags-help"
          />
          <p id="tags-help" className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
            {intl.formatMessage({ id: "resources.form.tags.help" })}
          </p>
        </div>

        {errors.submit && (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">
            {errors.submit}
          </p>
        )}

        <div className="flex gap-2">
          <Button type="submit" disabled={isSubmitting}>
            {isSubmitting
              ? intl.formatMessage({ id: "resources.form.submitting" })
              : intl.formatMessage({ id: "resources.form.submit" })}
          </Button>
          <Button type="button" variant="outline" onClick={onToggle}>
            {intl.formatMessage({ id: "resources.form.cancel" })}
          </Button>
        </div>
      </form>
    </div>
  );
}
