import { Info } from "lucide-react";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { CACertificateUpload } from "@/components/mcp-servers/CACertificateUpload";
import { NoneAuth } from "@/components/mcp-servers/NoneAuth";
import { BasicAuth } from "@/components/mcp-servers/BasicAuth";
import { BearerTokenAuth } from "@/components/mcp-servers/BearerTokenAuth";
import { CustomHeadersAuth } from "@/components/mcp-servers/CustomHeadersAuth";
import { OAuth2Auth } from "@/components/mcp-servers/OAuth2Auth";
import { QueryParameterAuth } from "@/components/mcp-servers/QueryParameterAuth";

type AuthType = "none" | "basic" | "bearer" | "custom" | "oauth" | "query";

export interface CustomHeader {
  key: string;
  value: string;
}

interface AdvancedSettingsProps {
  visibility: string;
  onVisibilityChange: (value: string) => void;
  authType: AuthType;
  onAuthTypeChange: (value: AuthType) => void;
  basicAuthUsername: string;
  basicAuthPassword: string;
  onBasicAuthUsernameChange: (value: string) => void;
  onBasicAuthPasswordChange: (value: string) => void;
  bearerToken: string;
  onBearerTokenChange: (value: string) => void;
  customHeaders: CustomHeader[];
  onCustomHeadersChange: (headers: CustomHeader[]) => void;
  oauthClientId: string;
  oauthClientSecret: string;
  oauthTokenUrl: string;
  onOAuthClientIdChange: (value: string) => void;
  onOAuthClientSecretChange: (value: string) => void;
  onOAuthTokenUrlChange: (value: string) => void;
  queryParamName: string;
  queryParamApiKey: string;
  onQueryParamNameChange: (value: string) => void;
  onQueryParamApiKeyChange: (value: string) => void;
  oneTimeAuth: boolean;
  onOneTimeAuthChange: (checked: boolean) => void;
  passthroughHeaders: string;
  onPassthroughHeadersChange: (value: string) => void;
  onCACertificateFilesSelected: (files: File[]) => void;
}

