import { useState, useCallback, useMemo, type FormEvent } from "react";
import { z } from "zod";
import { api } from "@/api/client";
import { useQuery } from "@/hooks/useQuery";
import type { Visibility } from "@/types/server";
import { sanitizeString, sanitizeUrl, sanitizePassword, sanitizeToken } from "@/lib/sanitize";

export type RequestType = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
export type AuthType = "none" | "basic" | "bearer" | "custom";
export type SchemaMode = "none" | "generated" | "manual";

export interface CustomHeader {
  id: string;
  key: string;
  value: string;
}

// Zod schema for form validation with sanitization
const toolFormObjectSchema = z.object({
  name: z
    .string()
    .transform((val) => sanitizeString(val, 100))
    .pipe(z.string().min(1, "Name is required").max(100, "Name must be less than 100 characters")),
  url: z
    .string()
    .transform((val) => sanitizeUrl(val, 2000))
    .pipe(
      z
        .string()
        .min(1, "URL is required")
        .refine(
          (value) => {
            try {
              const url = new URL(value);
              return url.protocol === "http:" || url.protocol === "https:";
            } catch {
              return false;
            }
          },
          { message: "URL must start with http:// or https://" },
        ),
    ),
  description: z
    .string()
    .transform((val) => sanitizeString(val, 500))
    .pipe(z.string().max(500, "Description must be less than 500 characters"))
    .optional(),
  requestType: z
    .enum(["GET", "POST", "PUT", "PATCH", "DELETE", "STREAMABLEHTTP", "SSE"])
    .optional(),
  integrationType: z.string().optional(),
  responseFilter: z
    .string()
    .transform((val) => sanitizeString(val, 500))
    .optional(),
  tags: z
    .string()
    .transform((val) => sanitizeString(val, 500))
    .optional(),
  inputSchema: z.record(z.unknown()).optional(),
  outputSchema: z.record(z.unknown()).optional(),
  authType: z.string().optional(),
  authUsername: z
    .string()
    .transform((val) => sanitizeString(val, 200))
    .optional(),
  authPassword: z // pragma: allowlist secret
    .string()
    .transform((val) => sanitizePassword(val, 1000))
    .optional(),
  authToken: z
    .string()
    .transform((val) => sanitizeToken(val, 2000))
    .optional(),
  auth_headers: z.array(z.object({ key: z.string(), value: z.string() })).optional(),
  visibility: z.enum(["public", "private", "team"]).optional(),
  teamId: z.string().optional(),
});

const toolFormSchema = toolFormObjectSchema.superRefine((data, ctx) => {
  // Require teamId when visibility is "team"
  if (data.visibility === "team" && !data.teamId) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      message: "Team selection is required when visibility is set to team",
      path: ["teamId"],
    });
  }

  // Require requestType when integrationType is not "MCP"
  if (data.integrationType !== "MCP" && !data.requestType) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      message: "Request type is required",
      path: ["requestType"],
    });
  }
});

export type ToolFormData = z.infer<typeof toolFormSchema>;

export interface ApiToolAuth {
  authType?: string;
  username?: string;
  password?: string; // pragma: allowlist secret
  token?: string;
  authHeaderKey?: string;
  authHeaderValue?: string;
  authHeaders?: Array<{ key: string; value: string }>;
}

export interface ApiToolPayload {
  tool: {
    name: string;
    url?: string;
    description?: string;
    integration_type: string;
    request_type: string;
    inputSchema?: Record<string, unknown>;
    outputSchema?: Record<string, unknown>;
    jsonpath_filter?: string;
    tags?: string[];
    visibility?: string;
    team_id?: string;
    auth_type?: string;
    auth_username?: string;
    auth_password?: string; // pragma: allowlist secret
    auth_token?: string;
    auth_header_key?: string;
    auth_header_value?: string;
    auth_headers?: Array<{ key: string; value: string }>;
  };
  team_id?: string;
}

export interface FormErrors {
  name?: string;
  url?: string;
  description?: string;
  requestType?: string;
  responseFilter?: string;
  tags?: string;
  teamId?: string;
  schema?: string;
  submit?: string;
}

export interface UseToolFormReturn {
  // Form state
  name: string;
  url: string;
  description: string;
  requestType: RequestType;
  integrationType: string;
  advancedOpen: boolean;
  visibility: Visibility;
  teamId: string;
  authType: AuthType;
  authUsername: string;
  authPassword: string; // pragma: allowlist secret
  bearerToken: string;
  customHeaders: CustomHeader[];
  responseFilter: string;
  tags: string;
  inputSchema: string;
  outputSchema: string;
  isGeneratingSchema: boolean;
  schemaMode: SchemaMode;
  openApiSpecUrl: string;
  showSpecUrlInput: boolean;
  errors: FormErrors;
  isValid: boolean;
  isSubmitting: boolean;

