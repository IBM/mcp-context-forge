import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { useIntl } from "react-intl";
import { z } from "zod";
import { useAuthContext } from "@/auth/AuthContext";
import { useQuery } from "@/hooks/useQuery";
import { parseApiError } from "@/lib/errorUtils";
import type { Prompt, PromptArgument, PromptFormErrors } from "@/types/prompts";
import type { Visibility } from "@/types/server";

interface PromptFormValues {
  name: string;
  visibility: Visibility;
  template: string;
  arguments: string;
  description: string;
  tags: string;
  teamId?: string;
}

interface CreatePromptPayload {
  prompt: {
    name: string;
    description?: string;
    template: string;
    arguments: PromptArgument[];
    tags?: string[];
    visibility: Visibility;
    team_id: string | null;
  };
  team_id: string | null;
  visibility: Visibility;
}

export interface UsePromptFormReturn {
  name: string;
  visibility: Visibility;
  teamId?: string;
  template: string;
  arguments: string;
  description: string;
  tags: string;
  errors: PromptFormErrors;
  isValid: boolean;
  isSubmitting: boolean;
  setName: (value: string) => void;
  setVisibility: (value: Visibility) => void;
  setTemplate: (value: string) => void;
  setArguments: (value: string) => void;
  setDescription: (value: string) => void;
  setTags: (value: string) => void;
  validateField: (field: keyof PromptFormErrors, value: string) => void;
  validateForm: () => boolean;
  resetForm: () => void;
  getFormData: () => CreatePromptPayload;
  handleSubmit: (event: FormEvent<HTMLFormElement>, onSuccess?: () => void) => Promise<void>;
}

const initialState: PromptFormValues = {
  name: "",
  visibility: "public",
  template: "",
  arguments: "",
  description: "",
  tags: "",
};

const TEMPLATE_MAX_LENGTH = 65536;
const DANGEROUS_HTML_TAGS_RE = /<(script|iframe|object|embed|link|meta|base|form)\b/i;
const EVENT_HANDLER_RE = /on\w+\s*=/i;
// Best-effort client mirror for instant feedback; the server is the source of truth.
// Keep aligned with mcpgateway/services/content_security.py validate_prompt_template.
const SSTI_SIMPLE_PREFIXES = ["${", "#{", "%{"];
const SSTI_DANGEROUS_SUBSTRINGS = [
  "__",
  "config",
  "self",
  "request",
  "application",
  "globals",
  "builtins",
  "import",
  "getattr",
  "|attr",
  "|selectattr",
  "|sort",
  "|map",
  "attribute=",
  "\\x",
  "\\u",
  "\\0",
  "lipsum",
  "cycler",
  "joiner",
];
const SSTI_DANGEROUS_OPERATORS = ["*", "/", "+", "-", "~", "[", "%"];

function iterTemplateExpressions(value: string, start: string, end: string): string[] {
  const exprs: string[] = [];
  let i = 0;
  while (i < value.length) {
    const startIdx = value.indexOf(start, i);
    if (startIdx === -1) break;
    const endIdx = value.indexOf(end, startIdx + start.length);
    if (endIdx === -1) break;
    exprs.push(value.slice(startIdx + start.length, endIdx));
    i = endIdx + end.length;
  }
  return exprs;
}

function validateTemplateContent(value: string): string | null {
  if (value.length > TEMPLATE_MAX_LENGTH) return "templateTooLong";
  if (DANGEROUS_HTML_TAGS_RE.test(value)) return "templateHtmlTags";
  if (EVENT_HANDLER_RE.test(value)) return "templateEventHandlers";
  if (SSTI_SIMPLE_PREFIXES.some((prefix) => value.includes(prefix))) {
    return "templateDangerousExpression";
  }

  for (const expr of [
    ...iterTemplateExpressions(value, "{{", "}}"),
    ...iterTemplateExpressions(value, "{%", "%}"),
  ]) {
    const lower = expr
      .toLowerCase()
      .replace(/\s*\|\s*/g, "|")
      .replace(/\s*=\s*/g, "=");
    if (SSTI_DANGEROUS_SUBSTRINGS.some((substring) => lower.includes(substring))) {
      return "templateDangerousExpression";
    }
    if (lower.includes(".")) return "templateDangerousExpression";
    if (SSTI_DANGEROUS_OPERATORS.some((operator) => expr.includes(operator))) {
      return "templateDangerousExpression";
    }
  }
  return null;
}

