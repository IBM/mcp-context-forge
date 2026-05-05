import { AlertTriangle } from "lucide-react";
import { Input } from "@/components/ui/input";

interface QueryParameterAuthProps {
  parameterName: string;
  apiKey: string;
  onParameterNameChange: (value: string) => void;
  onApiKeyChange: (value: string) => void;
}

export function QueryParameterAuth({
  parameterName,
  apiKey,
  onParameterNameChange,
  onApiKeyChange,
}: QueryParameterAuthProps) {
  return (
    <div className="space-y-4">
      {/* Security Warning */}
      <div className="flex items-center gap-3 rounded-md bg-neutral-50 px-3 py-5 dark:bg-neutral-800">
        <AlertTriangle className="h-5 w-5 shrink-0 text-yellow-600 dark:text-yellow-500" />
        <p className="text-sm text-neutral-700 dark:text-neutral-300">
          <span className="font-semibold">Security Warning:</span> API keys in URLs will be visible
          in proxy logs, browser history, and server access logs. Use only when the upstream server
          does not support header-based authentication.
        </p>
      </div>

      {/* Query parameter name */}
      <div className="space-y-1">
        <label
          htmlFor="query-param-name"
          className="inline-flex items-center gap-0.5 text-sm font-medium text-neutral-900 dark:text-neutral-100"
        >
          Query parameter name<span className="text-red-500">*</span>
          <span className="sr-only">(required)</span>
        </label>
        <Input
          id="query-param-name"
          type="text"
          value={parameterName}
          onChange={(e) => onParameterNameChange(e.target.value)}
          placeholder="e.g. api_key..."
          className="rounded-md border-neutral-300 bg-white px-4 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100 dark:placeholder:text-neutral-500"
        />
      </div>

      {/* API key */}
      <div className="space-y-1">
        <label
          htmlFor="query-param-api-key"
          className="inline-flex items-center gap-0.5 text-sm font-medium text-neutral-900 dark:text-neutral-100"
        >
          API key<span className="text-red-500">*</span>
          <span className="sr-only">(required)</span>
        </label>
        <Input
          id="query-param-api-key"
          type="password"
          value={apiKey}
          onChange={(e) => onApiKeyChange(e.target.value)}
          placeholder="e.g. a1b2c3d4e5f6789..."
          className="rounded-md border-neutral-300 bg-white px-4 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100 dark:placeholder:text-neutral-500"
        />
      </div>
    </div>
  );
}
