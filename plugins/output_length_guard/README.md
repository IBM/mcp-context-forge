# Output Length Guard Plugin

> Author: Mihai Criveti
> Version: 0.1.0

Guards tool outputs by enforcing minimum/maximum character lengths. Supports truncate or block strategies.

## Hooks
- tool_post_invoke

## Config
```yaml
config:
  min_chars: 0            # 0 disables minimum check
  max_chars: 15000        # null disables maximum check
  strategy: "truncate"    # truncate | block
  ellipsis: "…"           # used when truncating
```

## Example
```yaml
- name: "OutputLengthGuardPlugin"
  kind: "plugins.output_length_guard.output_length_guard.OutputLengthGuardPlugin"
  hooks: ["tool_post_invoke"]
  mode: "permissive"
  priority: 160
  config:
    max_chars: 8192
    strategy: "truncate"
```

## Design
- Hook placement: runs at `tool_post_invoke` to evaluate and possibly transform final text.
- Supported shapes: `str`, `{text: str}`, `list[str]`; conservative no-op for other types.
- Strategies:
  - truncate: trims only over-length content and appends `ellipsis`.
  - block: returns a violation when result length is outside `[min_chars, max_chars]`.
- Metadata: includes original/new length, strategy, min/max for auditability.

## Limitations
- Non-text payloads are ignored; nested shapes beyond `result.text` are not traversed.
- `truncate` strategy does not expand under-length outputs, only annotates.
- Counting is Unicode codepoints (not grapheme clusters); may differ from UI-perceived length.

## TODOs
- Add support for token-based budgets using model-specific tokenizers.
- Add opt-in traversal for nested structures and arrays of dicts.
- Optional word-boundary truncation to avoid mid-word cuts.
