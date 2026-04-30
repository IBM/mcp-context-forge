import { Info } from "lucide-react";
import { Textarea } from "@/components/ui/textarea";
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

type AuthType = "none" | "basic" | "bearer" | "custom" | "oauth" | "query";

interface AdvancedSettingsProps {
  visibility: string;
  onVisibilityChange: (value: string) => void;
  authType: AuthType;
  onAuthTypeChange: (value: AuthType) => void;
  basicAuthUsername: string;
  basicAuthPassword: string;
  onBasicAuthUsernameChange: (value: string) => void;
  onBasicAuthPasswordChange: (value: string) => void;
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
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={oneTimeAuth}
            onChange={(e) => onOneTimeAuthChange(e.target.checked)}
            className="h-4 w-4 rounded border-neutral-300 dark:border-neutral-700"
          />
          <span className="text-sm font-medium text-neutral-950 dark:text-white">
            One-time authentication
          </span>
          <Info className="h-4 w-4 text-neutral-400 dark:text-neutral-500" />
        </label>
        <p className="pl-6 text-sm text-neutral-600 dark:text-neutral-400">
          {
            "Use credentials once, don't store them. Health checks will be disabled. For reusable credentials, configure passthrough headers."
          }
        </p>
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

// Made with Bob
