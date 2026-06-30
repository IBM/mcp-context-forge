import { TOKEN_ENV, URL_ENV, type SnippetInput } from "./constants";

// Render args as a TypeScript object literal. JSON.stringify produces a valid
// object literal for string-keyed/string-valued maps and handles all string
// escaping (\" \\ \n) consistently with TS double-quoted strings.
function tsArgsLiteral(args: Record<string, string>, indent: string): string {
  const entries = Object.entries(args ?? {});
  if (entries.length === 0) return "{}";
  const body = entries
    .map(([key, value]) => `${indent}    ${JSON.stringify(key)}: ${JSON.stringify(value)},`)
    .join("\n");
  return `{\n${body}\n${indent}}`;
}

export function buildTypescript({ promptName, args }: SnippetInput): string {
  const argsLiteral = tsArgsLiteral(args, "");
  return [
    `const response = await fetch(`,
    `  \`\${process.env.${URL_ENV}}/prompts/${promptName}\`,`,
    `  {`,
    `    method: "POST",`,
    `    headers: {`,
    `      Authorization: \`Bearer \${process.env.${TOKEN_ENV}}\`,`,
    `      "Content-Type": "application/json",`,
    `    },`,
    `    body: JSON.stringify(${argsLiteral}),`,
    `  },`,
    `);`,
    `if (!response.ok) throw new Error(\`Prompt render failed: \${response.status}\`);`,
    `const data = await response.json();`,
  ].join("\n");
}
