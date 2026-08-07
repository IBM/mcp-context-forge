/**
 * StatusDot — a small colored status indicator with an optional label. The tone
 * is chosen by the caller from a fixed lookup (status -> tone), never derived
 * from other fields. Reused by health chips and mini-card status indicators.
 */

import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export type StatusTone = "success" | "error" | "warning" | "muted";

const TONE_CLASS: Record<StatusTone, string> = {
  success: "bg-green-500",
  error: "bg-destructive",
  warning: "bg-yellow-500",
  muted: "bg-muted-foreground",
};

interface StatusDotProps {
  tone: StatusTone;
  children?: ReactNode;
  className?: string;
}

export function StatusDot({ tone, children, className }: StatusDotProps) {
  return (
    <span className={cn("inline-flex items-center gap-1.5", className)}>
      <span className={cn("size-2 shrink-0 rounded-full", TONE_CLASS[tone])} aria-hidden />
      {children}
    </span>
  );
}
