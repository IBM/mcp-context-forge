import React from "react";

interface FormFieldProps {
  id: string;
  label: string;
  required?: boolean;
  error?: string;
  children: React.ReactNode;
}

/**
 * Wraps a form field with a label, children slot, and accessible error paragraph.
 * Error paragraph id follows the convention `${id}-error` so callers can wire
 * aria-describedby on their input.
 */
export function FormField({ id, label, required = false, error, children }: FormFieldProps) {
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
      {children}
      {error && (
        <p
          id={`${id}-error`}
          className="text-sm text-red-600 dark:text-red-400"
          role="alert"
          aria-live="polite"
        >
          {error}
        </p>
      )}
    </div>
  );
}
