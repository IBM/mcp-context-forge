import { Building2, Info, Lock, Users } from "lucide-react";
import { useIntl } from "react-intl";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

const INFO_IDS = {
  private: "common.visibility.info.private",
  team: "common.visibility.info.team",
  public: "common.visibility.info.internal",
} as const;

const LABEL_IDS = {
  private: "common.visibility.private",
  team: "common.visibility.team",
  public: "common.visibility.internal",
} as const;

const VISIBILITY_ICONS = { private: Lock, team: Users, public: Building2 };

/** Per-level icon for visibility rows; unknown/absent values fall back to Building2. */
export function getVisibilityIcon(visibility?: string | null) {
  return VISIBILITY_ICONS[visibility as keyof typeof VISIBILITY_ICONS] ?? Building2;
}

interface VisibilityInfoPopoverProps {
  className?: string;
  side?: "top" | "right" | "bottom" | "left";
  /**
   * Selected level. When it is a known level the popover shows only that
   * level's description; unknown or absent shows all three (forms, where the
   * user is still choosing).
   */
  visibility?: string | null;
}

/**
 * Info popover explaining the three visibility levels. The wire value "public"
 * is surfaced to users as "Internal" because it means "visible to everyone
 * signed into this platform", not "on the public internet".
 *
 * A popover (not a tooltip) so the explanation is reachable on touch devices
 * and its content stays hoverable/dismissible per WCAG 1.4.13.
 */
export function VisibilityInfoPopover({
  className,
  side = "right",
  visibility,
}: VisibilityInfoPopoverProps) {
  const intl = useIntl();
  const selectedInfoId = INFO_IDS[visibility as keyof typeof INFO_IDS];

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
        {selectedInfoId ? (
          <p>{intl.formatMessage({ id: selectedInfoId })}</p>
        ) : (
          (["private", "team", "public"] as const).map((level) => (
            <p key={level}>
              {intl.formatMessage({ id: LABEL_IDS[level] })}
              {": "}
              {intl.formatMessage({ id: INFO_IDS[level] })}
            </p>
          ))
        )}
      </PopoverContent>
    </Popover>
  );
}
