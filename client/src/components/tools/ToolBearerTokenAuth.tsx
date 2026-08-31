import { Input } from "@/components/ui/input";

interface ToolBearerTokenAuthProps {
  token: string;
  onTokenChange: (value: string) => void;
}

export function ToolBearerTokenAuth({ token, onTokenChange }: ToolBearerTokenAuthProps) {
  return (
    <div className="space-y-4">
      <label
        htmlFor="bearer-token"
        className="inline-flex items-center gap-0.5 text-sm font-medium text-neutral-900 dark:text-neutral-100"
      >
        Token<span className="text-red-500">*</span>
        <span className="sr-only">(required)</span>
      </label>

      <Input
        id="bearer-token"
        type="password"
        value={token}
        onChange={(e) => onTokenChange(e.target.value)}
        placeholder="Paste bearer token..."
        className="rounded-md border-neutral-300 px-4 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:text-neutral-100 dark:placeholder:text-neutral-500"
      />
    </div>
  );
}
