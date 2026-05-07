import * as React from "react";

import { cn } from "@/lib/utils";

const Input = React.forwardRef<HTMLInputElement, React.ComponentProps<"input">>(({ className, type, ...props }, ref) => {
  return (
    <input
      ref={ref}
      type={type}
      data-slot="input"
      className={cn(
        "h-9 w-full min-w-0 rounded-md border border-input bg-transparent px-2.5 py-1 text-base shadow-xs outline-none " +
          "transition-[color,box-shadow] placeholder:text-muted-foreground md:text-sm " +
          "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 " +
          "disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 " +
          "aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20 " +
          "file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground " +
          "dark:bg-input/30 dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/40",
        className,
      )}
      {...props}
    />
  );
});

Input.displayName = "Input";

export { Input };
