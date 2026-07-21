import { useEffect, useRef } from "react";
import { useIntl } from "react-intl";
import { CircleAlert, Info, MessageSquareCode } from "lucide-react";
import { BackButton } from "@/components/ui/back-button";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { usePromptForm, type PromptFormInitialValues } from "@/hooks/usePromptForm";
import { getTagDisplay } from "@/components/gateways/utils";
import type { PromptRead } from "@/generated/types";
import type { Visibility } from "@/types/server";

interface PromptFormProps {
  isOpen: boolean;
  onToggle: () => void;
  onSuccess: () => void;
  /** When provided, the form opens in edit mode and updates this prompt. */
  prompt?: NonNullable<PromptRead>;
}

function promptToInitialValues(
  prompt?: NonNullable<PromptRead>,
): PromptFormInitialValues | undefined {
  if (!prompt) return undefined;

  const args = (prompt.arguments ?? []).filter(Boolean);
  const tagLabels = (prompt.tags ?? []).map((tag, index) => getTagDisplay(tag, index).label);

  return {
    name: prompt.name,
    visibility: (prompt.visibility as Visibility) ?? "public",
    template: prompt.template ?? "",
    arguments: args.length > 0 ? JSON.stringify(args, null, 2) : "",
    description: prompt.description ?? "",
    tags: tagLabels.join(", "),
    teamId: prompt.teamId,
  };
}

