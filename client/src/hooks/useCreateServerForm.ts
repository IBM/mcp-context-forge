import { useCallback, useMemo, useState, type FormEvent } from "react";
import { useIntl } from "react-intl";
import { z } from "zod";
import type { CreateServerDetails } from "@/components/gateways/types";
import type { Visibility } from "@/types/server";
import { sanitizeString } from "@/lib/sanitize";

function createServerFormSchema(messages: {
  nameRequired: string;
  nameMax: string;
  tagsMax: string;
  descriptionMax: string;
}) {
  return z.object({
    name: z
      .string()
      .transform((value) => sanitizeString(value, 100))
      .pipe(z.string().min(1, messages.nameRequired).max(100, messages.nameMax)),
    visibility: z.enum(["team", "public", "private"]),
    oauthEnabled: z.boolean(),
    tags: z
      .string()
      .transform((value) =>
        value
          .split(",")
          .map((tag) => sanitizeString(tag, 50))
          .filter(Boolean),
      )
      .pipe(z.array(z.string()).max(20, messages.tagsMax)),
    description: z
      .string()
      .transform((value) => sanitizeString(value, 500))
      .pipe(z.string().max(500, messages.descriptionMax)),
  });
}

export type CreateServerFormData = z.infer<ReturnType<typeof createServerFormSchema>>;

interface CreateServerFormValues {
  name: string;
  visibility: Visibility;
  oauthEnabled: boolean;
  tags: string;
  description: string;
}

export interface CreateServerFormInitialValues {
  name?: string;
  visibility?: Visibility;
  oauthEnabled?: boolean;
  tags?: string[];
  description?: string;
}

export interface CreateServerFormErrors {
  name?: string;
  visibility?: string;
  oauthEnabled?: string;
  tags?: string;
  description?: string;
  submit?: string;
}

export interface UseCreateServerFormReturn {
  name: string;
  visibility: Visibility;
  oauthEnabled: boolean;
  tags: string;
  description: string;
  errors: CreateServerFormErrors;
  isValid: boolean;
  setName: (value: string) => void;
  setVisibility: (value: Visibility) => void;
  setOAuthEnabled: (value: boolean) => void;
  setTags: (value: string) => void;
  setDescription: (value: string) => void;
  validateField: (field: keyof CreateServerFormErrors, value: string | boolean) => void;
  validateForm: () => boolean;
  getFormData: () => CreateServerDetails;
  resetForm: () => void;
  handleSubmit: (
    event: FormEvent<HTMLFormElement>,
    onSuccess?: (details: CreateServerDetails) => void,
  ) => void;
}

const initialState: CreateServerFormValues = {
  name: "",
  visibility: "team",
  oauthEnabled: false,
  tags: "",
  description: "",
};

function toFieldErrors(error: z.ZodError): CreateServerFormErrors {
  const nextErrors: CreateServerFormErrors = {};
  error.issues.forEach((issue) => {
    const path = issue.path[0] as keyof CreateServerFormErrors;
    nextErrors[path] = issue.message;
  });
  return nextErrors;
}

function getInitialState(initialValues?: CreateServerFormInitialValues): CreateServerFormValues {
  return {
    name: initialValues?.name ?? initialState.name,
    visibility: initialValues?.visibility ?? initialState.visibility,
    oauthEnabled: initialValues?.oauthEnabled ?? initialState.oauthEnabled,
    tags: initialValues?.tags?.join(", ") ?? initialState.tags,
    description: initialValues?.description ?? initialState.description,
  };
}

export function useCreateServerForm(
  initialValues?: CreateServerFormInitialValues,
): UseCreateServerFormReturn {
  const intl = useIntl();
  const invalidValueMessage = intl.formatMessage({
    id: "gateways.createServer.validation.invalid",
  });
  const schema = useMemo(
    () =>
      createServerFormSchema({
        nameRequired: intl.formatMessage({
          id: "gateways.createServer.validation.nameRequired",
        }),
        nameMax: intl.formatMessage({ id: "gateways.createServer.validation.nameMax" }),
        tagsMax: intl.formatMessage({ id: "gateways.createServer.validation.tagsMax" }),
        descriptionMax: intl.formatMessage({
          id: "gateways.createServer.validation.descriptionMax",
        }),
      }),
    [intl],
  );
  const resolvedInitialState = useMemo(() => getInitialState(initialValues), [initialValues]);
  const [name, setName] = useState(resolvedInitialState.name);
  const [visibility, setVisibility] = useState<Visibility>(resolvedInitialState.visibility);
  const [oauthEnabled, setOAuthEnabled] = useState(resolvedInitialState.oauthEnabled);
  const [tags, setTags] = useState(resolvedInitialState.tags);
  const [description, setDescription] = useState(resolvedInitialState.description);
  const [errors, setErrors] = useState<CreateServerFormErrors>({});

  const getFormValues = useCallback(
    (): CreateServerFormValues => ({
      name,
      visibility,
      oauthEnabled,
      tags,
      description,
    }),
    [name, visibility, oauthEnabled, tags, description],
  );

  const getFormData = useCallback((): CreateServerDetails => {
    const parsed = schema.parse(getFormValues());
    return {
      name: parsed.name,
      visibility: parsed.visibility,
      oauthEnabled: parsed.oauthEnabled,
      tags: parsed.tags.length > 0 ? parsed.tags : undefined,
      description: parsed.description || undefined,
    };
  }, [getFormValues, schema]);

  const validateField = useCallback(
    (field: keyof CreateServerFormErrors, value: string | boolean) => {
      if (field === "submit") return;

      try {
        const fieldSchema = schema.shape[field as keyof typeof schema.shape];
        if (!fieldSchema) return;

        fieldSchema.parse(value);
        setErrors((current) => {
          const nextErrors = { ...current };
          delete nextErrors[field];
          return nextErrors;
        });
      } catch (error) {
        if (error instanceof z.ZodError) {
          setErrors((current) => ({
            ...current,
            [field]: error.issues[0]?.message || invalidValueMessage,
          }));
        }
      }
    },
    [invalidValueMessage, schema],
  );

  const validateForm = useCallback((): boolean => {
    try {
      schema.parse(getFormValues());
      setErrors({});
      return true;
    } catch (error) {
      if (error instanceof z.ZodError) {
        setErrors(toFieldErrors(error));
      }
      return false;
    }
  }, [getFormValues, schema]);

  const resetForm = useCallback(() => {
    setName(resolvedInitialState.name);
    setVisibility(resolvedInitialState.visibility);
    setOAuthEnabled(resolvedInitialState.oauthEnabled);
    setTags(resolvedInitialState.tags);
    setDescription(resolvedInitialState.description);
    setErrors({});
  }, [resolvedInitialState]);

  const handleSubmit = useCallback(
    (event: FormEvent<HTMLFormElement>, onSuccess?: (details: CreateServerDetails) => void) => {
      event.preventDefault();

      if (!validateForm()) return;

      try {
        onSuccess?.(getFormData());
      } catch (error) {
        if (error instanceof z.ZodError) {
          setErrors(toFieldErrors(error));
          return;
        }
      }
    },
    [getFormData, validateForm],
  );

  const isValid = useMemo(() => {
    return schema.safeParse(getFormValues()).success;
  }, [getFormValues, schema]);

  return {
    name,
    visibility,
    oauthEnabled,
    tags,
    description,
    errors,
    isValid,
    setName,
    setVisibility,
    setOAuthEnabled,
    setTags,
    setDescription,
    validateField,
    validateForm,
    getFormData,
    resetForm,
    handleSubmit,
  };
}
