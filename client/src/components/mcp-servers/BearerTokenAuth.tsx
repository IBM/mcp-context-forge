import { Input } from "@/components/ui/input";

interface BearerTokenAuthProps {
  token: string;
  onTokenChange: (value: string) => void;
}

export function BearerTokenAuth({ token, onTokenChange }: BearerTokenAuthProps) {
  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <label
          htmlFor="bearer-token"
          className="text-sm font-medium text-neutral-900 dark:text-neutral-100"
        >
          Bearer token
        </label>
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          Add the API key or token issued by the server.
        </p>
      </div>

      <Input
        id="bearer-token"
        type="password"
        value={token}
        onChange={(e) => onTokenChange(e.target.value)}
        placeholder="Paste bearer token..."
        className="rounded-md border-neutral-300 bg-white px-4 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100 dark:placeholder:text-neutral-500"
      />
    </div>
  );
}
