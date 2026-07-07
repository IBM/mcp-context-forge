import { useState } from "react";
import { useIntl } from "react-intl";
import { CircleAlert, MessageSquareCode } from "lucide-react";
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
import { promptsApi } from "@/api/prompts";
import { ApiError } from "@/api/client";
import { useAuthContext } from "@/auth/AuthContext";
import { validateTemplateContent } from "@/lib/validateTemplate";
import type { PromptFormData, PromptFormErrors } from "@/types/prompts";

function getPromptCreateError(error: unknown, fallbackMessage: string): string {
  if (error instanceof ApiError) {
    const body = error.body as { message?: string; detail?: unknown } | null;
    if (body?.message) return body.message;
    if (typeof body?.detail === "string") return body.detail;
    if (Array.isArray(body?.detail) && body.detail.length > 0) {
      return body.detail
        .map((item) => {
          if (item && typeof item === "object" && "msg" in item) {
            return String((item as { msg?: unknown }).msg);
          }
          return String(item);
        })
        .join("; ");
    }
  }

  if (error instanceof Error) return error.message;
  return fallbackMessage;
}

interface PromptFormProps {
  isOpen: boolean;
  onToggle: () => void;
  onSuccess: () => void;
}

export function PromptForm({ isOpen, onToggle, onSuccess }: PromptFormProps) {
  const intl = useIntl();
  const { selectedTeamId } = useAuthContext();

  const [formData, setFormData] = useState<PromptFormData>({
    name: "",
    visibility: "public",
    template: "",
    arguments: "",
    description: "",
    tags: "",
  });

  const [errors, setErrors] = useState<PromptFormErrors>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const validateField = (field: keyof PromptFormData, value: string): string | undefined => {
    if (field === "name" && !value.trim()) {
      return intl.formatMessage({ id: "prompts.add.error.nameRequired" });
    }

    if (field === "template") {
      if (!value.trim()) return intl.formatMessage({ id: "prompts.add.error.templateRequired" });
      const templateError = validateTemplateContent(value);
      if (templateError) return intl.formatMessage({ id: `prompts.add.error.${templateError}` });
    }

    if (field === "arguments" && value.trim()) {
      try {
        const parsedArguments = JSON.parse(value);
        if (!Array.isArray(parsedArguments)) {
          return intl.formatMessage({ id: "prompts.add.error.argumentsArrayRequired" });
        }
      } catch {
        return intl.formatMessage({ id: "prompts.add.error.argumentsInvalidJson" });
      }
    }

    return undefined;
  };

  const setFieldError = (field: keyof PromptFormData, error: string | undefined) => {
    setErrors((current) => {
      const nextErrors = { ...current };
      if (error) {
        nextErrors[field] = error;
      } else {
        delete nextErrors[field];
      }
      return nextErrors;
    });
  };

  const handleInputChange = (field: keyof PromptFormData, value: string) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
    setSubmitError(null);
    if (errors[field]) {
      setFieldError(field, validateField(field, value));
    }
  };

  const validateForm = (): boolean => {
    const newErrors: PromptFormErrors = {};
    const fields: Array<keyof PromptFormData> = ["name", "template", "arguments"];

    for (const field of fields) {
      const fieldError = validateField(field, formData[field] ?? "");
      if (fieldError) newErrors[field] = fieldError;
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validateForm()) return;

    setIsSubmitting(true);
    setSubmitError(null);
    try {
      await promptsApi.create({
        ...formData,
        teamId: selectedTeamId ?? undefined,
      });
      onSuccess();
    } catch (error) {
      if (error instanceof ApiError) {
        const body = error.body as { message?: string; field?: string } | null;
        if (body?.field && body?.message) {
          setErrors({ [body.field as keyof PromptFormData]: body.message });
          return;
        } else {
          setSubmitError(
            getPromptCreateError(error, intl.formatMessage({ id: "prompts.add.error" })),
          );
        }
      } else {
        setSubmitError(
          getPromptCreateError(error, intl.formatMessage({ id: "prompts.add.error" })),
        );
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="mx-auto mt-6 w-full max-w-3xl rounded-xl border border-neutral-200 bg-inherit p-0 shadow-[0_12px_40px_rgba(15,23,42,0.12)] dark:border-neutral-800">
      <div className="flex flex-col gap-6 p-6 sm:p-8">
        <div className="flex items-center gap-3">
          <div className="flex h-6 w-6 items-center justify-center rounded bg-green-400">
            <MessageSquareCode className="h-4 w-4 text-black" />
          </div>
          <h2 className="text-base font-semibold text-foreground">
            {intl.formatMessage({ id: "prompts.add.pageTitle" })}
          </h2>
        </div>

        <p className="text-sm text-muted-foreground">
          {intl.formatMessage({ id: "prompts.add.subtitle" })}
        </p>

        <form onSubmit={handleSubmit} className="space-y-6">
          {submitError && (
            <div
              className="flex gap-3 rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive"
              role="alert"
              aria-live="assertive"
            >
              <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              <p>{submitError}</p>
            </div>
          )}

          <div className="space-y-2.5">
            <Label htmlFor="name" className="text-sm font-medium text-foreground">
              {intl.formatMessage({ id: "prompts.add.field.name" })}{" "}
              <span className="text-destructive">
                {intl.formatMessage({ id: "prompts.add.required" })}
              </span>
            </Label>
            <Input
              id="name"
              value={formData.name}
              onChange={(e) => handleInputChange("name", e.target.value)}
              onBlur={(e) => setFieldError("name", validateField("name", e.target.value))}
              placeholder="Name"
              aria-invalid={!!errors.name}
              aria-describedby={errors.name ? "prompt-name-error" : undefined}
              className="h-10"
            />
            {errors.name && (
              <p id="prompt-name-error" className="text-sm text-destructive">
                {errors.name}
              </p>
            )}
          </div>

          <div className="space-y-2.5">
            <Label htmlFor="visibility" className="text-sm font-medium text-foreground">
              {intl.formatMessage({ id: "prompts.add.field.visibility" })}{" "}
              <span className="text-destructive">
                {intl.formatMessage({ id: "prompts.add.required" })}
              </span>
            </Label>
            <Select
              value={formData.visibility}
              onValueChange={(value) => handleInputChange("visibility", value)}
            >
              <SelectTrigger id="visibility" className="h-10 w-full">
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
          </div>

          <div className="space-y-2.5">
            <Label htmlFor="template" className="text-sm font-medium text-foreground">
              {intl.formatMessage({ id: "prompts.add.field.template" })}{" "}
              <span className="text-destructive">
                {intl.formatMessage({ id: "prompts.add.required" })}
              </span>
            </Label>
            <Textarea
              id="template"
              value={formData.template}
              onChange={(e) => handleInputChange("template", e.target.value)}
              onBlur={(e) => setFieldError("template", validateField("template", e.target.value))}
              placeholder={intl.formatMessage({ id: "prompts.add.placeholder.template" })}
              aria-invalid={!!errors.template}
              aria-describedby={errors.template ? "prompt-template-error" : undefined}
              className="min-h-[96px] resize-y"
            />
            {errors.template && (
              <p id="prompt-template-error" className="text-sm text-destructive">
                {errors.template}
              </p>
            )}
          </div>

          <div className="space-y-2.5">
            <Label htmlFor="arguments" className="text-sm font-medium text-foreground">
              {intl.formatMessage({ id: "prompts.add.field.arguments" })}
            </Label>
            <Textarea
              id="arguments"
              value={formData.arguments}
              onChange={(e) => handleInputChange("arguments", e.target.value)}
              onBlur={(e) =>
                setFieldError("arguments", validateField("arguments", e.target.value))
              }
              placeholder={intl.formatMessage({ id: "prompts.add.placeholder.arguments" })}
              aria-invalid={!!errors.arguments}
              aria-describedby={errors.arguments ? "prompt-arguments-error" : undefined}
              className="min-h-[116px] resize-y font-mono text-sm"
            />
            {errors.arguments && (
              <p id="prompt-arguments-error" className="text-sm text-destructive">
                {errors.arguments}
              </p>
            )}
          </div>

          <div className="space-y-2.5">
            <Textarea
              id="description"
              value={formData.description}
              onChange={(e) => handleInputChange("description", e.target.value)}
              placeholder={intl.formatMessage({ id: "prompts.add.placeholder.description" })}
              className="min-h-[60px] resize-y"
            />
          </div>

          <div className="space-y-2.5">
            <Label htmlFor="tags" className="text-sm font-medium text-foreground">
              {intl.formatMessage({ id: "prompts.add.field.tags" })}
            </Label>
            <Input
              id="tags"
              value={formData.tags}
              onChange={(e) => handleInputChange("tags", e.target.value)}
              placeholder={intl.formatMessage({ id: "prompts.add.placeholder.tags" })}
              className="h-10"
            />
          </div>

          <div className="flex items-center justify-end gap-3">
            <Button
              type="button"
              variant="ghost"
              onClick={onToggle}
              className="h-7 px-2"
              disabled={isSubmitting}
            >
              {intl.formatMessage({ id: "common.button.cancel" })}
            </Button>
            <Button type="submit" variant="default" className="h-7 px-2" disabled={isSubmitting}>
              {isSubmitting
                ? intl.formatMessage({ id: "common.button.submitting" })
                : intl.formatMessage({ id: "prompts.add.button.submit" })}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
