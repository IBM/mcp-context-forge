export const URL_ENV = "MCPGATEWAY_URL";
export const TOKEN_ENV = "MCPGATEWAY_BEARER_TOKEN";

export type SnippetLanguage = "curl" | "jsonRpc" | "python" | "typescript";

export interface SnippetInput {
  promptName: string;
  args: Record<string, string>;
}
