import { useEffect } from "react";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { BasicAuth } from "@/components/mcp-servers/BasicAuth";
import { ToolBearerTokenAuth } from "@/components/tools/ToolBearerTokenAuth";
import { CustomHeadersAuth, type CustomHeader } from "@/components/mcp-servers/CustomHeadersAuth";
import { OAuth2Auth } from "@/components/mcp-servers/OAuth2Auth";
import { useAuthContext } from "@/auth/AuthContext";
import type { Visibility } from "@/types/server";

export type { CustomHeader };

type AuthType = "none" | "basic" | "bearer" | "custom" | "oauth";

interface ToolAdvancedSettingsProps {
  visibility: Visibility;
  onVisibilityChange: (value: Visibility) => void;
  teamId: string;
  onTeamIdChange: (value: string) => void;
  authType: AuthType;
  onAuthTypeChange: (value: AuthType) => void;
  basicAuthUsername: string;
  basicAuthPassword: string; // pragma: allowlist secret
  onBasicAuthUsernameChange: (value: string) => void;
  onBasicAuthPasswordChange: (value: string) => void;
  bearerToken: string;
  onBearerTokenChange: (value: string) => void;
  customHeaders: CustomHeader[];
  onCustomHeadersChange: (headers: CustomHeader[]) => void;
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
  onOAuthClientIdChange: (value: string) => void;
  onOAuthClientSecretChange: (value: string) => void;
  onOAuthTokenUrlChange: (value: string) => void;
  onOAuthGrantTypeChange: (value: string) => void;
  onOAuthIssuerUrlChange: (value: string) => void;
  onOAuthRedirectUriChange: (value: string) => void;
  onOAuthAuthorizationUrlChange: (value: string) => void;
  onOAuthScopesChange: (value: string) => void;
  onOAuthStoreTokensChange: (checked: boolean) => void;
  onOAuthAutoRefreshChange: (checked: boolean) => void;
  onOAuthUsernameChange: (value: string) => void;
  onOAuthPasswordChange: (value: string) => void;
  responseFilter: string;
  onResponseFilterChange: (value: string) => void;
  tags: string;
  onTagsChange: (value: string) => void;
  description: string;
  onDescriptionChange: (value: string) => void;
  oauthErrors?: { username?: string; password?: string };
}

