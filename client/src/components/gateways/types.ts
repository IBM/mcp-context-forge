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

export type CreateServerVisibility = "public" | "team" | "private";

export interface CreateServerDetails {
  name: string;
  visibility: CreateServerVisibility;
  oauthEnabled: boolean;
  tags?: string[];
  description?: string;
  associatedTools?: string[];
  associatedResources?: string[];
  associatedPrompts?: string[];
}

export interface DetailComponentItem {
  id: string;
  name: string;
  secondary?: string;
  type: Exclude<ComponentFilter, "all">;
}
