# Code Formatter Plugin

Formats code/text outputs with lightweight, dependency-free normalization:
- Trim trailing whitespace
- Normalize indentation (tabs → spaces)
- Ensure single trailing newline
- Optional JSON pretty-printing
- Optional Markdown/code fence cleanup

Hooks
- tool_post_invoke
- resource_post_fetch

Configuration (example)
```yaml
- name: "CodeFormatter"
  kind: "plugins.code_formatter.code_formatter.CodeFormatterPlugin"
  hooks: ["tool_post_invoke", "resource_post_fetch"]
  mode: "permissive"
  priority: 180
  config:
    languages: ["python", "json", "markdown", "shell"]
    tab_width: 4
    trim_trailing: true
    ensure_newline: true
    dedent_code: true
    format_json: true
    max_size_kb: 512
```

Notes
- No external formatters are invoked; it's safe and fast.
- For JSON, the plugin attempts to parse then pretty-print; on failure it falls back to generic normalization.
- The plugin respects `max_size_kb` to avoid large payload overhead.
