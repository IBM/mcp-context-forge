import { useEffect, useRef } from "react";
import { useIntl } from "react-intl";
import { Box } from "lucide-react";
import { BackButton } from "@/components/ui/back-button";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { TagInput } from "@/components/ui/tag-input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  useResourceForm,
  MIME_TYPES,
  type MimeType,
  type ResourceFormOptions,
  type ResourceFormInitialValues,
} from "@/hooks/useResourceForm";
import { useTagSuggestions } from "@/hooks/useTagSuggestions";
import type { Visibility } from "@/types/server";
import type { ResourceRead } from "@/generated/types";

interface ResourceFormProps extends Omit<ResourceFormOptions, "resourceId" | "initialValues"> {
  isOpen: boolean;
  onToggle: () => void;
  onSuccess: (name: string) => void;
  resource?: NonNullable<ResourceRead>;
}

function resourceToInitialValues(
  resource?: NonNullable<ResourceRead>,
): ResourceFormInitialValues | undefined {
  if (!resource) return undefined;
  return {
    uri: resource.uriTemplate || resource.uri,
    name: resource.name,
    content: (resource as { content?: string }).content ?? "",
    description: resource.description ?? "",
    mimeType: (resource.mimeType as MimeType | null) ?? "",
    tags: resource.tags ?? [],
    visibility: (resource.visibility as Visibility) ?? "public",
  };
}