export function AdvancedSettings({
  visibility,
  onVisibilityChange,
  authType,
  onAuthTypeChange,
  basicAuthUsername,
  basicAuthPassword,
  onBasicAuthUsernameChange,
  onBasicAuthPasswordChange,
  bearerToken,
  onBearerTokenChange,
  customHeaders,
  onCustomHeadersChange,
  oauthClientId,
  oauthClientSecret,
  oauthTokenUrl,
  onOAuthClientIdChange,
  onOAuthClientSecretChange,
  onOAuthTokenUrlChange,
  queryParamName,
  queryParamApiKey,
  onQueryParamNameChange,
  onQueryParamApiKeyChange,
  oneTimeAuth,
  onOneTimeAuthChange,
  passthroughHeaders,
  onPassthroughHeadersChange,
  onCACertificateFilesSelected,
}: AdvancedSettingsProps) {
  const renderAuthContent = () => {
    switch (authType) {
      case "none":
        return <NoneAuth />;
      case "basic":
        return (
          <BasicAuth
            username={basicAuthUsername}
            password={basicAuthPassword}
            onUsernameChange={onBasicAuthUsernameChange}
            onPasswordChange={onBasicAuthPasswordChange}
          />
        );
      case "bearer":
        return <BearerTokenAuth token={bearerToken} onTokenChange={onBearerTokenChange} />;
      case "custom":
        return (
          <CustomHeadersAuth headers={customHeaders} onHeadersChange={onCustomHeadersChange} />
        );
      case "oauth":
        return (
          <OAuth2Auth
            clientId={oauthClientId}
            clientSecret={oauthClientSecret}
            tokenUrl={oauthTokenUrl}
            onClientIdChange={onOAuthClientIdChange}
            onClientSecretChange={onOAuthClientSecretChange}
            onTokenUrlChange={onOAuthTokenUrlChange}
          />
        );
      case "query":
        return (
          <QueryParameterAuth
            parameterName={queryParamName}
            apiKey={queryParamApiKey}
            onParameterNameChange={onQueryParamNameChange}
            onApiKeyChange={onQueryParamApiKeyChange}
          />
        );
      default:
        return null;
    }
  };

  return (
    <div className="space-y-6 py-4">
      {/* Visibility */}
      <div className="space-y-3">
        <label
          htmlFor="visibility"
          className="text-sm font-medium text-neutral-950 dark:text-white"
        >
          Visibility
        </label>
        <Select value={visibility} onValueChange={onVisibilityChange}>
          <SelectTrigger className="h-10 w-full border-neutral-300 bg-white dark:border-neutral-700 dark:bg-neutral-950">
            <SelectValue placeholder="Select visibility" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="public">Public</SelectItem>
            <SelectItem value="private">Private</SelectItem>
            <SelectItem value="team">Team</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Authentication type */}
      <div className="space-y-3">
        <label className="text-sm font-medium text-neutral-950 dark:text-white">
          Authentication type
        </label>
        <div
          role="radiogroup"
          aria-label="Authentication type"
          className="flex w-full flex-nowrap gap-1 rounded-md bg-neutral-100 p-1 dark:bg-neutral-800"
        >
          {(["none", "basic", "bearer", "custom", "oauth", "query"] as AuthType[]).map((type) => {
            const label =
              type === "none"
                ? "None"
                : type === "basic"
                  ? "Basic"
                  : type === "bearer"
                    ? "Bearer token"
                    : type === "custom"
                      ? "Custom headers"
                      : type === "oauth"
                        ? "OAuth 2.0"
                        : "Query parameter";
            const isLongerLabel = type === "custom" || type === "query";
            return (
              <div key={type} className={isLongerLabel ? "flex-[1.3] min-w-0" : "flex-1 min-w-0"}>
                <input
                  type="radio"
                  id={`auth-${type}`}
                  name="auth-type"
                  value={type}
                  checked={authType === type}
                  onChange={(e) => onAuthTypeChange(e.target.value as AuthType)}
                  className="sr-only peer"
                />
                <label
                  htmlFor={`auth-${type}`}
                  className="flex cursor-pointer items-center justify-center whitespace-nowrap rounded-md px-3 py-2 text-center text-sm font-medium text-neutral-500 transition hover:bg-neutral-200 hover:text-neutral-700 peer-checked:bg-neutral-800 peer-checked:text-white peer-checked:px-4 peer-focus-visible:ring-2 peer-focus-visible:ring-ring peer-focus-visible:ring-offset-2 dark:text-neutral-400 dark:hover:bg-neutral-900 dark:hover:text-neutral-300 dark:peer-checked:bg-neutral-950 dark:peer-checked:text-white"
                >
                  {label}
                </label>
              </div>
            );
          })}
        </div>
      </div>

      {/* Auth-specific content */}
      {renderAuthContent()}

      {/* One-time authentication */}
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <label
            htmlFor="one-time-auth"
            className="text-sm font-medium text-neutral-950 dark:text-white"
          >
            One-time authentication
          </label>
          <Info className="h-4 w-4 text-neutral-400 dark:text-neutral-500" />
        </div>
        <div className="flex items-center gap-3">
          <Switch id="one-time-auth" checked={oneTimeAuth} onCheckedChange={onOneTimeAuthChange} />
          <p className="text-sm text-neutral-600 dark:text-neutral-400">
            {"Use credentials once, don't store them. Health checks will be disabled."}
          </p>
        </div>
      </div>

      {/* Passthrough headers */}
      <div className="space-y-2">
        <label
          htmlFor="passthrough-headers"
          className="text-sm font-medium text-neutral-950 dark:text-white"
        >
          Passthrough headers
        </label>
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          Add comma-separate headers to forward from client requests. Leave empty to use global
          defaults.
        </p>
        <Textarea
          id="passthrough-headers"
          value={passthroughHeaders}
          onChange={(e) => onPassthroughHeadersChange(e.target.value)}
          placeholder="e.g. Authorization, X-Tenant-Id, X-Trace-Id..."
          className="min-h-20 focus-visible:ring-1 focus-visible:ring-offset-0"
        />
      </div>

      {/* CA certificate */}
      <CACertificateUpload onFilesSelected={onCACertificateFilesSelected} />
    </div>
  );
}
