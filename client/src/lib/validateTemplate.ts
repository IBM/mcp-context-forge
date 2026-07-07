export const TEMPLATE_MAX_LENGTH = 65536;

const DANGEROUS_HTML_TAGS_RE = /<(script|iframe|object|embed|link|meta|base|form)\b/i;
const EVENT_HANDLER_RE = /on\w+\s*=/i;
const SSTI_SIMPLE_PREFIXES = ["${", "#{", "%{"];
const SSTI_DANGEROUS_SUBSTRINGS = [
  "__", "config", "self", "request", "application", "globals", "builtins",
  "import", "getattr", "|attr", "|selectattr", "|sort", "|map", "attribute=",
  "\\x", "\\u", "\\0", "lipsum", "cycler", "joiner",
];
const SSTI_DANGEROUS_OPERATORS = ["*", "/", "+", "-", "~", "[", "%"];

function iterTemplateExpressions(value: string, start: string, end: string): string[] {
  const exprs: string[] = [];
  let i = 0;
  while (i < value.length) {
    const startIdx = value.indexOf(start, i);
    if (startIdx === -1) break;
    const endIdx = value.indexOf(end, startIdx + start.length);
    if (endIdx === -1) break;
    exprs.push(value.slice(startIdx + start.length, endIdx));
    i = endIdx + end.length;
  }
  return exprs;
}

export function validateTemplateContent(value: string): string | null {
  if (value.length > TEMPLATE_MAX_LENGTH) return "templateTooLong";
  if (DANGEROUS_HTML_TAGS_RE.test(value)) return "templateHtmlTags";
  if (EVENT_HANDLER_RE.test(value)) return "templateEventHandlers";
  if (SSTI_SIMPLE_PREFIXES.some((p) => value.includes(p))) return "templateDangerousExpression";

  for (const expr of [...iterTemplateExpressions(value, "{{", "}}"), ...iterTemplateExpressions(value, "{%", "%}")]) {
    const lower = expr.toLowerCase().replace(/\s*\|\s*/g, "|").replace(/\s*=\s*/g, "=");
    if (SSTI_DANGEROUS_SUBSTRINGS.some((s) => lower.includes(s))) return "templateDangerousExpression";
    if (lower.includes(".")) return "templateDangerousExpression";
    if (SSTI_DANGEROUS_OPERATORS.some((op) => expr.includes(op))) return "templateDangerousExpression";
  }
  return null;
}
