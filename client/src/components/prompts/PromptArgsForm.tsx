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
              <Label htmlFor={fieldId} className="flex items-center gap-1.5">
                <span className="font-mono text-[12px] text-foreground">{arg.name}</span>
                <span className="text-[11px] text-muted-foreground">
                  {required
                    ? intl.formatMessage({ id: "prompts.details.code.args.required" })
                    : intl.formatMessage({ id: "prompts.details.code.args.optional" })}
                </span>
              </Label>
              <Input
                id={fieldId}
                value={args[arg.name] ?? ""}
                onChange={(event) => handleChange(arg.name, event.target.value)}
                placeholder={intl.formatMessage({
                  id: "prompts.details.code.args.placeholder",
                })}
                required={required}
                aria-required={required}
                className="font-mono text-[12px]"
              />
              {arg.description && (
                <p className="text-[11px] text-muted-foreground">{arg.description}</p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
