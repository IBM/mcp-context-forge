import type { ComponentProps } from "react";
import { Info } from "lucide-react";
import { useIntl } from "react-intl";
import { cn } from "@/lib/utils";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

const VISIBILITY_LEVELS = ["private", "team", "internal"] as const;

export function VisibilityHelp({
  className,
  ...props
}: ComponentProps<typeof Tooltip> & { className?: string }) {
  const intl = useIntl();
  return (
    <TooltipProvider>
      <Tooltip {...props}>
        <TooltipTrigger asChild>
          <button
            type="button"
            aria-label={intl.formatMessage({ id: "common.visibility.help.aria" })}
            className={cn("inline-flex text-muted-foreground hover:text-foreground", className)}
          >
            <Info className="size-3.5" aria-hidden="true" />
          </button>
        </TooltipTrigger>
        <TooltipContent className="max-w-xs">
          <ul className="space-y-1">
            {VISIBILITY_LEVELS.map((level) => (
              <li key={level}>
                <span className="font-medium">
                  {intl.formatMessage({ id: `common.visibility.label.${level}` })}
                </span>
                {" — "}
                {intl.formatMessage({ id: `common.visibility.help.${level}` })}
              </li>
            ))}
          </ul>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
