import { useState, useCallback, useMemo, type FormEvent } from "react";
import { useIntl } from "react-intl";
import { z } from "zod";
import { useQuery } from "@/hooks/useQuery";
import { resourcesApi } from "@/api/resources";
import { sanitizeString } from "@/lib/sanitize";
import { parseApiError } from "@/lib/errorUtils";
import type { BodyCreateResourceV1ResourcesPost, ResourceUpdate } from "@/generated/types";
import type { Visibility } from "@/types/server";

const createResourceFormSchema = (intl: ReturnType<typeof useIntl>) =>
  z.object({
    uri: z.string().min(1, intl.formatMessage({ id: "resources.form.error.uriRequired" })),
    name: z
      .string()
      .min(1, intl.formatMessage({ id: "resources.form.error.nameRequired" }))
      .max(255, intl.formatMessage({ id: "resources.form.error.nameMax" }))
      .regex(
        /^[a-zA-Z0-9_.\- ]+$/,
        intl.formatMessage({ id: "resources.form.error.nameInvalidChars" }),
      ),
    content: z.string().min(1, intl.formatMessage({ id: "resources.form.error.contentRequired" })),
    description: z
      .string()
      .max(500, intl.formatMessage({ id: "resources.form.error.descriptionMax" }))
      .optional(),
    mimeType: z.string().optional(),
    tags: z.string().optional(),
  });

export type ResourceFormData = z.infer<ReturnType<typeof createResourceFormSchema>>;

export interface ResourceFormErrors {
  uri?: string;
  name?: string;
  content?: string;
  description?: string;
  mimeType?: string;
  tags?: string;
  submit?: string;
}

export interface ResourceFormInitialValues {
  uri?: string;
  name?: string;
  content?: string;
  description?: string;
  mimeType?: MimeType | "";
  tags?: string;
  visibility?: Visibility;
}

export interface ResourceFormOptions {
  onBeforeSubmit?: (data: BodyCreateResourceV1ResourcesPost) => void;
  onError?: () => void;
  resourceId?: string;
  initialValues?: ResourceFormInitialValues;
}

export interface UseResourceFormReturn {
  uri: string;
  name: string;
  content: string;
  description: string;
  mimeType: MimeType | "";
  tags: string;
  visibility: Visibility;
  errors: ResourceFormErrors;
  isSubmitting: boolean;
  setUri: (value: string) => void;
  setName: (value: string) => void;
  setContent: (value: string) => void;
  setDescription: (value: string) => void;
  setMimeType: (value: MimeType | "") => void;
  setTags: (value: string) => void;
  setVisibility: (value: Visibility) => void;
  validateForm: () => boolean;
  handleSubmit: (
    event: FormEvent<HTMLFormElement>,
    onSuccess?: (name: string) => void,
  ) => Promise<void>;
  getFormData: () => BodyCreateResourceV1ResourcesPost;
}

export const MIME_TYPES = [
  "text/plain",
  "text/markdown",
  "text/html",
  "text/csv",
  "application/json",
  "application/xml",
  "application/pdf",
] as const;

export type MimeType = (typeof MIME_TYPES)[number];

export function useResourceForm(options: ResourceFormOptions = {}): UseResourceFormReturn {
  const { onBeforeSubmit, onError, resourceId, initialValues } = options;
  const intl = useIntl();
  const schema = useMemo(() => createResourceFormSchema(intl), [intl]);

  const [uri, setUri] = useState(initialValues?.uri ?? "");
  const [name, setName] = useState(initialValues?.name ?? "");
  const [content, setContent] = useState(initialValues?.content ?? "");
  const [description, setDescription] = useState(initialValues?.description ?? "");
  const [mimeType, setMimeType] = useState<MimeType | "">(initialValues?.mimeType ?? "");
  const [tags, setTags] = useState(initialValues?.tags ?? "");
  const [visibility, setVisibility] = useState<Visibility>(initialValues?.visibility ?? "public");
  const [errors, setErrors] = useState<ResourceFormErrors>({});
  const [isUpdating, setIsUpdating] = useState(false);

  const { execute: createResource, isLoading: isCreating } = useQuery<
    unknown,
    BodyCreateResourceV1ResourcesPost
  >("/resources", { method: "POST", enabled: false });

  const isSubmitting = isCreating || isUpdating;

  const getFormData = useCallback((): BodyCreateResourceV1ResourcesPost => {
    return {
      resource: {
        uri: sanitizeString(uri, 2000),
        name: sanitizeString(name, 100),
        content,
        description: description ? sanitizeString(description, 500) : undefined,
        mimeType: mimeType ? sanitizeString(mimeType, 200) : undefined,
        tags: tags
          ? tags
              .split(",")
              .map((t) => sanitizeString(t.trim(), 200))
              .filter(Boolean)
          : undefined,
        visibility,
      },
    };
  }, [uri, name, content, description, mimeType, tags, visibility]);

  const validateForm = useCallback((): boolean => {
    try {
      schema.parse({
        uri,
        name,
        content,
        description: description || undefined,
        mimeType: mimeType || undefined,
        tags: tags || undefined,
      });
      setErrors({});
      return true;
    } catch (error) {
      if (error instanceof z.ZodError) {
        const newErrors: ResourceFormErrors = {};
        error.issues.forEach((issue) => {
          const path = issue.path[0] as keyof ResourceFormErrors;
          newErrors[path] = issue.message;
        });
        setErrors(newErrors);
      }
      return false;
    }
  }, [uri, name, content, description, mimeType, tags, schema]);

  const handleSubmit = useCallback(
    async (event: FormEvent<HTMLFormElement>, onSuccess?: (name: string) => void) => {
      event.preventDefault();

      if (!validateForm()) return;

      const formData = getFormData();
      onBeforeSubmit?.(formData);

      try {
        if (resourceId) {
          const { resource } = formData;
          const updatePayload: ResourceUpdate = {
            uri: resource.uri,
            name: resource.name,
            content: resource.content,
            description: resource.description,
            mimeType: resource.mimeType,
            tags: resource.tags,
            visibility: resource.visibility,
          };
          setIsUpdating(true);
          try {
            await resourcesApi.update(resourceId, updatePayload);
          } finally {
            setIsUpdating(false);
          }
        } else {
          await createResource(formData);
        }
        setErrors({});
        if (onSuccess) onSuccess(formData.resource.name);
      } catch (error) {
        onError?.();
        const fallback = intl.formatMessage({
          id: resourceId
            ? "resources.form.error.updateFailed"
            : "resources.form.error.createFailed",
        });
        setErrors({ submit: parseApiError(error, fallback) });
      }
    },
    [validateForm, getFormData, onBeforeSubmit, createResource, resourceId, onError, intl],
  );

  return {
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
    validateForm,
    handleSubmit,
    getFormData,
  };
}
