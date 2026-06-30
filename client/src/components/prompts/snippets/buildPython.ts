import { TOKEN_ENV, URL_ENV, type SnippetInput } from "./constants";

// Render args as a Python dict literal. JSON syntax is a valid subset of Python
// for string-keyed/string-valued dicts (double-quoted keys/values, \" \\ \n
// escapes line up), so JSON.stringify produces a safe literal.
function pythonArgsLiteral(args: Record<string, string>, indent: string): string {
  const entries = Object.entries(args ?? {});
  if (entries.length === 0) return "{}";
  const body = entries
    .map(([key, value]) => `${indent}    ${JSON.stringify(key)}: ${JSON.stringify(value)},`)
    .join("\n");
  return `{\n${body}\n${indent}}`;
}

export function buildPython({ promptName, args }: SnippetInput): string {
  const argsLiteral = pythonArgsLiteral(args, "    ");
  return [
    "import os",
    "import requests",
    "",
    "response = requests.post(",
    `    f"{os.environ['${URL_ENV}']}/prompts/${promptName}",`,
    `    headers={"Authorization": f"Bearer {os.environ['${TOKEN_ENV}']}"},`,
    `    json=${argsLiteral},`,
    ")",
    "response.raise_for_status()",
    "print(response.json())",
  ].join("\n");
}
