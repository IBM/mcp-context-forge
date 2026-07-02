export interface Prompt {
  id: string;
  name: string;
  displayName?: string;
  originalName?: string;
  gatewayId?: string | null;
  gatewaySlug?: string | null;
  description?: string | null;
  tags?: Array<{ id: string; label: string }>;
  arguments?: PromptArgument[];
}

export interface PromptArgument {
  name: string;
  description?: string;
  required?: boolean;
}

export type PromptsResponse = Prompt[] | { prompts?: Prompt[] };

export interface PromptFormData {
  name: string;
  visibility: string;
  template: string;
  arguments: string;
  description?: string;
  tags?: string;
  teamId?: string;
}

export type PromptFormErrors = Partial<Record<keyof PromptFormData, string>>;
