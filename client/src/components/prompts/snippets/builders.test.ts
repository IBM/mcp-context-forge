import { describe, it, expect } from "vitest";
import { buildCurl } from "./buildCurl";
import { buildJsonRpc } from "./buildJsonRpc";
import { buildPython } from "./buildPython";
import { buildTypescript } from "./buildTypescript";

const NAME = "greet_user";

// Escape-safety matrix — values that historically break naive string-concat
// snippet builders. Each value must round-trip cleanly through every
// language's parser back to the original string.
const TRICKY_ARGS: Record<string, string> = {
  quote: 'she said "hi"',
  backslash: "a\\b",
  newline: "line1\nline2",
  dollarVar: "${MCPGATEWAY_BEARER_TOKEN}",
  singleQuote: "it's mine",
};

// Helper — extract the JSON body curl sends with `-d '<json>'`.
// Reverses the bash single-quote escape (`'\''` → `'`).
function extractCurlBody(snippet: string): string {
  const match = snippet.match(/-d '([\s\S]*)'$/);
  if (!match) throw new Error("could not find -d body in curl snippet");
  return match[1].replace(/'\\''/g, "'");
}

// Helper — extract the args literal from a Python/TS snippet by locating the
// dict/object literal between `json=` (Python) or `JSON.stringify(` (TS) and
// the matching closing token. Brace-matched so embedded `}` in values are safe.
//
// Python and TS both allow (and we emit) trailing commas; strict JSON does
// not, so strip them before handing off to JSON.parse for the round-trip
// assertion.
//
// NOTE (test-parser only): the `snippet[i - 1] !== "\\"` inString check
// misparses a literal `\\"` sequence (escaped backslash immediately before a
// quote). Not exercised by TRICKY_ARGS; if the escape matrix grows, upgrade
// this to a proper two-state lexer.
function extractBracedLiteral(snippet: string, prefix: string): string {
  const start = snippet.indexOf(prefix);
  if (start === -1) throw new Error(`prefix not found: ${prefix}`);
  const openBrace = snippet.indexOf("{", start);
  let depth = 0;
  let inString = false;
  for (let i = openBrace; i < snippet.length; i++) {
    const ch = snippet[i];
    if (ch === '"' && snippet[i - 1] !== "\\") inString = !inString;
    if (inString) continue;
    if (ch === "{") depth++;
    else if (ch === "}") {
      depth--;
      if (depth === 0) {
        return snippet.slice(openBrace, i + 1).replace(/,(\s*[}\]])/g, "$1");
      }
    }
  }
  throw new Error("unbalanced braces in snippet");
}

describe("snippet builders — empty args", () => {
  it.each([
    ["curl", () => buildCurl({ promptName: NAME, args: {} })],
    ["jsonRpc", () => buildJsonRpc({ promptName: NAME, args: {} })],
    ["python", () => buildPython({ promptName: NAME, args: {} })],
    ["typescript", () => buildTypescript({ promptName: NAME, args: {} })],
  ])("%s emits a valid snippet with empty args", (_lang, build) => {
    const snippet = build();
    expect(snippet).toContain(NAME);
    expect(snippet).not.toContain("undefined");
    expect(snippet).not.toContain("null");
  });

  it("curl with empty args sends {}", () => {
    expect(extractCurlBody(buildCurl({ promptName: NAME, args: {} }))).toBe("{}");
  });

  it("jsonRpc with empty args has empty arguments object", () => {
    const parsed = JSON.parse(buildJsonRpc({ promptName: NAME, args: {} }));
    expect(parsed.params.arguments).toEqual({});
  });

  it("python with empty args emits {}", () => {
    expect(buildPython({ promptName: NAME, args: {} })).toContain("json={},");
  });

  it("typescript with empty args emits {}", () => {
    expect(buildTypescript({ promptName: NAME, args: {} })).toContain("JSON.stringify({})");
  });
});

