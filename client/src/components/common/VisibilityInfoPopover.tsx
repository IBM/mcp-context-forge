import { Info } from "lucide-react";
import { useIntl } from "react-intl";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

interface VisibilityInfoPopoverProps {
  className?: string;
  side?: "top" | "right" | "bottom" | "left";
}

/**
 * Info popover explaining the three visibility levels. The wire value "public"
 * is surfaced to users as "Internal" because it means "visible to everyone
 * signed into this platform", not "on the public internet".
 *
 * A popover (not a tooltip) so the explanation is reachable on touch devices
 * and its content stays hoverable/dismissible per WCAG 1.4.13.
 */
export function VisibilityInfoPopover({ className, side = "right" }: VisibilityInfoPopoverProps) {
  const intl = useIntl();

  return (
    <Popover>
      <PopoverTrigger
        type="button"
        aria-label={intl.formatMessage({ id: "common.visibility.info.trigger" })}
        className={cn(
          "rounded text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          className,
        )}
      >
        <Info className="size-3.5" aria-hidden="true" />
      </PopoverTrigger>
      <PopoverContent side={side} className="w-auto max-w-xs space-y-1 p-3 text-sm">
        <p>{intl.formatMessage({ id: "common.visibility.info.private" })}</p>
        <p>{intl.formatMessage({ id: "common.visibility.info.team" })}</p>
        <p>{intl.formatMessage({ id: "common.visibility.info.internal" })}</p>
      </PopoverContent>
    </Popover>
  );
}
