import { Input } from "@/components/ui/input";

interface BasicAuthProps {
  username: string;
  password: string; // pragma: allowlist secret
  onUsernameChange: (value: string) => void;
  onPasswordChange: (value: string) => void;
}

export function BasicAuth({
  username,
  password,
  onUsernameChange,
  onPasswordChange,
}: BasicAuthProps) {
  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <label
          htmlFor="basic-auth-username"
          className="inline-flex items-center gap-0.5 text-sm font-medium text-neutral-900 dark:text-neutral-100"
        >
          Username<span className="text-red-500">*</span>
          <span className="sr-only">(required)</span>
        </label>
        <Input
          id="basic-auth-username"
          type="text"
          value={username}
          onChange={(e) => onUsernameChange(e.target.value)}
          placeholder="Add username for basic authentication..."
          className="rounded-md border-neutral-300 px-4 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:text-neutral-100 dark:placeholder:text-neutral-500"
        />
      </div>

      <div className="space-y-1">
        <label
          htmlFor="basic-auth-password"
          className="inline-flex items-center gap-0.5 text-sm font-medium text-neutral-900 dark:text-neutral-100"
        >
          Password<span className="text-red-500">*</span>
          <span className="sr-only">(required)</span>
        </label>
        <Input
          id="basic-auth-password"
          type="password"
          value={password}
          onChange={(e) => onPasswordChange(e.target.value)}
          placeholder="Add password..."
          className="rounded-md border-neutral-300 px-4 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:text-neutral-100 dark:placeholder:text-neutral-500"
        />
      </div>
    </div>
  );
}