export function ToolAdvancedSettings({
  visibility,
  onVisibilityChange,
  teamId,
  onTeamIdChange,
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
  oauthGrantType,
  oauthIssuerUrl,
  oauthRedirectUri,
  oauthAuthorizationUrl,
  oauthScopes,
  oauthStoreTokens,
  oauthAutoRefresh,
  oauthUsername,
  oauthPassword,
  onOAuthClientIdChange,
  onOAuthClientSecretChange,
  onOAuthTokenUrlChange,
  onOAuthGrantTypeChange,
  onOAuthIssuerUrlChange,
  onOAuthRedirectUriChange,
  onOAuthAuthorizationUrlChange,
  onOAuthScopesChange,
  onOAuthStoreTokensChange,
  onOAuthAutoRefreshChange,
  onOAuthUsernameChange,
  onOAuthPasswordChange,
  responseFilter,
  onResponseFilterChange,
  tags,
  onTagsChange,
  description,
  onDescriptionChange,
  oauthErrors,
}: ToolAdvancedSettingsProps) {
  const { selectedTeamId } = useAuthContext();

  useEffect(() => {
    if (visibility === "team") {
      if (selectedTeamId && !teamId) {
        onTeamIdChange(selectedTeamId);
      }
    } else if (teamId) {
      onTeamIdChange("");
    }
  }, [visibility, selectedTeamId, teamId, onTeamIdChange]);
  const renderAuthContent = () => {
    switch (authType) {
      case "none":
        return null;
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
        return <ToolBearerTokenAuth token={bearerToken} onTokenChange={onBearerTokenChange} />;
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
            grantType={oauthGrantType}
            issuerUrl={oauthIssuerUrl}
            redirectUri={oauthRedirectUri}
            authorizationUrl={oauthAuthorizationUrl}
            scopes={oauthScopes}
            storeTokens={oauthStoreTokens}
            autoRefresh={oauthAutoRefresh}
            username={oauthUsername}
            password={oauthPassword}
            onClientIdChange={onOAuthClientIdChange}
            onClientSecretChange={onOAuthClientSecretChange}
            onTokenUrlChange={onOAuthTokenUrlChange}
            onGrantTypeChange={onOAuthGrantTypeChange}
            onIssuerUrlChange={onOAuthIssuerUrlChange}
            onRedirectUriChange={onOAuthRedirectUriChange}
            onAuthorizationUrlChange={onOAuthAuthorizationUrlChange}
            onScopesChange={onOAuthScopesChange}
            onStoreTokensChange={onOAuthStoreTokensChange}
            onAutoRefreshChange={onOAuthAutoRefreshChange}
            onUsernameChange={onOAuthUsernameChange}
            onPasswordChange={onOAuthPasswordChange}
            errors={oauthErrors}
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
          <SelectTrigger
            id="visibility"
            className="h-10 w-full border-neutral-300 bg-white dark:border-neutral-700 dark:bg-neutral-950"
          >
            <SelectValue placeholder="Select visibility" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="public">Public</SelectItem>
            <SelectItem value="private">Private</SelectItem>
            <SelectItem value="team">Team</SelectItem>
          </SelectContent>
        </Select>
        {visibility === "team" && (
          <p className="text-sm text-neutral-600 dark:text-neutral-400">
            {selectedTeamId
              ? "This tool will be scoped to your currently selected team"
              : "Please select a team using the team switcher in the sidebar"}
          </p>
        )}
      </div>

      {/* Authentication type */}
      <div className="space-y-3">
        <label
          id="auth-type-label"
          className="text-sm font-medium text-neutral-950 dark:text-white"
        >
          Authentication type
        </label>
        <div
          role="radiogroup"
          aria-labelledby="auth-type-label"
          className="flex w-full flex-nowrap gap-1 rounded-md bg-neutral-100 p-1 dark:bg-neutral-800"
        >
          {(["none", "basic", "bearer", "custom", "oauth"] as AuthType[]).map((type) => {
            const label =
              type === "none"
                ? "None"
                : type === "basic"
                  ? "Basic"
                  : type === "bearer"
                    ? "Bearer token"
                    : type === "custom"
                      ? "Custom headers"
                      : "OAuth 2.0";
            const isLongerLabel = type === "custom";
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
                  className="flex cursor-pointer items-center justify-center whitespace-nowrap rounded-md px-3 py-1 text-center text-sm font-medium text-neutral-500 transition hover:bg-neutral-200 hover:text-neutral-700 peer-checked:bg-neutral-800 peer-checked:text-white peer-checked:px-4 peer-focus-visible:ring-2 peer-focus-visible:ring-ring peer-focus-visible:ring-offset-2 dark:text-neutral-400 dark:hover:bg-neutral-900 dark:hover:text-neutral-300 dark:peer-checked:bg-neutral-950 dark:peer-checked:text-white"
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

      {/* Response filter (jq) */}
      <div className="space-y-2">
        <label
          htmlFor="response-filter"
          className="text-sm font-medium text-neutral-950 dark:text-white"
        >
          Response filter (jq)
        </label>
        <Input
          id="response-filter"
          value={responseFilter}
          onChange={(e) => onResponseFilterChange(e.target.value)}
          placeholder="Optional jq expression applied to the upstream response..."
          className="rounded-md border-neutral-300 bg-white px-4 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100 dark:placeholder:text-neutral-500"
        />
      </div>

      {/* Tags */}
      <div className="space-y-2">
        <label htmlFor="tags" className="text-sm font-medium text-neutral-950 dark:text-white">
          Tags
        </label>
        <Input
          id="tags"
          value={tags}
          onChange={(e) => onTagsChange(e.target.value)}
          placeholder="Add optional tags separated with commas"
          className="rounded-md border-neutral-300 bg-white px-4 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100 dark:placeholder:text-neutral-500"
        />
      </div>

      {/* Description */}
      <div className="space-y-2">
        <label
          htmlFor="advanced-description"
          className="text-sm font-medium text-neutral-950 dark:text-white"
        >
          Description
        </label>
        <Textarea
          id="advanced-description"
          value={description}
          onChange={(e) => onDescriptionChange(e.target.value)}
          placeholder="Add an optional description..."
          className="min-h-20 focus-visible:ring-1 focus-visible:ring-offset-0"
        />
      </div>
    </div>
  );
}
