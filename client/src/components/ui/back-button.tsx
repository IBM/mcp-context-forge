import { ArrowLeft } from "lucide-react";
import { useIntl } from "react-intl";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export interface BackButtonProps {
  /** Invoked when the button is activated (typically closes/toggles the form). */
  onClick: () => void;
  className?: string;
}

/**
 * Ghost "Back" button rendered above the card in entity create/edit forms
 * (prompts, tools, resources, users). Keeps the label and styling in one place
 * so the forms stay visually consistent.
 */
export function BackButton({ onClick, className }: BackButtonProps) {
  const intl = useIntl();
  return (
    <Button
      variant="ghost"
      size="sm"
      className={cn(
        "mb-4 gap-1.5 px-2 text-sm text-neutral-400 hover:text-neutral-700 dark:text-neutral-300 dark:hover:text-white",
        className,
      )}
      onClick={onClick}
      type="button"
    >
      <ArrowLeft className="h-4 w-4" />
      {intl.formatMessage({ id: "common.button.back" })}
    </Button>
  );
}
