import { useState, useMemo } from "react";
import { z } from "zod";
import { promptsApi, type PromptArgument } from "@/api/prompts";
import { sanitizeString } from "@/lib/sanitize";

type PromptFormVariable = Pick<PromptArgument, "name">;

const VARIABLE_NAME_PATTERN = /^[a-zA-Z_][a-zA-Z0-9_]*$/;
const TEMPLATE_VARIABLE_PATTERN = /\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}/g;

const promptFormSchema = z.object({
  name: z
    .string()
    .transform((val) => sanitizeString(val, 100))
    .pipe(z.string().min(1, "Name is required").max(100, "Name must be less than 100 characters")),
  // TODO: add validation for template string
  template: z.string().min(1, "Template is required"),
});

interface FormErrors {
  name?: string;
  template?: string;
  variable?: string;
  submit?: string;
}

function extractVariablesFromTemplate(template: string): string[] {
  const variables = new Set<string>();
  let match;

  while ((match = TEMPLATE_VARIABLE_PATTERN.exec(template)) !== null) {
    variables.add(match[1]);
  }

  return Array.from(variables);
}

export function usePromptForm() {
  const [name, setName] = useState("");
  const [template, setTemplate] = useState("");
  const [variables, setVariables] = useState<PromptFormVariable[]>([]);
  const [errors, setErrors] = useState<FormErrors>({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleTemplateChange = (newTemplate: string) => {
    setTemplate(newTemplate);
    const detectedVars = extractVariablesFromTemplate(newTemplate);
    setVariables(detectedVars.map((varName) => ({ name: varName })));
  };

  const deleteVariable = (varName: string) => {
    setVariables((currentVars) => currentVars.filter((v) => v.name !== varName));
  };

  const addVariable = (varName: string) => {
    const trimmedName = varName.trim();
    if (!trimmedName) return false;

    if (!VARIABLE_NAME_PATTERN.test(trimmedName)) {
      setErrors((currentErrors) => ({
        ...currentErrors,
        variable:
          "Variable names must start with a letter or underscore and contain only letters, numbers, and underscores.",
      }));
      return false;
    }

    setVariables((currentVars) => {
      const exists = currentVars.some((v) => v.name === trimmedName);
      if (exists) return currentVars;

      return [...currentVars, { name: trimmedName }];
    });

    setErrors((currentErrors) => {
      const remainingErrors = { ...currentErrors };
      delete remainingErrors.variable;
      return remainingErrors;
    });
    return true;
  };

  const validateField = (field: "name" | "template", value: string): string | undefined => {
    try {
      const fieldSchema = promptFormSchema.shape[field];
      fieldSchema.parse(value);
      return undefined;
    } catch (error) {
      if (error instanceof z.ZodError) {
        return error.errors[0]?.message;
      }
      return "Validation error";
    }
  };

  const validateForm = (): boolean => {
    const newErrors: FormErrors = {};

    const nameError = validateField("name", name);
    if (nameError) newErrors.name = nameError;

    const templateError = validateField("template", template);
    if (templateError) newErrors.template = templateError;

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const isValid = useMemo(() => {
    return name.trim().length > 0 && template.trim().length > 0;
  }, [name, template]);

  const handleSubmit = async (
    event: React.FormEvent<HTMLFormElement>,
    onSuccess?: (prompt: any) => void,
  ) => {
    event.preventDefault();

    if (!validateForm()) {
      return;
    }

    setIsSubmitting(true);
    setErrors({});

    try {
      const result = await promptsApi.create({
        name: sanitizeString(name, 100),
        template: template.trim(),
        arguments: variables,
      });

      if (onSuccess) {
        onSuccess(result);
      }
    } catch (error: any) {
      console.error("Failed to create prompt:", error);

      let errorMessage = "Failed to create prompt. Please try again.";

      if (error?.status === 409) {
        errorMessage = "A prompt with this name already exists.";
      } else if (error?.status === 400) {
        errorMessage = error?.body?.message || "Invalid prompt data.";
      } else if (error?.status === 403) {
        errorMessage = "You don't have permission to create prompts.";
      }

      setErrors({ submit: errorMessage });
    } finally {
      setIsSubmitting(false);
    }
  };

  return {
    name,
    template,
    variables,
    errors,
    isValid,
    isSubmitting,
    setName,
    setTemplate: handleTemplateChange,
    deleteVariable,
    addVariable,
    handleSubmit,
  };
}
