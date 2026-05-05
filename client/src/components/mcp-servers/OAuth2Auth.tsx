import { useState } from "react";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface OAuth2AuthProps {
  grantType?: string;
  issuerUrl?: string;
  redirectUri?: string;
  clientId: string;
  clientSecret: string;
  tokenUrl: string;
  authorizationUrl?: string;
  scopes?: string;
  storeTokens?: boolean;
  autoRefresh?: boolean;
  onGrantTypeChange?: (value: string) => void;
  onIssuerUrlChange?: (value: string) => void;
  onRedirectUriChange?: (value: string) => void;
  onClientIdChange: (value: string) => void;
  onClientSecretChange: (value: string) => void;
  onTokenUrlChange: (value: string) => void;
  onAuthorizationUrlChange?: (value: string) => void;
  onScopesChange?: (value: string) => void;
  onStoreTokensChange?: (checked: boolean) => void;
  onAutoRefreshChange?: (checked: boolean) => void;
}

export function OAuth2Auth({
  grantType = "client_credentials",
  issuerUrl = "",
  redirectUri = "",
  clientId,
  clientSecret,
  tokenUrl,
  authorizationUrl = "",
  scopes = "",
  storeTokens = false,
  autoRefresh = false,
  onGrantTypeChange,
  onIssuerUrlChange,
  onRedirectUriChange,
  onClientIdChange,
  onClientSecretChange,
  onTokenUrlChange,
  onAuthorizationUrlChange,
  onScopesChange,
  onStoreTokensChange,
  onAutoRefreshChange,
}: OAuth2AuthProps) {
  // Internal state for optional fields when parent doesn't control them
  const [localGrantType, setLocalGrantType] = useState(grantType);
  const [localIssuerUrl, setLocalIssuerUrl] = useState(issuerUrl);
  const [localRedirectUri, setLocalRedirectUri] = useState(redirectUri);
  const [localAuthorizationUrl, setLocalAuthorizationUrl] = useState(authorizationUrl);
  const [localScopes, setLocalScopes] = useState(scopes);
  const [localStoreTokens, setLocalStoreTokens] = useState(storeTokens);
  const [localAutoRefresh, setLocalAutoRefresh] = useState(autoRefresh);

  // Use parent-controlled values if handlers are provided, otherwise use local state
  const currentGrantType = onGrantTypeChange ? grantType : localGrantType;
  const currentIssuerUrl = onIssuerUrlChange ? issuerUrl : localIssuerUrl;
  const currentRedirectUri = onRedirectUriChange ? redirectUri : localRedirectUri;
  const currentAuthorizationUrl = onAuthorizationUrlChange
    ? authorizationUrl
    : localAuthorizationUrl;
  const currentScopes = onScopesChange ? scopes : localScopes;
  const currentStoreTokens = onStoreTokensChange ? storeTokens : localStoreTokens;
  const currentAutoRefresh = onAutoRefreshChange ? autoRefresh : localAutoRefresh;
  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <label
          htmlFor="oauth-grant-type"
          className="inline-flex items-center gap-0.5 text-sm font-medium text-neutral-900 dark:text-neutral-100"
        >
          Grant type<span className="text-red-500">*</span>
          <span className="sr-only">(required)</span>
        </label>
        <Select
          value={currentGrantType}
          onValueChange={(value) => {
            if (onGrantTypeChange) {
              onGrantTypeChange(value);
            } else {
              setLocalGrantType(value);
            }
          }}
        >
          <SelectTrigger
            id="oauth-grant-type"
            className="h-10 w-full border-neutral-300 bg-white dark:border-neutral-700 dark:bg-neutral-950"
          >
            <SelectValue placeholder="Select grant type" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="authorization_code">Authorization code (user login)</SelectItem>
            <SelectItem value="client_credentials">
              Client credentials (machine to machine)
            </SelectItem>
            <SelectItem value="password">Resource owner password (legacy)</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-1">
        <label
          htmlFor="oauth-issuer-url"
          className="inline-flex items-center gap-0.5 text-sm font-medium text-neutral-900 dark:text-neutral-100"
        >
          Issuer URL<span className="text-red-500">*</span>
          <span className="sr-only">(required)</span>
        </label>
        <Input
          id="oauth-issuer-url"
          type="text"
          value={currentIssuerUrl}
          onChange={(e) => {
            const value = e.target.value;
            if (onIssuerUrlChange) {
              onIssuerUrlChange(value);
            } else {
              setLocalIssuerUrl(value);
            }
          }}
          placeholder="e.g. https://auth.example.com"
          className="rounded-md border-neutral-300 bg-white px-4 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100 dark:placeholder:text-neutral-500"
        />
        <p className="text-xs text-neutral-600 dark:text-neutral-500">
          {
            "Authorization server's base URL for endpoint discovery and Dynamic Client Registration (DCR)"
          }
        </p>
      </div>

      <div className="space-y-1">
        <label
          htmlFor="oauth-redirect-uri"
          className="inline-flex items-center gap-0.5 text-sm font-medium text-neutral-900 dark:text-neutral-100"
        >
          Redirect URI<span className="text-red-500">*</span>
          <span className="sr-only">(required)</span>
        </label>
        <Input
          id="oauth-redirect-uri"
          type="text"
          value={currentRedirectUri}
          onChange={(e) => {
            const value = e.target.value;
            if (onRedirectUriChange) {
              onRedirectUriChange(value);
            } else {
              setLocalRedirectUri(value);
            }
          }}
          placeholder="e.g. https://gateway.example.com/oauth/callback"
          className="rounded-md border-neutral-300 bg-white px-4 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100 dark:placeholder:text-neutral-500"
        />
        <p className="text-xs text-neutral-600 dark:text-neutral-500">
          {"Copy URI into the OAuth application's allowed redirect URI"}
        </p>
      </div>

      <div className="space-y-1">
        <label
          htmlFor="oauth-client-id"
          className="text-sm font-medium text-neutral-900 dark:text-neutral-100"
        >
          Client ID
        </label>
        <Input
          id="oauth-client-id"
          type="text"
          value={clientId}
          onChange={(e) => onClientIdChange(e.target.value)}
          placeholder="e.g. 8f3a2c1d-4b5e-4f6a-9c8d-1e2f3a4b5c6"
          className="rounded-md border-neutral-300 bg-white px-4 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100 dark:placeholder:text-neutral-500"
        />
        <p className="text-xs text-neutral-600 dark:text-neutral-500">
          Not required for servers that support Dynamic Client Registration (DCR)
        </p>
      </div>

      <div className="space-y-1">
        <label
          htmlFor="oauth-client-secret"
          className="text-sm font-medium text-neutral-900 dark:text-neutral-100"
        >
          Client Secret
        </label>
        <Input
          id="oauth-client-secret"
          type="password"
          value={clientSecret}
          onChange={(e) => onClientSecretChange(e.target.value)}
          placeholder="e.g. a1b2c3d4e5f6"
          className="rounded-md border-neutral-300 bg-white px-4 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100 dark:placeholder:text-neutral-500"
        />
        <p className="text-xs text-neutral-600 dark:text-neutral-500">
          Not required for servers that support Dynamic Client Registration (DCR)
        </p>
      </div>

      <div className="space-y-1">
        <label
          htmlFor="oauth-token-url"
          className="inline-flex items-center gap-0.5 text-sm font-medium text-neutral-900 dark:text-neutral-100"
        >
          Token URL<span className="text-red-500">*</span>
          <span className="sr-only">(required)</span>
        </label>
        <Input
          id="oauth-token-url"
          type="text"
          value={tokenUrl}
          onChange={(e) => onTokenUrlChange(e.target.value)}
          placeholder="e.g. https://oauth.example.com/token"
          className="rounded-md border-neutral-300 bg-white px-4 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100 dark:placeholder:text-neutral-500"
        />
        <p className="text-xs text-neutral-600 dark:text-neutral-500">
          Exchanges authorization codes or credentials for access tokens
        </p>
      </div>

      <div className="space-y-1">
        <label
          htmlFor="oauth-authorization-url"
          className="inline-flex items-center gap-0.5 text-sm font-medium text-neutral-900 dark:text-neutral-100"
        >
          Authorization URL<span className="text-red-500">*</span>
          <span className="sr-only">(required)</span>
        </label>
        <Input
          id="oauth-authorization-url"
          type="text"
          value={currentAuthorizationUrl}
          onChange={(e) => {
            const value = e.target.value;
            if (onAuthorizationUrlChange) {
              onAuthorizationUrlChange(value);
            } else {
              setLocalAuthorizationUrl(value);
            }
          }}
          placeholder="e.g. https://oauth.example.com/authorize"
          className="rounded-md border-neutral-300 bg-white px-4 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100 dark:placeholder:text-neutral-500"
        />
        <p className="text-xs text-neutral-600 dark:text-neutral-500">
          Where users are redirected to log in and grant access
        </p>
      </div>

      <div className="space-y-1">
        <label
          htmlFor="oauth-scopes"
          className="text-sm font-medium text-neutral-900 dark:text-neutral-100"
        >
          Scopes
        </label>
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          Space-separated list of OAuth scopes
        </p>
        <Textarea
          id="oauth-scopes"
          value={currentScopes}
          onChange={(e) => {
            const value = e.target.value;
            if (onScopesChange) {
              onScopesChange(value);
            } else {
              setLocalScopes(value);
            }
          }}
          placeholder="e.g. repo read:user..."
          className="min-h-20 focus-visible:ring-1 focus-visible:ring-offset-0"
        />
      </div>

      <div className="space-y-2">
        <label className="text-sm font-medium text-neutral-900 dark:text-neutral-100">
          Token management
        </label>
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <Checkbox
              id="store-tokens"
              checked={currentStoreTokens}
              onCheckedChange={(checked) => {
                const value = checked === true;
                if (onStoreTokensChange) {
                  onStoreTokensChange(value);
                } else {
                  setLocalStoreTokens(value);
                }
              }}
            />
            <label
              htmlFor="store-tokens"
              className="text-sm text-neutral-900 dark:text-neutral-100 cursor-pointer"
            >
              Store access tokens for reuse
            </label>
          </div>
          <div className="flex items-center gap-2">
            <Checkbox
              id="auto-refresh"
              checked={currentAutoRefresh}
              onCheckedChange={(checked) => {
                const value = checked === true;
                if (onAutoRefreshChange) {
                  onAutoRefreshChange(value);
                } else {
                  setLocalAutoRefresh(value);
                }
              }}
            />
            <label
              htmlFor="auto-refresh"
              className="text-sm text-neutral-900 dark:text-neutral-100 cursor-pointer"
            >
              Automatically refresh expired tokens
            </label>
          </div>
        </div>
      </div>
    </div>
  );
}