function parseTags(value?: string): string[] | undefined {
  const tags = value
    ?.split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);

  return tags && tags.length > 0 ? tags : undefined;
}

const createPromptFormSchema = (intl: ReturnType<typeof useIntl>) =>
  z
    .object({
      name: z.string().min(1, intl.formatMessage({ id: "prompts.add.error.nameRequired" })),
      visibility: z.enum(["public", "private", "team"]),
      template: z
        .string()
        .min(1, intl.formatMessage({ id: "prompts.add.error.templateRequired" }))
        .superRefine((value, ctx) => {
          const templateError = validateTemplateContent(value);
          if (templateError) {
            ctx.addIssue({
              code: z.ZodIssueCode.custom,
              message: intl.formatMessage({ id: `prompts.add.error.${templateError}` }),
            });
          }
        }),
      arguments: z.string().transform((value, ctx): PromptArgument[] => {
        if (!value.trim()) return [];

        try {
          const parsedArguments = JSON.parse(value) as unknown;
          if (!Array.isArray(parsedArguments)) {
            ctx.addIssue({
              code: z.ZodIssueCode.custom,
              message: intl.formatMessage({ id: "prompts.add.error.argumentsArrayRequired" }),
            });
            return z.NEVER;
          }
          return parsedArguments as PromptArgument[];
        } catch {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            message: intl.formatMessage({ id: "prompts.add.error.argumentsInvalidJson" }),
          });
          return z.NEVER;
        }
      }),
      description: z.string().optional(),
      tags: z.string().optional().transform(parseTags),
      teamId: z.string().optional(),
    })
    .superRefine((data, ctx) => {
      if (data.visibility === "team" && !data.teamId) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: intl.formatMessage({ id: "prompts.add.error.teamRequired" }),
          path: ["visibility"],
        });
      }
    })
    .transform((data): CreatePromptPayload => {
      const teamId = data.visibility === "team" && data.teamId ? data.teamId : null;

      return {
        prompt: {
          name: data.name,
          description: data.description || undefined,
          template: data.template,
          arguments: data.arguments,
          tags: data.tags,
          visibility: data.visibility,
          team_id: teamId,
        },
        team_id: teamId,
        visibility: data.visibility,
      };
    });

function toFieldErrors(error: z.ZodError): PromptFormErrors {
  const nextErrors: PromptFormErrors = {};
  error.issues.forEach((issue) => {
    const path = issue.path[0] as keyof PromptFormErrors;
    nextErrors[path] = issue.message;
  });
  return nextErrors;
}

function getApiFieldError(error: unknown): PromptFormErrors | null {
  if (!error || typeof error !== "object" || !("body" in error)) return null;

  const body = (error as { body?: { field?: string; message?: string } | null }).body;
  if (!body?.field || !body.message) return null;

  const field = body.field === "team_id" ? "visibility" : body.field;
  if (
    field === "name" ||
    field === "visibility" ||
    field === "template" ||
    field === "arguments" ||
    field === "description" ||
    field === "tags"
  ) {
    return { [field]: body.message };
  }

  return null;
}

