import { useState, useCallback, useMemo, useEffect, type FormEvent } from "react";
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

// Maps frontend AuthType to the API's auth_type field value.
// "none" sends "" to explicitly clear any existing auth config on update.
const AUTH_TYPE_TO_API: Record<AuthType, string> = {
  none: "",
  basic: "basic",
  bearer: "bearer",
  custom: "authheaders",
  oauth: "oauth",
  query: "query_param",
};

// Maps API auth_type values back to the frontend AuthType.
const AUTH_TYPE_FROM_API: Partial<Record<string, AuthType>> = {
  basic: "basic",
  bearer: "bearer",
  authheaders: "custom",
  oauth: "oauth",
  query_param: "query",
};

const oauthConfigSchema = z.object({
  grant_type: z.enum(["client_credentials", "authorization_code", "password"]).optional(),
  issuer: z.string().optional(),
  client_id: z.string().optional(),
  client_secret: z.string().optional(),
  token_url: z.string().optional(),
  authorization_url: z.string().optional(),
  redirect_uri: z.string().optional(),
  scopes: z.array(z.string()).optional(),
  store_tokens: z.boolean().optional(),
  auto_refresh: z.boolean().optional(),
  username: z.string().optional(),
  password: z.string().optional(),
});

// Zod schema for form validation with sanitization - matches API request body
// Keep a reference to the inner ZodObject so validateField can access .shape
// (ZodEffects produced by .superRefine does not expose .shape)
const mcpServerFormObjectSchema = z.object({
    name: z
      .string()
      .transform((val) => sanitizeString(val, 100))
      .pipe(
        z.string().min(1, "Name is required").max(100, "Name must be less than 100 characters"),
      ),
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
    auth_headers: z.array(z.object({ key: z.string(), value: z.string() })).optional(),
    auth_query_param_key: z
      .string()
      .transform((val) => sanitizeQueryParam(val, 100))
      .optional(),
    auth_query_param_value: z
      .string()
      .transform((val) => sanitizeQueryParam(val, 500))
      .optional(),
    oneTimeAuth: z.boolean().optional(),
    visibility: z.enum(["public", "private"]).optional(),
    caCertificate: z
      .string()
      .transform((val) => sanitizeCertificate(val, 10000))
      .optional(),
    oauth_config: oauthConfigSchema.optional(),
  });

const mcpServerFormSchema = mcpServerFormObjectSchema.superRefine((data, ctx) => {
    const config = data.oauth_config;
    if (data.authType === "oauth" && config?.grant_type === "password") {
      if (!config.username) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "Username is required for password grant",
          path: ["oauthUsername"],
        });
      }
      if (!config.password) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "Password is required for password grant",
          path: ["oauthPassword"],
        });
      }
    }
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
  oneTimeAuth?: string;
  visibility?: string;
  caCertificate?: string;
  oauthUsername?: string;
  oauthPassword?: string;
  submit?: string;
}

export interface UseMCPServerFormReturn {
  // Form state
  fetchError: string | undefined;
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
  oauthUsername: string;
  oauthPassword: string;
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
  setOAuthUsername: (value: string) => void;
  setOAuthPassword: (value: string) => void;
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
  oauthUsername: "",
  oauthPassword: "",
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
  const [oauthUsername, setOAuthUsername] = useState(initialState.oauthUsername);
  const [oauthPassword, setOAuthPassword] = useState(initialState.oauthPassword);
  const [queryParamName, setQueryParamName] = useState(initialState.queryParamName);
  const [queryParamApiKey, setQueryParamApiKey] = useState(initialState.queryParamApiKey);
  const [errors, setErrors] = useState<FormErrors>({});

  const isEditMode = Boolean(gatewayId);