export function PromptForm({ isOpen, onToggle, onSuccess, prompt }: PromptFormProps) {
  const intl = useIntl();
  const isEditMode = Boolean(prompt);
  // Federated prompts (sourced from a remote MCP gateway) have no local
  // template — the upstream server resolves the content on `prompts/get` — so
  // the template field is optional for them. Local/REST prompts require it.
  const isFederated = Boolean(prompt?.gatewayId || prompt?.gatewaySlug || prompt?.federationSource);
  const templateRequired = !isFederated;
  const form = usePromptForm({
    promptId: prompt?.id,
    initialValues: promptToInitialValues(prompt),
    federated: isFederated,
  });
  const nameInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isOpen) {
      nameInputRef.current?.focus();
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const visibilityHintId = form.visibility === "team" ? "prompt-visibility-team-hint" : undefined;
  const visibilityErrorId = form.errors.visibility ? "prompt-visibility-error" : undefined;
  const visibilityDescribedBy =
    [visibilityHintId, visibilityErrorId].filter(Boolean).join(" ") || undefined;

  return (
    <div className="mx-auto w-full max-w-3xl">
      <BackButton onClick={onToggle} />

      <div className="rounded-xl border border-neutral-200 bg-inherit p-0 shadow-[0_12px_40px_rgba(15,23,42,0.12)] dark:border-neutral-800">
        <div className="flex flex-col gap-6 p-6 sm:p-8">
          <div className="flex items-center gap-3">
            <div className="flex h-6 w-6 items-center justify-center rounded bg-prompt-icon-bg">
              <MessageSquareCode className="h-4 w-4 text-black" />
            </div>
            <h2 className="text-base font-semibold text-foreground">
              {intl.formatMessage({
                id: isEditMode ? "prompts.edit.pageTitle" : "prompts.add.pageTitle",
              })}
            </h2>
          </div>

          <p className="text-sm text-muted-foreground">
            {intl.formatMessage({ id: "prompts.add.subtitle" })}
          </p>

          {isFederated && (
            <div
              role="note"
              className="flex gap-3 rounded-md border border-border bg-muted/50 p-3 text-sm text-muted-foreground"
            >
              <Info className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              <p>{intl.formatMessage({ id: "prompts.edit.federatedNotice" })}</p>
            </div>
          )}

          <form onSubmit={(event) => form.handleSubmit(event, onSuccess)} className="space-y-6">
            {form.errors.submit && (
              <div
                className="flex gap-3 rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive"
                role="alert"
                aria-live="assertive"
              >
                <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
                <p>{form.errors.submit}</p>
              </div>
            )}

            <div className="space-y-2.5">
              <Label htmlFor="name" className="mb-2.5 block text-sm font-medium text-foreground">
                {intl.formatMessage({ id: "prompts.add.field.name" })}{" "}
                <span className="text-destructive" aria-hidden="true">
                  {intl.formatMessage({ id: "prompts.add.required" })}
                </span>
              </Label>
              <Input
                id="name"
                ref={nameInputRef}
                value={form.name}
                onChange={(e) => form.setName(e.target.value)}
                placeholder="Name"
                aria-required="true"
                aria-invalid={!!form.errors.name}
                aria-describedby={form.errors.name ? "prompt-name-error" : undefined}
                className="h-10 rounded-md border-neutral-300 px-4 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:text-neutral-100 dark:placeholder:text-neutral-500"
              />
              {form.errors.name && (
                <p id="prompt-name-error" className="text-sm text-destructive">
                  {form.errors.name}
                </p>
              )}
            </div>

            <div className="space-y-2.5">
              <Label
                htmlFor="visibility"
                className="mb-2.5 block text-sm font-medium text-foreground"
              >
                {intl.formatMessage({ id: "prompts.add.field.visibility" })}{" "}
                <span className="text-destructive" aria-hidden="true">
                  {intl.formatMessage({ id: "prompts.add.required" })}
                </span>
              </Label>
              <Select
                value={form.visibility}
                onValueChange={(value) => form.setVisibility(value as Visibility)}
              >
                <SelectTrigger
                  id="visibility"
                  aria-required="true"
                  aria-invalid={!!form.errors.visibility}
                  aria-describedby={visibilityDescribedBy}
                  className="h-10 w-full rounded-md border-neutral-300 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 dark:border-neutral-700 dark:text-neutral-100"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="public">
                    {intl.formatMessage({ id: "prompts.add.visibility.public" })}
                  </SelectItem>
                  <SelectItem value="team">
                    {intl.formatMessage({ id: "prompts.add.visibility.team" })}
                  </SelectItem>
                  <SelectItem value="private">
                    {intl.formatMessage({ id: "prompts.add.visibility.private" })}
                  </SelectItem>
                </SelectContent>
              </Select>
              {form.visibility === "team" && (
                <p id="prompt-visibility-team-hint" className="text-sm text-muted-foreground">
                  {intl.formatMessage({
                    id: form.teamId
                      ? "prompts.add.visibility.team.selectedHint"
                      : "prompts.add.visibility.team.selectFromSidebarHint",
                  })}
                </p>
              )}
              {form.errors.visibility && (
                <p id="prompt-visibility-error" className="text-sm text-destructive">
                  {form.errors.visibility}
                </p>
              )}
            </div>

            <div className="space-y-2.5">
              <Label
                htmlFor="template"
                className="mb-2.5 block text-sm font-medium text-foreground"
              >
                {intl.formatMessage({ id: "prompts.add.field.template" })}{" "}
                {templateRequired && (
                  <span className="text-destructive" aria-hidden="true">
                    {intl.formatMessage({ id: "prompts.add.required" })}
                  </span>
                )}
              </Label>
              <Textarea
                id="template"
                value={form.template}
                onChange={(e) => form.setTemplate(e.target.value)}
                placeholder={intl.formatMessage({ id: "prompts.add.placeholder.template" })}
                aria-required={templateRequired}
                aria-invalid={!!form.errors.template}
                aria-describedby={form.errors.template ? "prompt-template-error" : undefined}
                disabled={isFederated}
                className="min-h-[96px] resize-y focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0"
              />
              {form.errors.template && (
                <p id="prompt-template-error" className="text-sm text-destructive">
                  {form.errors.template}
                </p>
              )}
            </div>

            <div className="space-y-2.5">
              <Label
                htmlFor="arguments"
                className="mb-2.5 block text-sm font-medium text-foreground"
              >
                {intl.formatMessage({ id: "prompts.add.field.arguments" })}
              </Label>
              <Textarea
                id="arguments"
                value={form.arguments}
                onChange={(e) => form.setArguments(e.target.value)}
                onBlur={(e) => form.validateField("arguments", e.target.value)}
                placeholder={intl.formatMessage({ id: "prompts.add.placeholder.arguments" })}
                aria-invalid={!!form.errors.arguments}
                aria-describedby={form.errors.arguments ? "prompt-arguments-error" : undefined}
                disabled={isFederated}
                className="min-h-[116px] resize-y font-mono text-sm focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0"
              />
              {form.errors.arguments && (
                <p id="prompt-arguments-error" className="text-sm text-destructive">
                  {form.errors.arguments}
                </p>
              )}
            </div>

            <div className="space-y-2.5">
              <Label
                htmlFor="description"
                className="mb-2.5 block text-sm font-medium text-foreground"
              >
                {intl.formatMessage({ id: "prompts.add.field.description" })}
              </Label>
              <Textarea
                id="description"
                value={form.description}
                onChange={(e) => form.setDescription(e.target.value)}
                placeholder={intl.formatMessage({ id: "prompts.add.placeholder.description" })}
                disabled={isFederated}
                className="min-h-[60px] resize-y focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0"
              />
            </div>

            <div className="space-y-2.5">
              <Label htmlFor="tags" className="mb-2.5 block text-sm font-medium text-foreground">
                {intl.formatMessage({ id: "prompts.add.field.tags" })}
              </Label>
              <Input
                id="tags"
                value={form.tags}
                onChange={(e) => form.setTags(e.target.value)}
                placeholder={intl.formatMessage({ id: "prompts.add.placeholder.tags" })}
                className="h-10 rounded-md border-neutral-300 px-4 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:text-neutral-100 dark:placeholder:text-neutral-500"
              />
            </div>

            <div className="flex items-center justify-end gap-3">
              <Button
                type="button"
                variant="ghost"
                onClick={onToggle}
                className="h-7 px-2"
                disabled={form.isSubmitting}
              >
                {intl.formatMessage({ id: "common.button.cancel" })}
              </Button>
              <Button
                type="submit"
                variant="default"
                className="h-7 px-2"
                disabled={form.isSubmitting || !form.isValid}
              >
                {form.isSubmitting
                  ? intl.formatMessage({
                      id: isEditMode ? "common.button.saving" : "common.button.submitting",
                    })
                  : intl.formatMessage({
                      id: isEditMode ? "prompts.edit.button.submit" : "prompts.add.button.submit",
                    })}
              </Button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
