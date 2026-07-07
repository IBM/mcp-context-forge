import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

const cardTagVariants = cva(
  "inline-flex items-center rounded px-1.5 py-1 text-[10px] font-medium leading-none",
  {
    variants: {
      variant: {
        default: "bg-tool-badge-bg text-white",
        neutral: "bg-neutral-100 text-neutral-700 dark:bg-neutral-800 dark:text-white",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

export interface CardTagProps
  extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof cardTagVariants> {
  /** Optional text shown in an accessible tooltip on hover/focus. */
  tooltip?: string | null;
}

/**
 * A compact tag chip used inside the tool/resource/prompt cards. Matches the
 * Figma card-tag style (a small squared chip, not the pill-shaped `Badge`).
 * When `tooltip` is provided the chip becomes an accessible tooltip trigger, so
 * the hint works for keyboard and touch users instead of relying on native
 * `title`.
 */
export function CardTag({ className, variant, tooltip, children, ...props }: CardTagProps) {
  const tag = (
    <span className={cn(cardTagVariants({ variant }), className)} {...props}>
      {children}
    </span>
  );

  if (!tooltip) {
    return tag;
  }

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger className="rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          {tag}
        </TooltipTrigger>
        <TooltipContent>{tooltip}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

export { cardTagVariants };
