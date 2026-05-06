import { useState, useCallback, useMemo, type FormEvent } from "react";
import { z } from "zod";
import { useQuery } from "@/hooks/useQuery";
import {
  sanitizeString,
  sanitizeUrl,
  sanitizePassword,
  sanitizeToken,
  sanitizeQueryParam,
  sanitizeCertificate,
} from "@/lib/sanitize";

export type TransportType = "SSE" | "STREAMABLEHTTP";
export type AuthType = "none" | "basic" | "bearer" | "custom" | "oauth" | "query";

export interface CustomHeader {
  id: string;
  key: string;
  value: string;
}

// Zod schema for form validation with sanitization - matches API request body
const mcpServerFormSchema = z.object({
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
  transport: z.enum(["SSE", "STREAMABLEHTTP"]),
  passthroughHeaders: z.array(z.string().transform((val) => sanitizeString(val, 200))).optional(),
  authType: z.string().optional(),
  authUsername: z
    .string()
    .transform((val) => sanitizeString(val, 200))
    .optional(),
  authPassword: z
    .string()
    .transform((val) => sanitizePassword(val, 1000))
    .optional(),
  authToken: z
    .string()
    .transform((val) => sanitizeToken(val, 2000))
    .optional(),
  authHeaderKey: z
    .string()
    .transform((val) => sanitizeString(val, 200))
    .optional(),
  authHeaderValue: z
    .string()
    .transform((val) => sanitizeString(val, 500))
    .optional(),
  authQueryParamKey: z
    .string()
    .transform((val) => sanitizeQueryParam(val, 100))
    .optional(),
  authQueryParamValue: z
    .string()
    .transform((val) => sanitizeQueryParam(val, 500))
    .optional(),
  oneTimeAuth: z.boolean().optional(),
  visibility: z.enum(["public", "private"]).optional(),
  caCertificate: z
    .string()
    .transform((val) => sanitizeCertificate(val, 10000))
    .optional(),
});

export type MCPServerFormData = z.infer<typeof mcpServerFormSchema>;

export interface FormErrors {
  name?: string;
  url?: string;
  description?: string;
  transport?: string;
  passthroughHeaders?: string;
  authType?: string;
  authUsername?: string;
  authPassword?: string;
  authToken?: string;
  authHeaderKey?: string;
  authHeaderValue?: string;
  authQueryParamKey?: string;
  authQueryParamValue?: string;
  oneTimeAuth?: string;
  visibility?: string;
  caCertificate?: string;
  submit?: string;
}

export interface UseMCPServerFormReturn {
  // Form state
  name: string;
  url: string;
  description: string;
  transport: TransportType;
  advancedOpen: boolean;
  visibility: string;
  authType: AuthType;
  oneTimeAuth: boolean;
  passthroughHeaders: string;
  authUsername: string;
  authPassword: string;
  authToken: string;
  authHeaderKey: string;
  authHeaderValue: string;
  authQueryParamKey: string;
  authQueryParamValue: string;
  caCertificate: string;
  // OAuth fields
  bearerToken: string;
  customHeaders: CustomHeader[];
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
  queryParamName: string;
  queryParamApiKey: string;
  errors: FormErrors;
  isValid: boolean;
  isSubmitting: boolean;

  // Setters
  setName: (value: string) => void;
  setUrl: (value: string) => void;
  setDescription: (value: string) => void;
  setTransport: (value: TransportType) => void;
  setAdvancedOpen: (value: boolean | ((prev: boolean) => boolean)) => void;
  setVisibility: (value: string) => void;
  setAuthType: (value: AuthType) => void;
  setOneTimeAuth: (value: boolean) => void;
  setPassthroughHeaders: (value: string) => void;
  setAuthUsername: (value: string) => void;
  setAuthPassword: (value: string) => void;
  setAuthToken: (value: string) => void;
  setAuthHeaderKey: (value: string) => void;
  setAuthHeaderValue: (value: string) => void;
  setAuthQueryParamKey: (value: string) => void;
  setAuthQueryParamValue: (value: string) => void;
  setCaCertificate: (value: string) => void;
  // OAuth setters
  setBearerToken: (value: string) => void;
  setCustomHeaders: (headers: CustomHeader[]) => void;
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
  setQueryParamName: (value: string) => void;
  setQueryParamApiKey: (value: string) => void;

  // Field-level validation
  validateField: (field: keyof FormErrors, value: string) => void;

  // Actions
  resetForm: () => void;
  validateForm: () => boolean;
  handleSubmit: (event: FormEvent<HTMLFormElement>, onSuccess?: () => void) => Promise<void>;
  getFormData: () => MCPServerFormData;
}

