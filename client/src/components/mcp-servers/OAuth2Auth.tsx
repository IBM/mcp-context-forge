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
  grantType: string;
  issuerUrl: string;
  redirectUri: string;
  clientId: string;
  clientSecret: string;
  tokenUrl: string;
  authorizationUrl: string;
  scopes: string;
  storeTokens: boolean;
  autoRefresh: boolean;
  username: string;
  password: string;
  onGrantTypeChange: (value: string) => void;
  onIssuerUrlChange: (value: string) => void;
  onRedirectUriChange: (value: string) => void;
  onClientIdChange: (value: string) => void;
  onClientSecretChange: (value: string) => void;
  onTokenUrlChange: (value: string) => void;
  onAuthorizationUrlChange: (value: string) => void;
  onScopesChange: (value: string) => void;
  onStoreTokensChange: (checked: boolean) => void;
  onAutoRefreshChange: (checked: boolean) => void;
  onUsernameChange: (value: string) => void;
  onPasswordChange: (value: string) => void;
  errors?: { username?: string; password?: string };
}

export function OAuth2Auth({
  grantType,
  issuerUrl,
  redirectUri,
  clientId,
  clientSecret,
  tokenUrl,
  authorizationUrl,
  scopes,
  storeTokens,
  autoRefresh,
  username,
  password,
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
  onUsernameChange,
  onPasswordChange,
  errors,
}: OAuth2AuthProps) {
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
        <Select value={grantType} onValueChange={onGrantTypeChange}>
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
          value={issuerUrl}
          onChange={(e) => onIssuerUrlChange(e.target.value)}
          placeholder="e.g. https://auth.example.com"
          className="rounded-md border-neutral-300 bg-white px-4 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100 dark:placeholder:text-neutral-500"
        />
        <p className="text-xs text-neutral-600 dark:text-neutral-500">
          {
            "Authorization server's base URL for endpoint discovery and Dynamic Client Registration (DCR)"
          }
        </p>
      </div>

      {grantType === "authorization_code" && (
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
            value={redirectUri}
            onChange={(e) => onRedirectUriChange(e.target.value)}
            placeholder="e.g. https://gateway.example.com/oauth/callback"
            className="rounded-md border-neutral-300 bg-white px-4 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100 dark:placeholder:text-neutral-500"
          />
          <p className="text-xs text-neutral-600 dark:text-neutral-500">
            {"Copy URI into the OAuth application's allowed redirect URI"}
          </p>
        </div>
      )}

      {grantType === "password" && (
        <>
          <div className="space-y-1">
            <label
              htmlFor="oauth-username"
              className="inline-flex items-center gap-0.5 text-sm font-medium text-neutral-900 dark:text-neutral-100"
            >
              Username<span className="text-red-500">*</span>
              <span className="sr-only">(required)</span>
            </label>
            <Input
              id="oauth-username"
              type="text"
              value={username}
              onChange={(e) => onUsernameChange(e.target.value)}
              placeholder="e.g. service-account"
              aria-invalid={!!errors?.username}
              aria-describedby={errors?.username ? "oauth-username-error" : undefined}
              className="rounded-md border-neutral-300 bg-white px-4 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100 dark:placeholder:text-neutral-500"
            />
            {errors?.username && (
              <p id="oauth-username-error" className="text-sm text-red-500">
                {errors.username}
              </p>
            )}
          </div>
          <div className="space-y-1">
            <label
              htmlFor="oauth-password"
              className="inline-flex items-center gap-0.5 text-sm font-medium text-neutral-900 dark:text-neutral-100"
            >
              Password<span className="text-red-500">*</span>
              <span className="sr-only">(required)</span>
            </label>
            <Input
              id="oauth-password"
              type="password"
              value={password}
              onChange={(e) => onPasswordChange(e.target.value)}
              placeholder="••••••••"
              aria-invalid={!!errors?.password}
              aria-describedby={errors?.password ? "oauth-password-error" : undefined}
              className="rounded-md border-neutral-300 bg-white px-4 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100 dark:placeholder:text-neutral-500"
            />
            {errors?.password && (
              <p id="oauth-password-error" className="text-sm text-red-500">
                {errors.password}
              </p>
            )}
          </div>
        </>
      )}

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

      {grantType === "authorization_code" && (
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
            value={authorizationUrl}
            onChange={(e) => onAuthorizationUrlChange(e.target.value)}
            placeholder="e.g. https://oauth.example.com/authorize"
            className="rounded-md border-neutral-300 bg-white px-4 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100 dark:placeholder:text-neutral-500"
          />
          <p className="text-xs text-neutral-600 dark:text-neutral-500">
            Where users are redirected to log in and grant access
          </p>
        </div>
      )}

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
          value={scopes}
          onChange={(e) => onScopesChange(e.target.value)}
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
              checked={storeTokens}
              onCheckedChange={(checked) => onStoreTokensChange(checked === true)}
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
              checked={autoRefresh}
              onCheckedChange={(checked) => onAutoRefreshChange(checked === true)}
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
