import type { ComponentType } from "react";

export interface ActionCard {
  icon: ComponentType<{ className?: string }>;
  title: string;
  description: string;
  buttonText: string;
  onAction: () => void;
  disabled?: boolean;
  disabledReason?: string;
}

export type ComponentFilter = "all" | "tools" | "resources" | "prompts";

export interface DetailComponentItem {
  id: string;
  name: string;
  secondary?: string;
  type: Exclude<ComponentFilter, "all">;
}