const initialState = {
  name: "",
  url: "",
  description: "",
  transport: "STREAMABLEHTTP" as TransportType,
  advancedOpen: false,
  visibility: "public",
  authType: "none" as AuthType,
  oneTimeAuth: false,
  passthroughHeaders: "",
  authUsername: "",
  authPassword: "",
  authToken: "",
  authHeaderKey: "",
  authHeaderValue: "",
  authQueryParamKey: "",
  authQueryParamValue: "",
  caCertificate: "",
  bearerToken: "",
  customHeaders: [] as CustomHeader[],
  oauthClientId: "",
  oauthClientSecret: "",
  oauthTokenUrl: "",
  oauthGrantType: "client_credentials",
  oauthIssuerUrl: "",
  oauthRedirectUri: "",
  oauthAuthorizationUrl: "",
  oauthScopes: "",
  oauthStoreTokens: true,
  oauthAutoRefresh: true,
  queryParamName: "",
  queryParamApiKey: "",
};

export function useMCPServerForm(gatewayId?: string): UseMCPServerFormReturn {
  const [name, setName] = useState(initialState.name);
  const [url, setUrl] = useState(initialState.url);
  const [description, setDescription] = useState(initialState.description);
  const [transport, setTransport] = useState<TransportType>(initialState.transport);
  const [advancedOpen, setAdvancedOpen] = useState(initialState.advancedOpen);
  const [visibility, setVisibility] = useState(initialState.visibility);
  const [authType, setAuthType] = useState<AuthType>(initialState.authType);
  const [oneTimeAuth, setOneTimeAuth] = useState(initialState.oneTimeAuth);
  const [passthroughHeaders, setPassthroughHeaders] = useState(initialState.passthroughHeaders);
  const [authUsername, setAuthUsername] = useState(initialState.authUsername);
  const [authPassword, setAuthPassword] = useState(initialState.authPassword);
  const [authToken, setAuthToken] = useState(initialState.authToken);
  const [authHeaderKey, setAuthHeaderKey] = useState(initialState.authHeaderKey);
  const [authHeaderValue, setAuthHeaderValue] = useState(initialState.authHeaderValue);
  const [authQueryParamKey, setAuthQueryParamKey] = useState(initialState.authQueryParamKey);
  const [authQueryParamValue, setAuthQueryParamValue] = useState(initialState.authQueryParamValue);
  const [caCertificate, setCaCertificate] = useState(initialState.caCertificate);
  const [bearerToken, setBearerToken] = useState(initialState.bearerToken);
  const [customHeaders, setCustomHeaders] = useState<CustomHeader[]>(initialState.customHeaders);
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
  const [queryParamName, setQueryParamName] = useState(initialState.queryParamName);
  const [queryParamApiKey, setQueryParamApiKey] = useState(initialState.queryParamApiKey);
  const [errors, setErrors] = useState<FormErrors>({});

  const isEditMode = Boolean(gatewayId);

  // Use useQuery for POST request to create MCP gateway
  const { execute: createGateway, isLoading: isCreating } = useQuery<unknown, MCPServerFormData>(
    "/gateways",
    {
      method: "POST",
      enabled: false, // Don't execute immediately
    },
  );

  // handleSubmit guards against a missing gatewayId before calling updateGateway,
  // so this URL is only ever used when gatewayId is defined.
  const { execute: updateGateway, isLoading: isUpdating } = useQuery<unknown, MCPServerFormData>(
    `/gateways/${gatewayId}`,
    {
      method: "PUT",
      enabled: false, // Don't execute immediately
    },
  );

  const isSubmitting = isCreating || isUpdating;

  const getFormData = useCallback((): MCPServerFormData => {
    // Convert passthroughHeaders string to array
    const headersArray = passthroughHeaders
      .split(",")
      .map((h) => h.trim())
      .filter((h) => h.length > 0);

    return {
      name,
      url,
      description: description || undefined,
      transport,
      passthroughHeaders: headersArray.length > 0 ? headersArray : undefined,
      // Don't send authType if it's "none" - API doesn't accept it
      authType: authType && authType !== "none" ? authType : undefined,
      authUsername: authUsername || undefined,
      authPassword: authPassword || undefined,
      authToken: authToken || undefined,
      authHeaderKey: authHeaderKey || undefined,
      authHeaderValue: authHeaderValue || undefined,
      authQueryParamKey: authQueryParamKey || undefined,
      authQueryParamValue: authQueryParamValue || undefined,
      oneTimeAuth: oneTimeAuth || undefined,
      visibility: (visibility as "public" | "private") || undefined,
      caCertificate: caCertificate || undefined,
    };
  }, [
    name,
    url,
    description,
    transport,
    passthroughHeaders,
    authType,
    authUsername,
    authPassword,
    authToken,
    authHeaderKey,
    authHeaderValue,
    authQueryParamKey,
    authQueryParamValue,
    oneTimeAuth,
    visibility,
    caCertificate,
  ]);

  const validateField = useCallback((field: keyof FormErrors, value: string) => {
    try {
      const fieldSchema =
        mcpServerFormSchema.shape[field as keyof typeof mcpServerFormSchema.shape];
      if (fieldSchema) {
        // passthroughHeaders is stored as a comma-separated string in form state
        // but the Zod schema expects an array; convert before validating
        const parseValue =
          field === "passthroughHeaders"
            ? value
                .split(",")
                .map((h) => h.trim())
                .filter((h) => h.length > 0)
            : value;
        fieldSchema.parse(parseValue);
        setErrors((prev) => {
          const newErrors = { ...prev };
          delete newErrors[field];
          return newErrors;
        });
      }
    } catch (error) {
      if (error instanceof z.ZodError) {
        setErrors((prev) => ({
          ...prev,
          [field]: error.issues[0]?.message || "Invalid value",
        }));
      }
    }
  }, []);

  const validateForm = useCallback((): boolean => {
    try {
      const formData = getFormData();
      mcpServerFormSchema.parse(formData);
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
  }, [getFormData]);

  const resetForm = useCallback(() => {
    setName(initialState.name);
    setUrl(initialState.url);
    setDescription(initialState.description);
    setTransport(initialState.transport);
    setAdvancedOpen(initialState.advancedOpen);
    setVisibility(initialState.visibility);
    setAuthType(initialState.authType);
    setOneTimeAuth(initialState.oneTimeAuth);
    setPassthroughHeaders(initialState.passthroughHeaders);
    setAuthUsername(initialState.authUsername);
    setAuthPassword(initialState.authPassword);
    setAuthToken(initialState.authToken);
    setAuthHeaderKey(initialState.authHeaderKey);
    setAuthHeaderValue(initialState.authHeaderValue);
    setAuthQueryParamKey(initialState.authQueryParamKey);
    setAuthQueryParamValue(initialState.authQueryParamValue);
    setCaCertificate(initialState.caCertificate);
    setBearerToken(initialState.bearerToken);
    setCustomHeaders(initialState.customHeaders);
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
    setQueryParamName(initialState.queryParamName);
    setQueryParamApiKey(initialState.queryParamApiKey);
    setErrors({});
  }, []);

  const handleSubmit = useCallback(
    async (event: FormEvent<HTMLFormElement>, onSuccess?: () => void) => {
      event.preventDefault();

      if (validateForm()) {
        try {
          // Form is valid, proceed with submission
          const formData = getFormData();

          // Call the appropriate API based on mode (create or update)
          if (isEditMode) {
            if (!gatewayId) {
              setErrors({ submit: "Cannot update: gateway ID is missing." });
              return;
            }
            await updateGateway(formData);
          } else {
            await createGateway(formData);
          }

          // Call success callback if provided
          if (onSuccess) {
            onSuccess();
          }

          // Reset form after successful submission (only for create mode)
          if (!isEditMode) {
            resetForm();
          }
        } catch (error) {
          // Handle API errors from useQuery
          const action = isEditMode ? "update" : "create";

          // Parse errors from API response
          let errorMessage = `Failed to ${action} MCP gateway. Please try again.`;

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
    [validateForm, getFormData, createGateway, updateGateway, resetForm, isEditMode],
  );

  const isValid = useMemo(() => {
    if (!name.trim() || !url.trim()) return false;
    try {
      const parsed = new URL(url.trim());
      return parsed.protocol === "http:" || parsed.protocol === "https:";
    } catch {
      return false;
    }
  }, [name, url]);

  return {
    // State
    name,
    url,
    description,
    transport,
    advancedOpen,
    visibility,
    authType,
    oneTimeAuth,
    passthroughHeaders,
    authUsername,
    authPassword,
    authToken,
    authHeaderKey,
    authHeaderValue,
    authQueryParamKey,
    authQueryParamValue,
    caCertificate,
    bearerToken,
    customHeaders,
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
    queryParamName,
    queryParamApiKey,
    errors,
    isValid,
    isSubmitting,

    // Setters
    setName,
    setUrl,
    setDescription,
    setTransport,
    setAdvancedOpen,
    setVisibility,
    setAuthType,
    setOneTimeAuth,
    setPassthroughHeaders,
    setAuthUsername,
    setAuthPassword,
    setAuthToken,
    setAuthHeaderKey,
    setAuthHeaderValue,
    setAuthQueryParamKey,
    setAuthQueryParamValue,
    setCaCertificate,
    setBearerToken,
    setCustomHeaders,
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
    setQueryParamName,
    setQueryParamApiKey,

    // Actions
    resetForm,
    validateForm,
    validateField,
    handleSubmit,
    getFormData,
  };
}