describe("snippet builders — basic args", () => {
  const args = { user_name: "Alice", tone: "friendly" };

  it("curl produces parseable JSON body with all args", () => {
    const body = extractCurlBody(buildCurl({ promptName: NAME, args }));
    expect(JSON.parse(body)).toEqual(args);
  });

  it("jsonRpc envelope is valid JSON and includes args under params.arguments", () => {
    const parsed = JSON.parse(buildJsonRpc({ promptName: NAME, args }));
    expect(parsed).toMatchObject({
      jsonrpc: "2.0",
      method: "prompts/get",
      params: { name: NAME, arguments: args },
    });
  });

  it("python dict literal is parseable as JSON (since values are strings)", () => {
    const literal = extractBracedLiteral(buildPython({ promptName: NAME, args }), "json=");
    expect(JSON.parse(literal)).toEqual(args);
  });

  it("typescript object literal is parseable as JSON (since values are strings)", () => {
    const literal = extractBracedLiteral(
      buildTypescript({ promptName: NAME, args }),
      "JSON.stringify(",
    );
    expect(JSON.parse(literal)).toEqual(args);
  });
});

describe("snippet builders — escape-safety matrix", () => {
  // Each value must round-trip back to its original through the corresponding
  // language's parser. These are the historical pain points.

  it("curl: tricky values round-trip through bash single-quote + JSON", () => {
    const body = extractCurlBody(buildCurl({ promptName: NAME, args: TRICKY_ARGS }));
    expect(JSON.parse(body)).toEqual(TRICKY_ARGS);
  });

  it("jsonRpc: tricky values round-trip through JSON parsing", () => {
    const parsed = JSON.parse(buildJsonRpc({ promptName: NAME, args: TRICKY_ARGS }));
    expect(parsed.params.arguments).toEqual(TRICKY_ARGS);
  });

  it("python: tricky values round-trip through JSON parsing of the dict literal", () => {
    const literal = extractBracedLiteral(
      buildPython({ promptName: NAME, args: TRICKY_ARGS }),
      "json=",
    );
    expect(JSON.parse(literal)).toEqual(TRICKY_ARGS);
  });

  it("typescript: tricky values round-trip through JSON parsing of the object literal", () => {
    const literal = extractBracedLiteral(
      buildTypescript({ promptName: NAME, args: TRICKY_ARGS }),
      "JSON.stringify(",
    );
    expect(JSON.parse(literal)).toEqual(TRICKY_ARGS);
  });

  it("dollar-sign values are not shell-expanded inside curl single quotes", () => {
    const snippet = buildCurl({ promptName: NAME, args: { dollarVar: "${INJECTED}" } });
    // Body lives inside single quotes — bash treats $ literally there.
    expect(snippet).toContain('\'{"dollarVar":"${INJECTED}"}\'');
  });

  it("never emits smart quotes — straight ASCII only", () => {
    const all = [
      buildCurl({ promptName: NAME, args: TRICKY_ARGS }),
      buildJsonRpc({ promptName: NAME, args: TRICKY_ARGS }),
      buildPython({ promptName: NAME, args: TRICKY_ARGS }),
      buildTypescript({ promptName: NAME, args: TRICKY_ARGS }),
    ].join("\n");
    expect(all).not.toMatch(/[‘’“”]/);
  });

  it("uses the literal env var names, not interpolated values", () => {
    const snippet = buildCurl({ promptName: NAME, args: {} });
    expect(snippet).toContain("$MCPGATEWAY_URL");
    expect(snippet).toContain("$MCPGATEWAY_BEARER_TOKEN");
  });
});

describe("snippet builders — URL encoding of prompt name", () => {
  // Backend name regex allows spaces and dots (^[a-zA-Z0-9_.\- ]+$), so the
  // snippet URLs must percent-encode or the copied curl/python/typescript
  // will 400 as an unquoted path.

  it("curl encodes spaces in the URL path", () => {
    expect(buildCurl({ promptName: "my prompt", args: {} })).toContain("/prompts/my%20prompt");
  });

  it("python encodes spaces in the URL path", () => {
    expect(buildPython({ promptName: "my prompt", args: {} })).toContain("/prompts/my%20prompt");
  });

  it("typescript encodes spaces in the URL path", () => {
    expect(buildTypescript({ promptName: "my prompt", args: {} })).toContain(
      "/prompts/my%20prompt",
    );
  });

  it("json-rpc carries the raw name as a field value (JSON handles escaping)", () => {
    const parsed = JSON.parse(buildJsonRpc({ promptName: "my prompt", args: {} }));
    expect(parsed.params.name).toBe("my prompt");
  });
});
