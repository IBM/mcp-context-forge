import { useCallback, useId, useMemo } from "react";
import { useIntl } from "react-intl";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { PromptArgument } from "@/generated/types";

export interface PromptArgsFormProps {
  args: Record<string, string>;
  schema: (PromptArgument | null)[];
  onChange: (next: Record<string, string>) => void;
}

function toPlaceholder(description?: string): string {
  if (!description) return "";
  const trimmed = description.trim();
  if (!trimmed) return "";
  const egMatch = trimmed.match(/\be\.g\..*/i);
  const extracted = egMatch ? egMatch[0] : trimmed;
  return extracted.charAt(0).toLowerCase() + extracted.slice(1);
}

/**
 * Renders one input per declared prompt argument. Pure controlled component —
 * holds no state of its own. Parent owns the args record and replaces it on
 * every change.
 */
export function PromptArgsForm({ args, schema, onChange }: PromptArgsFormProps) {
  const intl = useIntl();
  const fieldIdPrefix = useId();

  const declared = useMemo(
    () => schema.filter((entry): entry is NonNullable<PromptArgument> => Boolean(entry)),
    [schema],
  );

  const handleChange = useCallback(
    (name: string, value: string) => {
      onChange({ ...args, [name]: value });
    },
    [args, onChange],
  );

  if (declared.length === 0) {
    return null;
  }

  return (
    <div className="space-y-3">
      <h4 className="text-sm font-semibold text-foreground">
        {intl.formatMessage({ id: "prompts.details.code.args.heading" })}
      </h4>
      <div className="space-y-3">
        {declared.map((arg) => {
          const fieldId = `${fieldIdPrefix}-${arg.name}`;
          const required = Boolean(arg.required);
          return (
            <div key={arg.name} className="space-y-1.5">
              <Label htmlFor={fieldId} className="inline-flex items-center gap-0.5">
                <span className="font-mono text-[12px] text-foreground">{arg.name}</span>
                {required && (
                  <>
                    <span className="text-red-500" aria-hidden="true">
                      *
                    </span>
                    <span className="sr-only">
                      {intl.formatMessage({ id: "prompts.details.code.args.required" })}
                    </span>
                  </>
                )}
              </Label>
              <Input
                id={fieldId}
                value={args[arg.name] ?? ""}
                onChange={(event) => handleChange(arg.name, event.target.value)}
                placeholder={toPlaceholder(arg.description)}
                required={required}
                aria-required={required}
                className="placeholder:text-neutral-400 dark:placeholder:text-neutral-500"
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}