export function ResourceForm({
  isOpen,
  onToggle,
  onSuccess,
  onBeforeSubmit,
  onError,
  resource,
}: ResourceFormProps) {
  const intl = useIntl();
  const tagSuggestions = useTagSuggestions();
  const isEditMode = Boolean(resource);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const {
    uri,
    name,
    content,
    description,
    mimeType,
    tags,
    visibility,
    errors,
    isSubmitting,
    setUri,
    setName,
    setContent,
    setDescription,
    setMimeType,
    setTags,
    setVisibility,
    handleSubmit,
  } = useResourceForm({
    onBeforeSubmit,
    onError,
    resourceId: resource?.id,
    initialValues: resourceToInitialValues(resource),
  });

  useEffect(() => {
    if (isOpen) headingRef.current?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const hasCustomMimeType = mimeType !== "" && !MIME_TYPES.includes(mimeType as MimeType);

  if (!isOpen) return null;

  return (
    <div className="mx-auto w-full max-w-3xl">
      <BackButton onClick={onToggle} />

      <div className="rounded-xl border border-neutral-200 bg-inherit p-0 shadow-[0_12px_40px_rgba(15,23,42,0.12)] dark:border-neutral-800">
        <div className="flex flex-col gap-8 p-6 sm:p-8">
          <div className="flex flex-col gap-4">
            <div className="flex items-center gap-2">
              <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-sm bg-[#ff5aff] shadow-sm">
                <Box className="h-4 w-4 text-black" />
              </div>
              <h2
                ref={headingRef}
                tabIndex={-1}
                className="text-lg font-semibold tracking-tight text-neutral-950 dark:text-neutral-50"
              >
                {isEditMode
                  ? intl.formatMessage({ id: "resources.form.heading.edit" })
                  : intl.formatMessage({ id: "resources.form.title" })}
              </h2>
            </div>
            <p className="text-sm leading-6 text-neutral-600 dark:text-neutral-400">
              {intl.formatMessage({ id: "resources.form.subtitle" })}
            </p>
          </div>

          <form onSubmit={(e) => handleSubmit(e, onSuccess)} className="space-y-6">
            {/* Name */}
            <div className="space-y-1">
              <label
                htmlFor="resource-name"
                className="inline-flex items-center gap-0.5 text-sm font-medium text-neutral-900 dark:text-neutral-100"
              >
                {intl.formatMessage({ id: "resources.form.name.label" })}
                <span className="text-red-500">*</span>
              </label>
              <Input
                id="resource-name"
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={intl.formatMessage({ id: "resources.form.name.placeholder" })}
                className="rounded-md border-neutral-300 px-4 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:text-neutral-100 dark:placeholder:text-neutral-500"
                aria-invalid={!!errors.name}
                aria-describedby={errors.name ? "name-error" : undefined}
              />
              {errors.name && (
                <p id="name-error" role="alert" className="text-sm text-red-500">
                  {errors.name}
                </p>
              )}
            </div>

            {/* URI */}
            <div className="space-y-1">
              <label
                htmlFor="resource-uri"
                className="inline-flex items-center gap-0.5 text-sm font-medium text-neutral-900 dark:text-neutral-100"
              >
                {intl.formatMessage({ id: "resources.form.uri.label" })}
                <span className="text-red-500">*</span>
              </label>
              <Input
                id="resource-uri"
                type="text"
                value={uri}
                onChange={(e) => setUri(e.target.value)}
                placeholder="resource://example/path"
                className="rounded-md border-neutral-300 px-4 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:text-neutral-100 dark:placeholder:text-neutral-500"
                aria-invalid={!!errors.uri}
                aria-describedby={errors.uri ? "uri-error" : undefined}
              />
              {errors.uri && (
                <p id="uri-error" role="alert" className="text-sm text-red-500">
                  {errors.uri}
                </p>
              )}
            </div>

            {/* Description — no label, placeholder only */}
            <div className="space-y-1">
              <Textarea
                id="resource-description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder={intl.formatMessage({ id: "resources.form.description.placeholder" })}
                rows={3}
                className="rounded-md border-neutral-300 px-4 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:text-neutral-100 dark:placeholder:text-neutral-500"
                aria-invalid={!!errors.description}
                aria-describedby={errors.description ? "description-error" : undefined}
              />
              {errors.description && (
                <p id="description-error" role="alert" className="text-sm text-red-500">
                  {errors.description}
                </p>
              )}
            </div>

            {/* MIME Type — optional select */}
            <div className="space-y-1">
              <label
                htmlFor="resource-mime-type"
                className="text-sm font-medium text-neutral-900 dark:text-neutral-100"
              >
                {intl.formatMessage({ id: "resources.form.mimeType.label" })}
              </label>
              <Select value={mimeType} onValueChange={(v) => setMimeType(v as MimeType | "")}>
                <SelectTrigger
                  id="resource-mime-type"
                  className="w-full rounded-md border-neutral-300 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 dark:border-neutral-700 dark:text-neutral-100"
                >
                  <SelectValue
                    placeholder={intl.formatMessage({ id: "resources.form.mimeType.placeholder" })}
                  />
                </SelectTrigger>
                <SelectContent>
                  {hasCustomMimeType && <SelectItem value={mimeType}>{mimeType}</SelectItem>}
                  {MIME_TYPES.map((type) => (
                    <SelectItem key={type} value={type}>
                      {type}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {errors.mimeType && (
                <p id="mime-type-error" role="alert" className="text-sm text-red-500">
                  {errors.mimeType}
                </p>
              )}
            </div>

            {/* Content — code editor */}
            <div className="space-y-1">
              <label
                htmlFor="resource-content"
                className="inline-flex items-center gap-0.5 text-sm font-medium text-neutral-900 dark:text-neutral-100"
              >
                {intl.formatMessage({ id: "resources.form.content.label" })}
                <span className="text-red-500">*</span>
              </label>
              <Textarea
                id="resource-content"
                value={content}
                onChange={(e) => setContent(e.target.value)}
                placeholder={intl.formatMessage({ id: "resources.form.content.placeholder" })}
                className="min-h-40 font-mono text-xs focus-visible:ring-1 focus-visible:ring-offset-0"
                spellCheck={false}
                aria-invalid={!!errors.content}
                aria-describedby={errors.content ? "content-error" : undefined}
              />
              {errors.content && (
                <p id="content-error" role="alert" className="text-sm text-red-500">
                  {errors.content}
                </p>
              )}
            </div>

            {/* Visibility — required select */}
            <div className="space-y-1">
              <label
                htmlFor="resource-visibility"
                className="inline-flex items-center gap-0.5 text-sm font-medium text-neutral-900 dark:text-neutral-100"
              >
                {intl.formatMessage({ id: "resources.form.visibility.label" })}
                <span className="text-red-500">*</span>
              </label>
              <Select value={visibility} onValueChange={(v) => setVisibility(v as Visibility)}>
                <SelectTrigger
                  id="resource-visibility"
                  className="w-full rounded-md border-neutral-300 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 dark:border-neutral-700 dark:text-neutral-100"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="public">
                    {intl.formatMessage({ id: "resources.form.visibility.public" })}
                  </SelectItem>
                  <SelectItem value="private">
                    {intl.formatMessage({ id: "resources.form.visibility.private" })}
                  </SelectItem>
                  <SelectItem value="team">
                    {intl.formatMessage({ id: "resources.form.visibility.team" })}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Tags */}
            <div className="space-y-1">
              <label
                htmlFor="resource-tags"
                className="text-sm font-medium text-neutral-900 dark:text-neutral-100"
              >
                {intl.formatMessage({ id: "resources.form.tags.label" })}
              </label>
              <TagInput
                id="resource-tags"
                value={tags}
                onChange={setTags}
                suggestions={tagSuggestions}
                placeholder="tag1, tag2, tag3"
              />
            </div>

            {errors.submit && (
              <div
                role="alert"
                aria-live="assertive"
                className="rounded-md border border-red-200 bg-red-50 p-3 dark:border-red-900/50 dark:bg-red-950/50"
              >
                <p className="text-sm text-red-600 dark:text-red-400">{errors.submit}</p>
              </div>
            )}

            <div className="flex items-center justify-end gap-3 pt-6">
              <Button
                type="button"
                variant="ghost"
                onClick={onToggle}
                className="h-10 rounded-md px-3 text-sm font-medium text-neutral-700 hover:bg-neutral-100 hover:text-neutral-950 dark:text-neutral-300 dark:hover:bg-neutral-800 dark:hover:text-neutral-100"
              >
                {intl.formatMessage({ id: "resources.form.cancel" })}
              </Button>
              <Button
                type="submit"
                disabled={isSubmitting}
                className="h-10 rounded-md bg-neutral-950 px-4 text-sm font-medium text-white hover:enabled:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-950 dark:hover:enabled:bg-neutral-200"
              >
                {isSubmitting
                  ? isEditMode
                    ? intl.formatMessage({ id: "resources.form.button.updating" })
                    : intl.formatMessage({ id: "resources.form.submitting" })
                  : isEditMode
                    ? intl.formatMessage({ id: "resources.form.button.update" })
                    : intl.formatMessage({ id: "resources.form.submit" })}
              </Button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
