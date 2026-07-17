import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { useIntl } from "react-intl";
import { z } from "zod";
import { useAuthContext } from "@/auth/AuthContext";
import { useQuery } from "@/hooks/useQuery";
import { promptsApi } from "@/api/prompts";
import { parseApiError } from "@/lib/errorUtils";
import { sanitizeString } from "@/lib/sanitize";
import type {
  BodyCreatePromptV1PromptsPost,
  PromptArgument,
  PromptRead,
  PromptUpdate,
} from "@/generated/types";
import type { PromptFormErrors } from "@/types/prompts";
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

export interface PromptFormInitialValues {
  name?: string;
  visibility?: Visibility;
  template?: string;
  arguments?: string;
  description?: string;
  tags?: string;
  /**
   * The prompt's existing team (edit mode). When set, a `team`-visibility edit
   * keeps this team instead of forcing the caller to (re)select one in the
   * sidebar, so editing a team prompt never silently reassigns or blocks it.
   */
  teamId?: string | null;
}

export interface UsePromptFormOptions {
  /** When set, the form updates this prompt (`PUT /prompts/{id}`) instead of creating one. */
  promptId?: string;
  /** Values to prefill the form with (edit mode). */
  initialValues?: PromptFormInitialValues;
  /**
   * Whether the template field is required. Defaults to `true` (REST/local
   * prompts). Pass `false` for federated prompts, which legitimately have no
   * local template.
   */
  templateRequired?: boolean;
}

// The generated `prompt` field is nullable to match the server's Optional
// schema; the form always constructs a real object, so narrow it locally.
type CreatePromptPayload = Omit<BodyCreatePromptV1PromptsPost, "prompt"> & {
  prompt: NonNullable<BodyCreatePromptV1PromptsPost["prompt"]>;
};

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

function parseTags(value?: string): string[] | undefined {
  const tags = value
    ?.split(",")
    .map((tag) => sanitizeString(tag, 200))
    .filter(Boolean);

  return tags && tags.length > 0 ? tags : undefined;
}

const createPromptFormSchema = (intl: ReturnType<typeof useIntl>, templateRequired: boolean) =>
  z
    .object({
      name: z
        .string()
        .transform((value) => sanitizeString(value, 100))
        .pipe(z.string().min(1, intl.formatMessage({ id: "prompts.add.error.nameRequired" }))),
      visibility: z.enum(["public", "private", "team"]),
      // Local (REST) prompts carry their content in `template`, so it is
      // required. Federated prompts have no local template — the upstream MCP
      // server resolves the content on `prompts/get` — so the field is optional
      // when editing them.
      template: templateRequired
        ? z.string().min(1, intl.formatMessage({ id: "prompts.add.error.templateRequired" }))
        : z.string(),
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
      description: z
        .string()
        .transform((value) => sanitizeString(value, 500))
        .optional(),
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
          teamId,
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
  if (field === "name" || field === "visibility" || field === "template" || field === "arguments") {
    return { [field]: body.message };
  }

  return null;
}

export function usePromptForm(options: UsePromptFormOptions = {}): UsePromptFormReturn {
  const { promptId, initialValues, templateRequired = true } = options;
  const intl = useIntl();
  const { selectedTeamId } = useAuthContext();
  const schema = useMemo(
    () => createPromptFormSchema(intl, templateRequired),
    [intl, templateRequired],
  );

  const [name, setNameState] = useState(initialValues?.name ?? initialState.name);
  const [visibility, setVisibilityState] = useState<Visibility>(
    initialValues?.visibility ?? initialState.visibility,
  );
  const [template, setTemplateState] = useState(initialValues?.template ?? initialState.template);
  const [argumentsValue, setArgumentsState] = useState(
    initialValues?.arguments ?? initialState.arguments,
  );
  const [description, setDescriptionState] = useState(
    initialValues?.description ?? initialState.description,
  );
  const [tags, setTagsState] = useState(initialValues?.tags ?? initialState.tags);
  const [errors, setErrors] = useState<PromptFormErrors>({});
  const [isUpdating, setIsUpdating] = useState(false);
  // In edit mode, keep the prompt's own team; only fall back to the sidebar
  // selection (create mode, or when switching a non-team prompt to team).
  const initialTeamId = initialValues?.teamId ?? undefined;
  const resolveTeamId = (vis: Visibility): string | undefined =>
    vis === "team" ? (initialTeamId ?? selectedTeamId ?? undefined) : undefined;
  const teamId = resolveTeamId(visibility);
  const { execute: createPrompt, isLoading: isCreating } = useQuery<
    PromptRead,
    CreatePromptPayload
  >("/prompts", {
    method: "POST",
    enabled: false,
  });

  const isSubmitting = isCreating || isUpdating;

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
        nextValues.teamId =
          value === "team" ? (initialTeamId ?? selectedTeamId ?? undefined) : undefined;
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
    [getFormValues, schema, selectedTeamId, initialTeamId],
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

  const getUpdateData = useCallback((): NonNullable<PromptUpdate> => {
    const { prompt } = schema.parse(getFormValues());
    return {
      name: prompt.name,
      description: prompt.description ?? null,
      template: prompt.template,
      arguments: prompt.arguments,
      tags: prompt.tags ?? null,
      teamId: prompt.teamId,
      visibility: prompt.visibility,
    };
  }, [getFormValues, schema]);

  const handleSubmit = useCallback(
    async (event: FormEvent<HTMLFormElement>, onSuccess?: () => void) => {
      event.preventDefault();
      if (!validateForm()) return;

      try {
        if (promptId) {
          setIsUpdating(true);
          try {
            await promptsApi.update(promptId, getUpdateData());
          } finally {
            setIsUpdating(false);
          }
        } else {
          await createPrompt(getFormData());
          resetForm();
        }
        setErrors({});
        onSuccess?.();
      } catch (error) {
        const fieldError = getApiFieldError(error);
        if (fieldError) {
          setErrors(fieldError);
        } else {
          setErrors({
            submit: parseApiError(
              error,
              intl.formatMessage({ id: promptId ? "prompts.edit.error" : "prompts.add.error" }),
            ),
          });
        }
      }
    },
    [createPrompt, getFormData, getUpdateData, intl, promptId, resetForm, validateForm],
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
