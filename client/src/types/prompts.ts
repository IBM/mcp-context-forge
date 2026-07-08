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

export interface PromptGroup<T = Prompt> {
  /** Stable key for React lists (gateway slug, or the REST-prompts label). */
  key: string;
  /** Card title: the gateway slug, or the REST-prompts label for gateway-less prompts. */
  label: string;
  gatewayId?: string | null;
  prompts: T[];
}
