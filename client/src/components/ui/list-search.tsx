import { useRef, useState } from "react";
import { Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

interface ListSearchProps {
  value: string;
  onChange: (value: string) => void;
  ariaLabel: string;
  placeholder?: string;
  className?: string;
}

/**
 * Expandable search box for entity list tables. Collapses to an icon until
 * focused or non-empty, mirroring the search affordance used in the details
 * drawers. Filtering is owned by the caller; this component only manages the
 * expand/collapse presentation.
 */
export function ListSearch({
  value,
  onChange,
  ariaLabel,
  placeholder,
  className,
}: ListSearchProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [isExpanded, setIsExpanded] = useState(false);
  const open = isExpanded || value.length > 0;

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <Button
        type="button"
        variant="ghost"
        size="icon-xs"
        onClick={() => inputRef.current?.focus()}
        className="size-8 rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        aria-label={ariaLabel}
      >
        <Search className="size-4" />
      </Button>
      <Input
        ref={inputRef}
        type="search"
        aria-label={ariaLabel}
        tabIndex={open ? 0 : -1}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onFocus={() => setIsExpanded(true)}
        onBlur={() => setIsExpanded(value.length > 0)}
        placeholder={open ? placeholder : ""}
        className={cn(
          "h-8 rounded-md border-border bg-muted/50 text-sm shadow-none transition-[width,padding,color,background-color,border-color] duration-200 ease-out placeholder:text-muted-foreground focus-visible:bg-background",
          open
            ? "w-48 px-3 text-foreground"
            : "w-0 px-0 text-transparent caret-foreground border-transparent",
        )}
      />
    </div>
  );
}
