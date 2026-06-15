import type { ComponentType } from "react";
import type { Visibility } from "@/types/server";

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

export interface CreateServerDetails {
  name: string;
  visibility: Visibility;
  teamId?: string;
  oauthEnabled: boolean;
  tags?: string[];
  description?: string;
  associatedTools?: string[];
  associatedResources?: string[];
  associatedPrompts?: string[];
  associatedMCPServerIds?: string[];
}

export interface DetailComponentItem {
  id: string;
  name: string;
  secondary?: string;
  type: Exclude<ComponentFilter, "all">;
}
