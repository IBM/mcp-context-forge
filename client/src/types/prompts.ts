import { PromptRead } from "@/generated/types";

export interface PromptGroup<T = PromptRead> {
  /** Stable key for React lists (gateway slug, or the REST-prompts label). */
  key: string;
  /** Card title: the gateway slug, or the REST-prompts label for gateway-less prompts. */
  label: string;
  gatewayId?: string | null;
  prompts: T[];
}

export interface PromptFormData {
  name: string;
  visibility: string;
  template: string;
  arguments: string;
  description?: string;
  tags?: string;
  teamId?: string;
}

export type PromptFormErrors = Partial<Record<keyof PromptFormData | "submit", string>>;