  // Setters
  setName: (value: string) => void;
  setUrl: (value: string) => void;
  setDescription: (value: string) => void;
  setRequestType: (value: RequestType) => void;
  setAdvancedOpen: (value: boolean | ((prev: boolean) => boolean)) => void;
  setVisibility: (value: Visibility) => void;
  setTeamId: (value: string) => void;
  setAuthType: (value: AuthType) => void;
  setAuthUsername: (value: string) => void;
  setAuthPassword: (value: string) => void; // pragma: allowlist secret
  setBearerToken: (value: string) => void;
  setCustomHeaders: (headers: CustomHeader[]) => void;
  setResponseFilter: (value: string) => void;
  setTags: (value: string) => void;
  setInputSchema: (value: string) => void;
  setOutputSchema: (value: string) => void;
  setSchemaMode: (mode: SchemaMode) => void;
  setOpenApiSpecUrl: (value: string) => void;
  generateSchema: () => Promise<void>;

  // Actions
  resetForm: () => void;
  validateForm: () => boolean;
  handleSubmit: (
    event: FormEvent<HTMLFormElement>,
    onSuccess?: (response?: unknown) => void,
  ) => Promise<void>;
  getFormData: () => ApiToolPayload;
}

const initialState = {
  name: "",
  url: "",
  description: "",
  requestType: "POST" as RequestType,
  advancedOpen: false,
  visibility: "public" as Visibility,
  teamId: "",
  authType: "none" as AuthType,
  authUsername: "",
  authPassword: "", // pragma: allowlist secret
  bearerToken: "",
  customHeaders: [] as CustomHeader[],
  responseFilter: "",
  tags: "",
  inputSchema: "",
  outputSchema: "",
};

export interface ToolFormInitialValues {
  name?: string;
  url?: string;
  description?: string;
  requestType?: RequestType;
  integrationType?: string;
  schemaMode?: SchemaMode;
  inputSchema?: string;
  outputSchema?: string;
  tags?: string;
  visibility?: Visibility;
  teamId?: string;
  advancedOpen?: boolean;
  authType?: AuthType;
  authUsername?: string;
  authPassword?: string; // pragma: allowlist secret
  bearerToken?: string;
  customHeaders?: CustomHeader[];
}

