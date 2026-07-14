import { TOKEN_ENV, URL_ENV, type SnippetInput } from "./constants";

// Escape a string so it is safe to embed inside a bash single-quoted literal.
// Bash treats ' as a hard terminator with no inner escape; the idiom is to
// close the quoted run, emit a literal ', and reopen: '\''.
function bashSingleQuote(value: string): string {
  return value.replace(/'/g, "'\\''");
}

export function buildCurl({ promptName, args }: SnippetInput): string {
  const encodedName = encodeURIComponent(promptName);
  const body = JSON.stringify(args);
  const lines = [
    `curl -X POST "$${URL_ENV}/prompts/${encodedName}" \\`,
    `  -H "Authorization: Bearer $${TOKEN_ENV}" \\`,
    `  -H "Content-Type: application/json" \\`,
    `  -d '${bashSingleQuote(body)}'`,
  ];
  return lines.join("\n");
}
