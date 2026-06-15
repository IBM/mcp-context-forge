import { useMemo } from "react";

type TokenType = "key" | "string" | "number" | "boolean" | "null" | "punctuation" | "whitespace";

interface TokenStyle {
  color?: string;
  fontWeight?: string;
  fontStyle?: string;
}

const TOKEN_STYLES: Record<TokenType, TokenStyle> = {
  key: { color: "#6FFF9F", fontWeight: "bold" },
  string: { color: "#AE69FF" },
  number: { color: "#FFB86F", fontStyle: "italic" },
  boolean: { color: "#6FC8FF", fontStyle: "italic" },
  null: { color: "#6FC8FF", fontStyle: "italic" },
  punctuation: {},
  whitespace: {},
};

function tokenizeJson(json: string): Array<{ type: TokenType; value: string }> {
  const tokens: Array<{ type: TokenType; value: string }> = [];
  let i = 0;

  while (i < json.length) {
    const ch = json[i];

    if (ch === '"') {
      let j = i + 1;
      while (j < json.length) {
        if (json[j] === "\\") {
          j += 2;
        } else if (json[j] === '"') {
          j++;
          break;
        } else {
          j++;
        }
      }
      const str = json.slice(i, j);
      let k = j;
      while (k < json.length && /\s/.test(json[k])) k++;
      tokens.push({ type: json[k] === ":" ? "key" : "string", value: str });
      i = j;
    } else if (/\s/.test(ch)) {
      let j = i;
      while (j < json.length && /\s/.test(json[j])) j++;
      tokens.push({ type: "whitespace", value: json.slice(i, j) });
      i = j;
    } else if (json.slice(i, i + 4) === "true") {
      tokens.push({ type: "boolean", value: "true" });
      i += 4;
    } else if (json.slice(i, i + 5) === "false") {
      tokens.push({ type: "boolean", value: "false" });
      i += 5;
    } else if (json.slice(i, i + 4) === "null") {
      tokens.push({ type: "null", value: "null" });
      i += 4;
    } else if (ch === "-" || /\d/.test(ch)) {
      let j = i;
      if (json[j] === "-") j++;
      while (j < json.length && /\d/.test(json[j])) j++;
      if (json[j] === ".") {
        j++;
        while (j < json.length && /\d/.test(json[j])) j++;
      }
      if (json[j] === "e" || json[j] === "E") {
        j++;
        if (json[j] === "+" || json[j] === "-") j++;
        while (j < json.length && /\d/.test(json[j])) j++;
      }
      tokens.push({ type: "number", value: json.slice(i, j) });
      i = j;
    } else {
      tokens.push({ type: "punctuation", value: ch });
      i++;
    }
  }

  return tokens;
}

export function JsonHighlighter({ text }: { text: string }) {
  const tokens = useMemo(() => tokenizeJson(text), [text]);
  return (
    <>
      {tokens.map((token, idx) => {
        const style = TOKEN_STYLES[token.type];
        const hasStyle = style.color || style.fontWeight || style.fontStyle;
        return hasStyle ? (
          <span key={`${token.type}-${idx}`} style={style}>
            {token.value}
          </span>
        ) : (
          token.value
        );
      })}
    </>
  );
}