export function useToolForm({
  maxCustomHeaders,
  toolId,
  initialValues,
}: {
  maxCustomHeaders?: number;
  toolId?: string;
  initialValues?: ToolFormInitialValues;
} = {}): UseToolFormReturn {
  const [name, setName] = useState(initialValues?.name ?? initialState.name);
  const [url, setUrl] = useState(initialValues?.url ?? initialState.url);
  const [description, setDescription] = useState(
    initialValues?.description ?? initialState.description,
  );
  const [requestType, setRequestType] = useState<RequestType>(
    (initialValues?.requestType as RequestType) ?? initialState.requestType,
  );
  const integrationType = initialValues?.integrationType ?? "REST";
  const [advancedOpen, setAdvancedOpen] = useState(
    initialValues?.advancedOpen ?? initialState.advancedOpen,
  );
  const [visibility, setVisibility] = useState<Visibility>(
    (initialValues?.visibility as Visibility) ?? initialState.visibility,
  );
  const [teamId, setTeamId] = useState(initialValues?.teamId ?? initialState.teamId);
  const [authType, setAuthType] = useState<AuthType>(
    initialValues?.authType ?? initialState.authType,
  );
  const [authUsername, setAuthUsername] = useState(
    initialValues?.authUsername ?? initialState.authUsername,
  );
  const [authPassword, setAuthPassword] = useState(
    initialValues?.authPassword ?? initialState.authPassword,
  ); // pragma: allowlist secret
  const [bearerToken, setBearerToken] = useState(
    initialValues?.bearerToken ?? initialState.bearerToken,
  );
  const [customHeaders, setCustomHeaders] = useState<CustomHeader[]>(
    initialValues?.customHeaders ?? initialState.customHeaders,
  );
  const [responseFilter, setResponseFilter] = useState(initialState.responseFilter);
  const [tags, setTags] = useState(initialValues?.tags ?? initialState.tags);
  const [inputSchema, setInputSchema] = useState(
    initialValues?.inputSchema ?? initialState.inputSchema,
  );
  const [outputSchema, setOutputSchema] = useState(
    initialValues?.outputSchema ?? initialState.outputSchema,
  );
  const [isGeneratingSchema, setIsGeneratingSchema] = useState(false);
  const [schemaMode, setSchemaMode] = useState<SchemaMode>(initialValues?.schemaMode ?? "none");
  const [openApiSpecUrl, setOpenApiSpecUrl] = useState("");
  const [showSpecUrlInput, setShowSpecUrlInput] = useState(false);
  const [errors, setErrors] = useState<FormErrors>({});

  // Use useQuery for POST request to create tool
  const { execute: createTool, isLoading: isCreating } = useQuery<unknown, ApiToolPayload>(
    "/tools",
    {
      method: "POST",
      enabled: false, // Don't execute immediately
    },
  );

  // handleSubmit guards against a missing toolId before calling updateTool,
  // so this URL is only ever used when toolId is defined.
  const { execute: updateTool, isLoading: isUpdating } = useQuery<unknown, Record<string, unknown>>(
    `/tools/${toolId}`,
    {
      method: "PUT",
      enabled: false,
    },
  );

  const isSubmitting = isCreating || isUpdating;

  const generateSchema = useCallback(async () => {
    if (!url.trim()) return;
    try {
      const parsed = new URL(url.trim());
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return;
    } catch {
      return;
    }
    const safeSpecUrl = (() => {
      if (!openApiSpecUrl.trim()) return undefined;
      try {
        const u = new URL(openApiSpecUrl.trim());
        return u.protocol === "http:" || u.protocol === "https:"
          ? openApiSpecUrl.trim()
          : undefined;
      } catch {
        return undefined;
      }
    })();
    setIsGeneratingSchema(true);
    setErrors((prev) => ({ ...prev, schema: undefined }));
    try {
      const payload: Record<string, unknown> = {
        url: url.trim(),
        request_type: requestType,
        ...(safeSpecUrl ? { openapi_url: safeSpecUrl } : {}),
      };

      if (authType === "bearer" && bearerToken.trim()) {
        payload.auth_type = "bearer";
        payload.auth_token = bearerToken;
      } else if (authType === "basic") {
        payload.auth_type = "basic";
        payload.auth_username = authUsername;
        payload.auth_password = authPassword;
      } else if (authType === "custom") {
        const validHeaders = customHeaders.filter((h) => h.key.trim());
        if (validHeaders.length > 0) {
          payload.auth_type = "authheaders";
          if (maxCustomHeaders === 1) {
            payload.auth_header_key = sanitizeString(validHeaders[0].key, 200);
            payload.auth_header_value = sanitizeString(validHeaders[0].value, 1000);
          } else {
            payload.auth_headers = validHeaders.map((h) => ({
              key: sanitizeString(h.key, 200),
              value: sanitizeString(h.value, 1000),
            }));
          }
        }
      }

      const result = await api.post<{
        success: boolean;
        input_schema: Record<string, unknown> | null;
        output_schema: Record<string, unknown> | null;
        message: string;
        requires_auth?: boolean;
      }>("/v1/tools/generate-schemas-from-openapi", payload);
      if (result.success) {
        setInputSchema(result.input_schema ? JSON.stringify(result.input_schema, null, 2) : "");
        setOutputSchema(result.output_schema ? JSON.stringify(result.output_schema, null, 2) : "");
        setSchemaMode("generated");
      } else {
        setErrors((prev) => ({ ...prev, schema: result.message || "Failed to generate schema" }));
      }
    } catch (error) {
      let message = "Failed to generate schema. Check the URL and try again.";
      let requiresAuth = false;
      if (error && typeof error === "object" && "body" in error) {
        const err = error as { body?: { message?: string; requires_auth?: boolean } };
        if (err.body?.message) {
          message = err.body.message;
        }
        if (err.body?.requires_auth) {
          requiresAuth = true;
        }
      }
      if (requiresAuth) {
        setAdvancedOpen(true);
        setShowSpecUrlInput(true);
      }
      setErrors((prev) => ({ ...prev, schema: message }));
    } finally {
      setIsGeneratingSchema(false);
    }
  }, [
    url,
    requestType,
    authType,
    bearerToken,
    authUsername,
    authPassword,
    customHeaders,
    openApiSpecUrl,
    maxCustomHeaders,
  ]);

  const getFormData = useCallback((): ApiToolPayload => {
    const AUTH_TYPE_TO_API: Record<AuthType, string> = {
      none: "",
      basic: "basic",
      bearer: "bearer",
      custom: "authheaders",
    };

    const parseSchemaJson = (raw: string): Record<string, unknown> | undefined => {
      if (!raw.trim()) return undefined;
      try {
        return JSON.parse(raw) as Record<string, unknown>;
      } catch {
        return undefined;
      }
    };

    const tool: ApiToolPayload["tool"] = {
      name: sanitizeString(name, 100),
      url: sanitizeUrl(url, 2000),
      description: description ? sanitizeString(description, 500) : undefined,
      integration_type: "REST",
      request_type: requestType,
      inputSchema: parseSchemaJson(inputSchema),
      outputSchema: parseSchemaJson(outputSchema),
      jsonpath_filter: responseFilter ? sanitizeString(responseFilter, 500) : undefined,
      tags: tags
        ? tags
            .split(",")
            .map((t) => sanitizeString(t.trim(), 200))
            .filter(Boolean)
        : undefined,
      visibility: visibility || undefined,
    };

    const apiAuthType = AUTH_TYPE_TO_API[authType];
    if (apiAuthType) {
      tool.auth_type = apiAuthType;
      if (authType === "basic") {
        if (authUsername) tool.auth_username = sanitizeString(authUsername, 200);
        if (authPassword) tool.auth_password = sanitizePassword(authPassword, 1000); // pragma: allowlist secret
      } else if (authType === "bearer") {
        if (bearerToken) tool.auth_token = sanitizeToken(bearerToken, 2000);
      } else if (authType === "custom") {
        const validHeaders = customHeaders.filter((h) => h.key.trim());
        if (validHeaders.length > 0) {
          if (maxCustomHeaders === 1) {
            tool.auth_header_key = sanitizeString(validHeaders[0].key, 200);
            tool.auth_header_value = sanitizeString(validHeaders[0].value, 1000);
          } else {
            tool.auth_headers = validHeaders.map((h) => ({
              key: sanitizeString(h.key, 200),
              value: sanitizeString(h.value, 1000),
            }));
          }
        }
      }
    }

    return {
      tool,
      team_id: visibility === "team" ? teamId || undefined : undefined,
    };
  }, [
    name,
    url,
    description,
    requestType,
    responseFilter,
    tags,
    inputSchema,
    outputSchema,
    authType,
    authUsername,
    authPassword,
    bearerToken,
    customHeaders,
    visibility,
    teamId,
    maxCustomHeaders,
  ]);

  const validateForm = useCallback((): boolean => {
    const schemaErrors: FormErrors = {};

    if (inputSchema.trim()) {
      try {
        JSON.parse(inputSchema);
      } catch {
        schemaErrors.schema = "Input schema is not valid JSON";
      }
    }
    if (!schemaErrors.schema && outputSchema.trim()) {
      try {
        JSON.parse(outputSchema);
      } catch {
        schemaErrors.schema = "Output schema is not valid JSON";
      }
    }

    if (schemaErrors.schema) {
      setErrors(schemaErrors);
      return false;
    }

    try {
      // Validate using Zod schema field names (camelCase), separate from the API payload shape
      toolFormSchema.parse({
        name,
        url,
        description: description || undefined,
        requestType,
        integrationType,
        responseFilter: responseFilter || undefined,
        tags: tags || undefined,
        visibility: visibility || undefined,
        teamId: visibility === "team" ? teamId || undefined : undefined,
      });
      setErrors({});
      return true;
    } catch (error) {
      if (error instanceof z.ZodError) {
        const newErrors: FormErrors = {};
        error.issues.forEach((issue) => {
          const path = issue.path[0] as keyof FormErrors;
          newErrors[path] = issue.message;
        });
        setErrors(newErrors);
      }
      return false;
    }
  }, [
    name,
    url,
    description,
    requestType,
    integrationType,
    responseFilter,
    tags,
    visibility,
    teamId,
    inputSchema,
    outputSchema,
  ]);

  const resetForm = useCallback(() => {
    setName(initialState.name);
    setUrl(initialState.url);
    setDescription(initialState.description);
    setRequestType(initialState.requestType);
    setAdvancedOpen(initialState.advancedOpen);
    setVisibility(initialState.visibility);
    setTeamId(initialState.teamId);
    setAuthType(initialState.authType);
    setAuthUsername(initialState.authUsername);
    setAuthPassword(initialState.authPassword);
    setBearerToken(initialState.bearerToken);
    setCustomHeaders(initialState.customHeaders);
    setResponseFilter(initialState.responseFilter);
    setTags(initialState.tags);
    setInputSchema(initialState.inputSchema);
    setOutputSchema(initialState.outputSchema);
    setSchemaMode("none");
    setOpenApiSpecUrl("");
    setShowSpecUrlInput(false);
    setErrors({});
  }, []);

  const handleSubmit = useCallback(
    async (event: FormEvent<HTMLFormElement>, onSuccess?: (response?: unknown) => void) => {
      event.preventDefault();

      const formValid = validateForm();

      if (formValid) {
        try {
          const formData = getFormData();
          let response: unknown;
          if (toolId) {
            const { request_type } = formData.tool;
            const REST_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH"];
            const updatePayload = {
              name: formData.tool.name,
              url: formData.tool.url,
              description: formData.tool.description,
              inputSchema: formData.tool.inputSchema,
              outputSchema: formData.tool.outputSchema,
              jsonpath_filter: formData.tool.jsonpath_filter,
              tags: formData.tool.tags,
              visibility: formData.tool.visibility,
              auth_type: formData.tool.auth_type,
              auth_username: formData.tool.auth_username,
              auth_password: formData.tool.auth_password, // pragma: allowlist secret
              auth_token: formData.tool.auth_token,
              auth_header_key: formData.tool.auth_header_key,
              auth_header_value: formData.tool.auth_header_value,
              auth_headers: formData.tool.auth_headers,
              customName: formData.tool.name,
              ...(REST_METHODS.includes(request_type)
                ? { requestType: request_type, integrationType: "REST" }
                : {}),
            };
            response = await updateTool(updatePayload);
          } else {
            response = await createTool(formData);
          }

          // Call success callback if provided
          if (onSuccess) {
            onSuccess(response);
          }

          // Reset form after successful submission
          resetForm();
        } catch (error) {
          let errorMessage = toolId
            ? "Failed to update tool. Please try again."
            : "Failed to create tool. Please try again.";

          if (error && typeof error === "object" && "body" in error) {
            const errorWithBody = error as {
              body?: {
                detail?: Array<{ msg?: string; loc?: string[] }> | string;
                message?: string;
              };
            };

            const { message: bodyMessage, detail } = errorWithBody.body ?? {};

            if (bodyMessage) {
              // 403 ORJSONResponse shape: { message: "..." }
              errorMessage = bodyMessage;
            } else if (typeof detail === "string" && detail) {
              // HTTPException shape: { detail: "..." }
              errorMessage = detail;
            } else if (Array.isArray(detail) && detail.length > 0) {
              // Pydantic validation shape: { detail: [{ loc, msg }] }
              errorMessage = detail
                .map((err) => {
                  const field = err.loc && err.loc.length > 1 ? err.loc[err.loc.length - 1] : "";
                  const msg = err.msg || "Invalid value";
                  return field ? `${field}: ${msg}` : msg;
                })
                .join("; ");
            }
          }

          setErrors({ submit: errorMessage });
        }
      }
    },
    [validateForm, getFormData, createTool, updateTool, resetForm, toolId],
  );

  const isValid = useMemo(() => {
    if (inputSchema.trim()) {
      try {
        JSON.parse(inputSchema);
      } catch {
        return false;
      }
    }
    if (outputSchema.trim()) {
      try {
        JSON.parse(outputSchema);
      } catch {
        return false;
      }
    }
    return toolFormSchema.safeParse({
      name,
      url,
      description: description || undefined,
      requestType,
      integrationType,
      responseFilter: responseFilter || undefined,
      tags: tags || undefined,
      visibility: visibility || undefined,
      teamId: visibility === "team" ? teamId || undefined : undefined,
    }).success;
  }, [
    name,
    url,
    description,
    requestType,
    integrationType,
    responseFilter,
    tags,
    visibility,
    teamId,
    inputSchema,
    outputSchema,
  ]);

  return {
    // State
    name,
    url,
    description,
    requestType,
    integrationType,
    advancedOpen,
    visibility,
    teamId,
    authType,
    authUsername,
    authPassword,
    bearerToken,
    customHeaders,
    responseFilter,
    tags,
    inputSchema,
    outputSchema,
    isGeneratingSchema,
    schemaMode,
    openApiSpecUrl,
    showSpecUrlInput,
    errors,
    isValid,
    isSubmitting,

    // Setters
    setName,
    setUrl,
    setDescription,
    setRequestType,
    setAdvancedOpen,
    setVisibility,
    setTeamId,
    setAuthType,
    setAuthUsername,
    setAuthPassword,
    setBearerToken,
    setCustomHeaders,
    setResponseFilter,
    setTags,
    setInputSchema,
    setOutputSchema,
    setSchemaMode,
    setOpenApiSpecUrl,
    generateSchema,

    // Actions
    resetForm,
    validateForm,
    handleSubmit,
    getFormData,
  };
}
