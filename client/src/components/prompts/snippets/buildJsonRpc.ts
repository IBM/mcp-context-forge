import type { SnippetInput } from "./constants";

export function buildJsonRpc({ promptName, args }: SnippetInput): string {
  const envelope = {
    jsonrpc: "2.0",
    id: 1,
    method: "prompts/get",
    params: {
      name: promptName,
      arguments: args,
    },
  };
  return JSON.stringify(envelope, null, 2);
}