  // Fetch server data when in edit mode
  // API response uses camelCase outer keys (via alias_generator), but oauth_config dict stays snake_case
  const { data: serverData, error: serverFetchError } = useQuery<{
    name?: string;
    url?: string;
    description?: string;
    transport?: string;
    visibility?: string;
    authType?: string;
    authUsername?: string;
    authPassword?: string;
    authToken?: string;
    authHeaders?: Array<{ key: string; value: string }>;
    authHeaderKey?: string;
    authHeaderValue?: string;
    authQueryParamKey?: string;
    authQueryParamValueMasked?: string;
    passthroughHeaders?: string[];
    oneTimeAuth?: boolean;
    caCertificate?: string;
    oauthConfig?: {
      grant_type?: string;
      client_id?: string;
      client_secret?: string;
      token_url?: string;
      issuer?: string;
      redirect_uri?: string;
      authorization_url?: string;
      scopes?: string | string[];
      username?: string;
      password?: string;
      store_tokens?: boolean;
      auto_refresh?: boolean;
    };
  }>(`/gateways/${gatewayId}`, {
    enabled: Boolean(gatewayId),
  });

  // Populate form when server data is loaded
  useEffect(() => {
    if (serverData && gatewayId) {
      // Basic fields
      setName(serverData.name || "");
      setUrl(serverData.url || "");
      setDescription(serverData.description || "");
      setTransport((serverData.transport as TransportType) || "STREAMABLEHTTP");
      setVisibility(serverData.visibility || "public");

      // Auth fields — open advanced panel when any auth is configured
      if (serverData.authType) {
        setAuthType(AUTH_TYPE_FROM_API[serverData.authType] ?? (serverData.authType as AuthType));
        setAdvancedOpen(true);
      }
      if (serverData.authUsername) setAuthUsername(serverData.authUsername);
      if (serverData.authPassword) setAuthPassword(serverData.authPassword);
      // bearer token: API returns authToken, which maps to the bearer token UI field
      if (serverData.authToken) setBearerToken(serverData.authToken);
      // custom headers: show existing headers (values will be masked by the server).
      // The getFormData() filter skips masked values so unchanged headers are never sent back.
      if (serverData.authHeaders && serverData.authHeaders.length > 0) {
        setCustomHeaders(
          serverData.authHeaders.map((h, i) => ({ id: String(i + 1), key: h.key, value: h.value })),
        );
      } else if (serverData.authHeaderKey) {
        setCustomHeaders([
          { id: "1", key: serverData.authHeaderKey, value: serverData.authHeaderValue || "" },
        ]);
      }
      // query param auth
      if (serverData.authQueryParamKey) setQueryParamName(serverData.authQueryParamKey);
      if (serverData.authQueryParamValueMasked)
        setQueryParamApiKey(serverData.authQueryParamValueMasked);

      // Advanced settings
      if (serverData.passthroughHeaders && Array.isArray(serverData.passthroughHeaders)) {
        setPassthroughHeaders(serverData.passthroughHeaders.join(", "));
      }
      if (serverData.oneTimeAuth !== undefined) setOneTimeAuth(serverData.oneTimeAuth);
      if (serverData.caCertificate) setCaCertificate(serverData.caCertificate);

      // OAuth config — outer key is camelCase (oauthConfig), inner dict keys are snake_case
      if (serverData.oauthConfig) {
        const oauthConfig = serverData.oauthConfig;
        if (oauthConfig.grant_type) setOAuthGrantType(oauthConfig.grant_type);
        if (oauthConfig.client_id) setOAuthClientId(oauthConfig.client_id);
        if (oauthConfig.client_secret) setOAuthClientSecret(oauthConfig.client_secret);
        if (oauthConfig.token_url) setOAuthTokenUrl(oauthConfig.token_url);
        if (oauthConfig.issuer) setOAuthIssuerUrl(oauthConfig.issuer);
        if (oauthConfig.redirect_uri) setOAuthRedirectUri(oauthConfig.redirect_uri);
        if (oauthConfig.authorization_url) setOAuthAuthorizationUrl(oauthConfig.authorization_url);
        if (oauthConfig.scopes) {
          setOAuthScopes(
            Array.isArray(oauthConfig.scopes) ? oauthConfig.scopes.join(" ") : oauthConfig.scopes,
          );
        }
        if (oauthConfig.username) setOAuthUsername(oauthConfig.username);
        if (oauthConfig.password) setOAuthPassword(oauthConfig.password);
        setOAuthStoreTokens(Boolean(oauthConfig.store_tokens));
        setOAuthAutoRefresh(Boolean(oauthConfig.auto_refresh));
      }
    }
  }, [serverData, gatewayId]);

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

