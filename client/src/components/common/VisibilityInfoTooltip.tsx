import { Info } from "lucide-react";
import { useIntl } from "react-intl";

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

interface VisibilityInfoTooltipProps {
  className?: string;
  side?: "top" | "right" | "bottom" | "left";
}

/**
 * Info tooltip explaining the three visibility levels. The wire value "public"
 * is surfaced to users as "Internal" because it means "visible to everyone
 * signed into this platform", not "on the public internet".
 */
export function VisibilityInfoTooltip({ className, side = "right" }: VisibilityInfoTooltipProps) {
  const intl = useIntl();

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger
          type="button"
          aria-label={intl.formatMessage({ id: "common.visibility.info.trigger" })}
          className={cn(
            "rounded text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            className,
          )}
        >
          <Info className="size-3.5" aria-hidden="true" />
        </TooltipTrigger>
        <TooltipContent side={side} className="max-w-xs flex-col items-start gap-1">
          <p>{intl.formatMessage({ id: "common.visibility.info.private" })}</p>
          <p>{intl.formatMessage({ id: "common.visibility.info.team" })}</p>
          <p>{intl.formatMessage({ id: "common.visibility.info.internal" })}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
