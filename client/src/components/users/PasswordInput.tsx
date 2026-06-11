import React from "react";
import { Eye, EyeOff } from "lucide-react";
import { useIntl } from "react-intl";
import { Input } from "@/components/ui/input";

interface PasswordInputProps {
  id: string;
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  label: string;
  required?: boolean;
  autoComplete?: string;
  error?: string;
  hint?: string;
}

export function PasswordInput({
  id,
  value,
  onChange,
  placeholder,
  label,
  required = false,
  autoComplete = "new-password",
  error,
  hint,
}: PasswordInputProps) {
  const intl = useIntl();
  const [showPassword, setShowPassword] = React.useState(false);
  const errorId = `${id}-error`;
  const hintId = `${id}-hint`;

  return (
    <div className="space-y-1">
      <label
        htmlFor={id}
        className="inline-flex items-center gap-0.5 text-sm font-medium text-neutral-900 dark:text-neutral-100"
      >
        {label}
        {required && (
          <>
            <span className="text-red-500">*</span>
            <span className="sr-only">(required)</span>
          </>
        )}
      </label>
      <div className="relative">
        <Input
          id={id}
          type={showPassword ? "text" : "password"}
          autoComplete={autoComplete}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          className="rounded-md border-neutral-300 bg-white px-4 pr-10 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100 dark:placeholder:text-neutral-500"
          aria-invalid={!!error}
          aria-describedby={error ? errorId : hint ? hintId : undefined}
        />
        <button
          type="button"
          onClick={() => setShowPassword((v) => !v)}
          className="absolute inset-y-0 right-0 flex items-center px-3 text-neutral-400 hover:text-neutral-600 dark:hover:text-neutral-300"
          aria-label={intl.formatMessage({
            id: showPassword ? "users.form.password.hide" : "users.form.password.show",
          })}
        >
          {showPassword ? (
            <EyeOff className="h-4 w-4" aria-hidden="true" />
          ) : (
            <Eye className="h-4 w-4" aria-hidden="true" />
          )}
        </button>
      </div>
      {error ? (
        <p id={errorId} className="text-sm text-red-600 dark:text-red-400" role="alert" aria-live="polite">
          {error}
        </p>
      ) : hint ? (
        <p id={hintId} className="text-xs text-neutral-500 dark:text-neutral-400">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