    let oauthConfig: z.infer<typeof oauthConfigSchema> | undefined;
    if (authType === "oauth") {
      const scopesArray = oauthScopes ? oauthScopes.split(/\s+/).filter(Boolean) : undefined;
      const base = {
        issuer: oauthIssuerUrl || undefined,
        scopes: scopesArray,
        store_tokens: oauthStoreTokens,
        auto_refresh: oauthAutoRefresh,
      };

      if (oauthGrantType === "client_credentials") {
        oauthConfig = {
          ...base,
          grant_type: "client_credentials",
          client_id: oauthClientId || undefined,
          client_secret: oauthClientSecret || undefined,
          token_url: oauthTokenUrl || undefined,
        };
      } else if (oauthGrantType === "authorization_code") {
        oauthConfig = {
          ...base,
          grant_type: "authorization_code",
          client_id: oauthClientId || undefined,
          client_secret: oauthClientSecret || undefined,
          token_url: oauthTokenUrl || undefined,
          authorization_url: oauthAuthorizationUrl || undefined,
          redirect_uri: oauthRedirectUri || undefined,
        };
      } else if (oauthGrantType === "password") {
        oauthConfig = {
          ...base,
          grant_type: "password",
          client_id: oauthClientId || undefined,
          client_secret: oauthClientSecret || undefined,
          token_url: oauthTokenUrl || undefined,
          username: oauthUsername || undefined,
          password: oauthPassword || undefined,
        };
      }
    }

    return {
      name,
      url,
      description: description || undefined,
      transport,
      passthroughHeaders: headersArray.length > 0 ? headersArray : undefined,
      authType: AUTH_TYPE_TO_API[authType],
      authUsername: authType === "basic" ? authUsername || undefined : undefined,
      authPassword:
        authType === "basic"
          ? authPassword === "*****"
            ? undefined
            : authPassword || undefined
          : undefined,
      authToken:
        authType === "bearer"
          ? bearerToken === "*****"
            ? undefined
            : bearerToken || undefined
          : undefined,
      auth_headers: (() => {
        if (authType !== "custom") return undefined;
        const headers = customHeaders
          .filter((h) => h.key)
          .map((h) => ({ key: h.key, value: h.value }));
        return headers.length > 0 ? headers : undefined;
      })(),
      auth_query_param_key: authType === "query" ? queryParamName || undefined : undefined,
      auth_query_param_value: authType === "query" ? queryParamApiKey || undefined : undefined,
      oneTimeAuth: oneTimeAuth || undefined,
      visibility: (visibility as "public" | "private") || undefined,
      caCertificate: caCertificate || undefined,
      oauth_config: oauthConfig,
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
    bearerToken,
    customHeaders,
    queryParamName,
    queryParamApiKey,
    oneTimeAuth,
    visibility,
    caCertificate,
    oauthGrantType,
    oauthClientId,
    oauthClientSecret,
    oauthTokenUrl,
    oauthIssuerUrl,
    oauthRedirectUri,
    oauthAuthorizationUrl,
    oauthScopes,
    oauthStoreTokens,
    oauthAutoRefresh,
    oauthUsername,
    oauthPassword,
  ]);

  const validateField = useCallback((field: keyof FormErrors, value: string) => {
    try {
      const fieldSchema =
        mcpServerFormObjectSchema.shape[field as keyof typeof mcpServerFormObjectSchema.shape];
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
    setOAuthUsername(initialState.oauthUsername);
    setOAuthPassword(initialState.oauthPassword);
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

          // Reset form after successful submission
          resetForm();
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
    [validateForm, getFormData, createGateway, updateGateway, resetForm, isEditMode, gatewayId],
  );

  const isValid = useMemo(() => {
    if (!name.trim() || !url.trim()) return false;
    try {
      const parsed = new URL(url.trim());
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return false;
    } catch {
      return false;
    }
    if (authType === "oauth" && oauthGrantType === "password") {
      if (!oauthUsername.trim()) return false;
      if (!oauthPassword.trim()) return false;
    }
    return true;
  }, [name, url, authType, oauthGrantType, oauthUsername, oauthPassword]);

  return {
    // State
    fetchError: serverFetchError?.message,
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
    oauthUsername,
    oauthPassword,
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
    setOAuthUsername,
    setOAuthPassword,
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
