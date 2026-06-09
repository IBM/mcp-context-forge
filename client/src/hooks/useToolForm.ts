import { useState, useCallback, useMemo, type FormEvent } from "react";
import { z } from "zod";
import { api } from "@/api/client";
import { useQuery } from "@/hooks/useQuery";
import type { Visibility } from "@/types/server";
import { sanitizeString, sanitizeUrl, sanitizePassword, sanitizeToken } from "@/lib/sanitize";

export type RequestType = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
export type AuthType = "none" | "basic" | "bearer" | "custom" | "oauth";
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
  requestType: z.enum(["GET", "POST", "PUT", "PATCH", "DELETE"]),
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
});

export type ToolFormData = z.infer<typeof toolFormSchema>;

export interface ApiToolPayload {
  tool: {
    name: string;
    url?: string;
    description?: string;
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
    oauth_config?: {
      grant_type?: string;
      client_id?: string;
      client_secret?: string; // pragma: allowlist secret
      token_url?: string;
      issuer?: string;
      scopes?: string[];
      store_tokens?: boolean;
      auto_refresh?: boolean;
      username?: string;
      password?: string; // pragma: allowlist secret
      authorization_url?: string;
      redirect_uri?: string;
    };
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
  schema?: string;
  submit?: string;
}

export interface UseToolFormReturn {
  // Form state
  name: string;
  url: string;
  description: string;
  requestType: RequestType;
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
  oauthClientId: string;
  oauthClientSecret: string;
  oauthTokenUrl: string;
  oauthGrantType: string;
  oauthIssuerUrl: string;
  oauthRedirectUri: string;
  oauthAuthorizationUrl: string;
  oauthScopes: string;
  oauthStoreTokens: boolean;
  oauthAutoRefresh: boolean;
  oauthUsername: string;
  oauthPassword: string; // pragma: allowlist secret

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
  setOAuthClientId: (value: string) => void;
  setOAuthClientSecret: (value: string) => void;
  setOAuthTokenUrl: (value: string) => void;
  setOAuthGrantType: (value: string) => void;
  setOAuthIssuerUrl: (value: string) => void;
  setOAuthRedirectUri: (value: string) => void;
  setOAuthAuthorizationUrl: (value: string) => void;
  setOAuthScopes: (value: string) => void;
  setOAuthStoreTokens: (checked: boolean) => void;
  setOAuthAutoRefresh: (checked: boolean) => void;
  setOAuthUsername: (value: string) => void;
  setOAuthPassword: (value: string) => void;

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
  requestType: "GET" as RequestType,
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
  oauthClientId: "",
  oauthClientSecret: "", // pragma: allowlist secret
  oauthTokenUrl: "",
  oauthGrantType: "client_credentials",
  oauthIssuerUrl: "",
  oauthRedirectUri: "",
  oauthAuthorizationUrl: "",
  oauthScopes: "",
  oauthStoreTokens: true,
  oauthAutoRefresh: true,
  oauthUsername: "",
  oauthPassword: "", // pragma: allowlist secret
};

export function useToolForm(): UseToolFormReturn {
  const [name, setName] = useState(initialState.name);
  const [url, setUrl] = useState(initialState.url);
  const [description, setDescription] = useState(initialState.description);
  const [requestType, setRequestType] = useState<RequestType>(initialState.requestType);
  const [advancedOpen, setAdvancedOpen] = useState(initialState.advancedOpen);
  const [visibility, setVisibility] = useState(initialState.visibility);
  const [teamId, setTeamId] = useState(initialState.teamId);
  const [authType, setAuthType] = useState<AuthType>(initialState.authType);
  const [authUsername, setAuthUsername] = useState(initialState.authUsername);
  const [authPassword, setAuthPassword] = useState(initialState.authPassword);
  const [bearerToken, setBearerToken] = useState(initialState.bearerToken);
  const [customHeaders, setCustomHeaders] = useState<CustomHeader[]>(initialState.customHeaders);
  const [responseFilter, setResponseFilter] = useState(initialState.responseFilter);
  const [tags, setTags] = useState(initialState.tags);
  const [inputSchema, setInputSchema] = useState(initialState.inputSchema);
  const [outputSchema, setOutputSchema] = useState(initialState.outputSchema);
  const [isGeneratingSchema, setIsGeneratingSchema] = useState(false);
  const [schemaMode, setSchemaMode] = useState<SchemaMode>("none");
  const [openApiSpecUrl, setOpenApiSpecUrl] = useState("");
  const [showSpecUrlInput, setShowSpecUrlInput] = useState(false);
  const [oauthClientId, setOAuthClientId] = useState(initialState.oauthClientId);
  const [oauthClientSecret, setOAuthClientSecret] = useState(initialState.oauthClientSecret);
  const [oauthTokenUrl, setOAuthTokenUrl] = useState(initialState.oauthTokenUrl);
  const [oauthGrantType, setOAuthGrantType] = useState(initialState.oauthGrantType);
  const [oauthIssuerUrl, setOAuthIssuerUrl] = useState(initialState.oauthIssuerUrl);
  const [oauthRedirectUri, setOAuthRedirectUri] = useState(initialState.oauthRedirectUri);
  const [oauthAuthorizationUrl, setOAuthAuthorizationUrl] = useState(
    initialState.oauthAuthorizationUrl,
  );
  const [oauthScopes, setOAuthScopes] = useState(initialState.oauthScopes);
  const [oauthStoreTokens, setOAuthStoreTokens] = useState(initialState.oauthStoreTokens);
  const [oauthAutoRefresh, setOAuthAutoRefresh] = useState(initialState.oauthAutoRefresh);
  const [oauthUsername, setOAuthUsername] = useState(initialState.oauthUsername);
  const [oauthPassword, setOAuthPassword] = useState(initialState.oauthPassword);
  const [errors, setErrors] = useState<FormErrors>({});

  // Use useQuery for POST request to create tool
  const { execute: createTool, isLoading: isCreating } = useQuery<unknown, ApiToolPayload>(
    "/tools",
    {
      method: "POST",
      enabled: false, // Don't execute immediately
    },
  );

  const isSubmitting = isCreating;

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
          payload.auth_headers = validHeaders.map((h) => ({
            key: sanitizeString(h.key, 200),
            value: sanitizeString(h.value, 1000),
          }));
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
  ]);

  const getFormData = useCallback((): ApiToolPayload => {
    const AUTH_TYPE_TO_API: Record<AuthType, string> = {
      none: "",
      basic: "basic",
      bearer: "bearer",
      custom: "authheaders",
      oauth: "oauth", // pragma: allowlist secret
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
      name,
      url: url || undefined,
      description: description || undefined,
      request_type: requestType,
      inputSchema: parseSchemaJson(inputSchema),
      outputSchema: parseSchemaJson(outputSchema),
      jsonpath_filter: responseFilter || undefined,
      tags: tags
        ? tags
            .split(",")
            .map((t) => t.trim())
            .filter(Boolean)
        : undefined,
      visibility: visibility || undefined,
    };

    const apiAuthType = AUTH_TYPE_TO_API[authType];
    if (apiAuthType) {
      tool.auth_type = apiAuthType;
      if (authType === "basic") {
        if (authUsername) tool.auth_username = authUsername;
        if (authPassword) tool.auth_password = authPassword; // pragma: allowlist secret
      } else if (authType === "bearer") {
        if (bearerToken) tool.auth_token = bearerToken;
      } else if (authType === "custom") {
        const firstHeader = customHeaders.find((h) => h.key.trim());
        if (firstHeader) {
          tool.auth_header_key = firstHeader.key;
          tool.auth_header_value = firstHeader.value;
        }
      } else if (authType === "oauth") {
        const scopesArray = oauthScopes ? oauthScopes.split(/\s+/).filter(Boolean) : undefined;
        const base = {
          issuer: oauthIssuerUrl || undefined,
          scopes: scopesArray,
          store_tokens: oauthStoreTokens,
          auto_refresh: oauthAutoRefresh,
        };
        if (oauthGrantType === "client_credentials") {
          tool.oauth_config = {
            ...base,
            grant_type: "client_credentials",
            client_id: oauthClientId || undefined,
            client_secret: oauthClientSecret || undefined, // pragma: allowlist secret
            token_url: oauthTokenUrl || undefined,
          };
        } else if (oauthGrantType === "authorization_code") {
          tool.oauth_config = {
            ...base,
            grant_type: "authorization_code",
            client_id: oauthClientId || undefined,
            client_secret: oauthClientSecret || undefined, // pragma: allowlist secret
            token_url: oauthTokenUrl || undefined,
            authorization_url: oauthAuthorizationUrl || undefined,
            redirect_uri: oauthRedirectUri || undefined,
          };
        } else if (oauthGrantType === "password") {
          tool.oauth_config = {
            ...base,
            grant_type: "password",
            client_id: oauthClientId || undefined,
            client_secret: oauthClientSecret || undefined, // pragma: allowlist secret
            token_url: oauthTokenUrl || undefined,
            username: oauthUsername || undefined,
            password: oauthPassword || undefined, // pragma: allowlist secret
          };
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
    oauthClientId,
    oauthClientSecret,
    oauthTokenUrl,
    oauthGrantType,
    oauthIssuerUrl,
    oauthRedirectUri,
    oauthAuthorizationUrl,
    oauthScopes,
    oauthStoreTokens,
    oauthAutoRefresh,
    oauthUsername,
    oauthPassword,
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
    setOAuthClientId(initialState.oauthClientId);
    setOAuthClientSecret(initialState.oauthClientSecret);
    setOAuthTokenUrl(initialState.oauthTokenUrl);
    setOAuthGrantType(initialState.oauthGrantType);
    setOAuthIssuerUrl(initialState.oauthIssuerUrl);
    setOAuthRedirectUri(initialState.oauthRedirectUri);
    setOAuthAuthorizationUrl(initialState.oauthAuthorizationUrl);
    setOAuthScopes(initialState.oauthScopes);
    setOAuthStoreTokens(initialState.oauthStoreTokens);
    setOAuthAutoRefresh(initialState.oauthAutoRefresh);
    setOAuthUsername(initialState.oauthUsername);
    setOAuthPassword(initialState.oauthPassword);
    setErrors({});
  }, []);

  const handleSubmit = useCallback(
    async (event: FormEvent<HTMLFormElement>, onSuccess?: (response?: unknown) => void) => {
      event.preventDefault();

      const formValid = validateForm();

      if (formValid) {
        try {
          const formData = getFormData();
          const response = await createTool(formData);

          // Call success callback if provided
          if (onSuccess) {
            onSuccess(response);
          }

          // Reset form after successful submission
          resetForm();
        } catch (error) {
          // Handle API errors from useQuery
          let errorMessage = "Failed to create tool. Please try again.";

          if (error && typeof error === "object" && "body" in error) {
            const errorWithBody = error as {
              body?: {
                detail?: Array<{ msg?: string; loc?: string[] }>;
                message?: string;
              };
            };

            // Check for simple message format first
            if (errorWithBody.body?.message) {
              errorMessage = errorWithBody.body.message;
            }
            // Then check for validation errors format
            else {
              const details = errorWithBody.body?.detail;

              if (Array.isArray(details) && details.length > 0) {
                // Extract error messages from validation errors
                const messages = details
                  .map((err) => {
                    const field = err.loc && err.loc.length > 1 ? err.loc[err.loc.length - 1] : "";
                    const msg = err.msg || "Invalid value";
                    return field ? `${field}: ${msg}` : msg;
                  })
                  .join("; ");
                errorMessage = messages;
              }
            }
          }

          setErrors({ submit: errorMessage });
        }
      }
    },
    [validateForm, getFormData, createTool, resetForm],
  );

  const isValid = useMemo(() => {
    if (!name.trim() || !url.trim()) return false;
    try {
      const parsed = new URL(url.trim());
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return false;
    } catch {
      return false;
    }
    // Require teamId when visibility is "team"
    if (visibility === "team" && (!teamId || !teamId.trim())) {
      return false;
    }
    return true;
  }, [name, url, visibility, teamId]);

  return {
    // State
    name,
    url,
    description,
    requestType,
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
    oauthClientId,
    oauthClientSecret,
    oauthTokenUrl,
    oauthGrantType,
    oauthIssuerUrl,
    oauthRedirectUri,
    oauthAuthorizationUrl,
    oauthScopes,
    oauthStoreTokens,
    oauthAutoRefresh,
    oauthUsername,
    oauthPassword,

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
    setOAuthClientId,
    setOAuthClientSecret,
    setOAuthTokenUrl,
    setOAuthGrantType,
    setOAuthIssuerUrl,
    setOAuthRedirectUri,
    setOAuthAuthorizationUrl,
    setOAuthScopes,
    setOAuthStoreTokens,
    setOAuthAutoRefresh,
    setOAuthUsername,
    setOAuthPassword,

    // Actions
    resetForm,
    validateForm,
    handleSubmit,
    getFormData,
  };
}
