import { ChevronDown, CircleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { MCPIcon } from "@/components/icons/MCPIcon";
import { AdvancedSettings } from "@/components/mcp-servers/AdvancedSettings";
import { useRouter } from "@/router";
import { useMCPServerForm, type TransportType } from "@/hooks/useMCPServerForm";

interface MCPServerFormProps {
  isOpen: boolean;
  onToggle: () => void;
  serverId?: string;
  onSuccess?: () => void;
}

export function MCPServerForm({ isOpen, onToggle, serverId, onSuccess }: MCPServerFormProps) {
  const { navigate } = useRouter();
  const {
    fetchError,
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
    errors,
    isValid,
    isSubmitting,
    oauthPending,
    oauthNotification,
    clearOAuthNotification,
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
    handleSubmit,
    bearerToken,
    setBearerToken,
    customHeaders,
    setCustomHeaders,
    oauthClientId,
    setOAuthClientId,
    oauthClientSecret,
    setOAuthClientSecret,
    oauthTokenUrl,
    setOAuthTokenUrl,
    oauthGrantType,
    setOAuthGrantType,
    oauthIssuerUrl,
    setOAuthIssuerUrl,
    oauthRedirectUri,
    setOAuthRedirectUri,
    oauthAuthorizationUrl,
    setOAuthAuthorizationUrl,
    oauthScopes,
    setOAuthScopes,
    oauthStoreTokens,
    setOAuthStoreTokens,
    oauthAutoRefresh,
    setOAuthAutoRefresh,
    oauthUsername,
    setOAuthUsername,
    oauthPassword,
    setOAuthPassword,
    queryParamName,
    setQueryParamName,
    queryParamApiKey,
    setQueryParamApiKey,
  } = useMCPServerForm(serverId);

  const handleCancel = () => {
    onToggle();
  };

  const onSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    handleSubmit(event, () => {
      if (onSuccess) {
        onSuccess();
      } else {
        onToggle();
      }
    });
  };

  if (!isOpen) return null;

  return (
    <>
      <div className="mx-auto mt-6 w-full max-w-3xl rounded-xl border border-neutral-200 bg-inherit p-0 shadow-[0_12px_40px_rgba(15,23,42,0.12)] dark:border-neutral-800">
        <div className="flex flex-col gap-8 p-6 sm:p-8">
          <div className="flex flex-col gap-4">
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-sm bg-orange-500 text-white shadow-sm">
                <MCPIcon className="h-5 w-5" />
              </div>
              <h2 className="text-2xl font-semibold tracking-tight text-neutral-950 dark:text-neutral-50">
                {serverId ? "Edit MCP server" : "Connect MCP server"}
              </h2>
            </div>

            <p className="text-sm leading-6 text-neutral-600 dark:text-neutral-400">
              {
                "Context Forge will discover the server's tools, resources, and prompts. The MCP server should be running and reachable. Or, choose a server from the"
              }{" "}
              <button
                type="button"
                onClick={() => {
                  onToggle();
                  navigate("/app/server-catalog");
                }}
                className="font-medium text-cyan-700 underline decoration-cyan-300 underline-offset-4 transition hover:text-cyan-800 dark:text-cyan-400 dark:decoration-cyan-700 dark:hover:text-cyan-300"
              >
                mcp server catalog
              </button>
              .
            </p>
          </div>

          {fetchError && serverId && (
            <div className="rounded-md border border-red-200 bg-red-50 p-3 dark:border-red-900/50 dark:bg-red-950/50">
              <p className="text-sm text-red-600 dark:text-red-400">
                Failed to load server data: {fetchError}
              </p>
            </div>
          )}

          <form className="space-y-6" onSubmit={onSubmit}>
            <div className="space-y-3">
              <label className="text-sm font-medium text-neutral-950 dark:text-white">
                Server transport type
              </label>
              <div
                role="radiogroup"
                aria-label="Server transport type"
                className="flex gap-2 rounded-md bg-neutral-100 p-1 dark:bg-neutral-800"
              >
                {(["STREAMABLEHTTP", "SSE"] as TransportType[]).map((type) => {
                  const label = type === "STREAMABLEHTTP" ? "Streamable HTTP" : "SSE";
                  return (
                    <div key={type} className="flex-1">
                      <input
                        type="radio"
                        id={`transport-${type}`}
                        name="transport"
                        value={type}
                        checked={transport === type}
                        onChange={(e) => setTransport(e.target.value as TransportType)}
                        className="sr-only peer"
                      />
                      <label
                        htmlFor={`transport-${type}`}
                        className="flex cursor-pointer items-center justify-center rounded-md px-4 py-2 text-sm font-medium text-neutral-500 transition hover:bg-neutral-200 hover:text-neutral-700 peer-checked:bg-neutral-800 peer-checked:text-white peer-focus-visible:ring-2 peer-focus-visible:ring-ring peer-focus-visible:ring-offset-2 dark:text-neutral-400 dark:hover:bg-neutral-900 dark:hover:text-neutral-300 dark:peer-checked:bg-neutral-950 dark:peer-checked:text-white"
                      >
                        {label}
                      </label>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="space-y-1">
              <label
                htmlFor="server-name"
                className="inline-flex items-center gap-0.5 text-sm font-medium text-neutral-900 dark:text-neutral-100"
              >
                Name<span className="text-red-500">*</span>
                <span className="sr-only">(required)</span>
              </label>
              <Input
                id="server-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Add MCP server name..."
                className="rounded-md border-neutral-300 bg-white px-4 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100 dark:placeholder:text-neutral-500"
                aria-invalid={!!errors.name}
                aria-describedby={errors.name ? "name-error" : undefined}
              />
              {errors.name && (
                <p id="name-error" className="text-sm text-red-500">
                  {errors.name}
                </p>
              )}
            </div>

            <div className="space-y-1">
              <label
                htmlFor="server-url"
                className="inline-flex items-center gap-0.5 text-sm font-medium text-neutral-900 dark:text-neutral-100"
              >
                URL<span className="text-red-500">*</span>
                <span className="sr-only">(required)</span>
                <CircleAlert className="h-4 w-4 text-neutral-400 dark:text-neutral-500" />
              </label>
              <Input
                id="server-url"
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                placeholder="Add URL for a running MCP server..."
                className="rounded-md border-neutral-300 bg-white px-4 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100 dark:placeholder:text-neutral-500"
                aria-invalid={!!errors.url}
                aria-describedby={errors.url ? "url-error" : undefined}
              />
              {errors.url && (
                <p id="url-error" className="text-sm text-red-500">
                  {errors.url}
                </p>
              )}
            </div>

            <div className="space-y-1">
              <label htmlFor="server-description" className="sr-only">
                Description
              </label>
              <Textarea
                id="server-description"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="Add an optional description..."
                className="min-h-28 focus-visible:ring-1 focus-visible:ring-offset-0"
                aria-invalid={!!errors.description}
                aria-describedby={errors.description ? "description-error" : undefined}
              />
              {errors.description && (
                <p id="description-error" className="text-sm text-red-500">
                  {errors.description}
                </p>
              )}
            </div>

            <div className="flex flex-col gap-5 pt-2">
              <button
                type="button"
                onClick={() => setAdvancedOpen((current) => !current)}
                className="inline-flex w-full items-center gap-2 rounded-md border border-neutral-200 px-3 py-2 text-sm font-medium text-neutral-600 transition hover:text-neutral-950 dark:border-neutral-800 dark:text-neutral-400 dark:hover:text-neutral-300"
                aria-expanded={advancedOpen}
              >
                <ChevronDown className={`h-4 w-4 transition ${advancedOpen ? "rotate-180" : ""}`} />
                Advanced settings
              </button>

              {advancedOpen && (
                <AdvancedSettings
                  visibility={visibility}
                  onVisibilityChange={setVisibility}
                  authType={authType}
                  onAuthTypeChange={setAuthType}
                  basicAuthUsername={authUsername}
                  basicAuthPassword={authPassword}
                  onBasicAuthUsernameChange={setAuthUsername}
                  onBasicAuthPasswordChange={setAuthPassword}
                  bearerToken={bearerToken}
                  onBearerTokenChange={setBearerToken}
                  customHeaders={customHeaders}
                  onCustomHeadersChange={setCustomHeaders}
                  oauthClientId={oauthClientId}
                  oauthClientSecret={oauthClientSecret}
                  oauthTokenUrl={oauthTokenUrl}
                  oauthGrantType={oauthGrantType}
                  oauthIssuerUrl={oauthIssuerUrl}
                  oauthRedirectUri={oauthRedirectUri}
                  oauthAuthorizationUrl={oauthAuthorizationUrl}
                  oauthScopes={oauthScopes}
                  oauthStoreTokens={oauthStoreTokens}
                  oauthAutoRefresh={oauthAutoRefresh}
                  oauthUsername={oauthUsername}
                  oauthPassword={oauthPassword}
                  onOAuthClientIdChange={setOAuthClientId}
                  onOAuthClientSecretChange={setOAuthClientSecret}
                  onOAuthTokenUrlChange={setOAuthTokenUrl}
                  onOAuthGrantTypeChange={setOAuthGrantType}
                  onOAuthIssuerUrlChange={setOAuthIssuerUrl}
                  onOAuthRedirectUriChange={setOAuthRedirectUri}
                  onOAuthAuthorizationUrlChange={setOAuthAuthorizationUrl}
                  onOAuthScopesChange={setOAuthScopes}
                  onOAuthStoreTokensChange={setOAuthStoreTokens}
                  onOAuthAutoRefreshChange={setOAuthAutoRefresh}
                  onOAuthUsernameChange={setOAuthUsername}
                  onOAuthPasswordChange={setOAuthPassword}
                  queryParamName={queryParamName}
                  queryParamApiKey={queryParamApiKey}
                  onQueryParamNameChange={setQueryParamName}
                  onQueryParamApiKeyChange={setQueryParamApiKey}
                  oneTimeAuth={oneTimeAuth}
                  onOneTimeAuthChange={setOneTimeAuth}
                  passthroughHeaders={passthroughHeaders}
                  onPassthroughHeadersChange={setPassthroughHeaders}
                  onCACertificateFilesSelected={(files) => {
                    console.log("Selected CA certificate files:", files);
                  }}
                  oauthErrors={{
                    username: errors.oauthUsername,
                    password: errors.oauthPassword, // pragma: allowlist secret
                  }}
                />
              )}

              {errors.submit && (
                <div className="rounded-md border border-red-200 bg-red-50 p-3 dark:border-red-900/50 dark:bg-red-950/50">
                  <p className="text-sm text-red-600 dark:text-red-400">{errors.submit}</p>
                </div>
              )}

              {oauthPending && (
                <div
                  role="status"
                  className="rounded-md border border-blue-200 bg-blue-50 p-3 dark:border-blue-900/50 dark:bg-blue-950/50"
                >
                  <p className="text-sm text-blue-700 dark:text-blue-300">
                    Waiting for OAuth authorization in the popup window…
                  </p>
                </div>
              )}

              {oauthNotification && (
                <div
                  role={oauthNotification.type === "error" ? "alert" : "status"}
                  className={`flex items-start justify-between rounded-md border p-3 ${
                    oauthNotification.type === "success"
                      ? "border-green-200 bg-green-50 dark:border-green-900/50 dark:bg-green-950/50"
                      : "border-red-200 bg-red-50 dark:border-red-900/50 dark:bg-red-950/50"
                  }`}
                >
                  <p
                    className={`text-sm ${
                      oauthNotification.type === "success"
                        ? "text-green-700 dark:text-green-300"
                        : "text-red-600 dark:text-red-400"
                    }`}
                  >
                    {oauthNotification.message}
                  </p>
                  <button
                    type="button"
                    onClick={clearOAuthNotification}
                    aria-label="Dismiss notification"
                    className="ml-2 shrink-0 p-1 opacity-60 hover:opacity-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500"
                  >
                    ×
                  </button>
                </div>
              )}

              <div className="flex items-center justify-end gap-3 pt-6">
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => handleCancel()}
                  className="h-10 rounded-md px-3 text-sm font-medium text-neutral-700 hover:bg-neutral-100 hover:text-neutral-950 dark:text-neutral-300 dark:hover:bg-neutral-800 dark:hover:text-neutral-100"
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  disabled={!isValid || isSubmitting || oauthPending}
                  className="h-10 rounded-md bg-neutral-950 px-4 text-sm font-medium text-white hover:enabled:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-950 dark:hover:enabled:bg-neutral-200"
                >
                  {isSubmitting
                    ? "Connecting..."
                    : oauthPending
                      ? "Waiting for OAuth…"
                      : "Connect server"}
                </Button>
              </div>
            </div>
          </form>
        </div>
      </div>
    </>
  );
}

// Made with Bob