export function usePromptForm(): UsePromptFormReturn {
  const intl = useIntl();
  const { selectedTeamId } = useAuthContext();
  const schema = useMemo(() => createPromptFormSchema(intl), [intl]);

  const [name, setNameState] = useState(initialState.name);
  const [visibility, setVisibilityState] = useState<Visibility>(initialState.visibility);
  const [template, setTemplateState] = useState(initialState.template);
  const [argumentsValue, setArgumentsState] = useState(initialState.arguments);
  const [description, setDescriptionState] = useState(initialState.description);
  const [tags, setTagsState] = useState(initialState.tags);
  const [errors, setErrors] = useState<PromptFormErrors>({});
  const teamId = visibility === "team" ? (selectedTeamId ?? undefined) : undefined;
  const { execute: createPrompt, isLoading: isSubmitting } = useQuery<Prompt, CreatePromptPayload>(
    "/prompts",
    {
      method: "POST",
      enabled: false,
    },
  );

  const getFormValues = useCallback(
    (): PromptFormValues => ({
      name,
      visibility,
      template,
      arguments: argumentsValue,
      description,
      tags,
      teamId,
    }),
    [name, visibility, template, argumentsValue, description, tags, teamId],
  );

  const validateField = useCallback(
    (field: keyof PromptFormErrors, value: string) => {
      if (field === "submit") return;

      const nextValues = {
        ...getFormValues(),
        [field]: value,
      };

      if (field === "visibility") {
        nextValues.teamId = value === "team" ? (selectedTeamId ?? undefined) : undefined;
      }

      const result = schema.safeParse({
        ...nextValues,
      });

      if (result.success) {
        setErrors((current) => {
          const nextErrors = { ...current };
          delete nextErrors[field];
          return nextErrors;
        });
        return;
      }

      const fieldIssue = result.error.issues.find((issue) => issue.path[0] === field);
      setErrors((current) => {
        const nextErrors = { ...current };
        if (fieldIssue) {
          nextErrors[field] = fieldIssue.message;
        } else {
          delete nextErrors[field];
        }
        return nextErrors;
      });
    },
    [getFormValues, schema, selectedTeamId],
  );

  const updateField = useCallback(
    (
      field: keyof PromptFormErrors,
      value: string,
      setter: (nextValue: string) => void,
      validateImmediately = false,
    ) => {
      setter(value);
      setErrors((current) => {
        if (!current.submit) return current;
        const nextErrors = { ...current };
        delete nextErrors.submit;
        return nextErrors;
      });

      if (validateImmediately || errors[field]) {
        validateField(field, value);
      }
    },
    [errors, validateField],
  );

  const setName = useCallback(
    (value: string) => updateField("name", value, setNameState),
    [updateField],
  );
  const setVisibility = useCallback(
    (value: Visibility) => {
      setVisibilityState(value);
      setErrors((current) => {
        if (!current.submit) return current;
        const nextErrors = { ...current };
        delete nextErrors.submit;
        return nextErrors;
      });
      validateField("visibility", value);
    },
    [validateField],
  );
  const setTemplate = useCallback(
    (value: string) => updateField("template", value, setTemplateState),
    [updateField],
  );
  const setArguments = useCallback(
    (value: string) => updateField("arguments", value, setArgumentsState),
    [updateField],
  );
  const setDescription = useCallback(
    (value: string) => updateField("description", value, setDescriptionState),
    [updateField],
  );
  const setTags = useCallback(
    (value: string) => updateField("tags", value, setTagsState),
    [updateField],
  );

  const validateForm = useCallback((): boolean => {
    const result = schema.safeParse(getFormValues());
    if (result.success) {
      setErrors({});
      return true;
    }

    setErrors(toFieldErrors(result.error));
    return false;
  }, [getFormValues, schema]);

  const resetForm = useCallback(() => {
    setNameState(initialState.name);
    setVisibilityState(initialState.visibility);
    setTemplateState(initialState.template);
    setArgumentsState(initialState.arguments);
    setDescriptionState(initialState.description);
    setTagsState(initialState.tags);
    setErrors({});
  }, []);

  const getFormData = useCallback(
    (): CreatePromptPayload => schema.parse(getFormValues()),
    [getFormValues, schema],
  );

  const handleSubmit = useCallback(
    async (event: FormEvent<HTMLFormElement>, onSuccess?: () => void) => {
      event.preventDefault();
      if (!validateForm()) return;

      try {
        await createPrompt(getFormData());
        setErrors({});
        resetForm();
        onSuccess?.();
      } catch (error) {
        const fieldError = getApiFieldError(error);
        if (fieldError) {
          setErrors(fieldError);
        } else {
          setErrors({
            submit: parseApiError(error, intl.formatMessage({ id: "prompts.add.error" })),
          });
        }
      }
    },
    [createPrompt, getFormData, intl, resetForm, validateForm],
  );

  useEffect(() => {
    if (visibility === "team") {
      validateField("visibility", visibility);
    }
  }, [validateField, visibility]);

  const isValid = useMemo(() => schema.safeParse(getFormValues()).success, [getFormValues, schema]);

  return {
    name,
    visibility,
    teamId,
    template,
    arguments: argumentsValue,
    description,
    tags,
    errors,
    isValid,
    isSubmitting,
    setName,
    setVisibility,
    setTemplate,
    setArguments,
    setDescription,
    setTags,
    validateField,
    validateForm,
    resetForm,
    getFormData,
    handleSubmit,
  };
}
