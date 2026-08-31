# Code Safety Linter Plugin

> Author: Mihai Criveti
> Version: 0.1.0

Detects unsafe code patterns (eval/exec/os.system/subprocess/rm -rf) in tool outputs and blocks when found.

## Hooks
- tool_post_invoke

## Config
```yaml
config:
  blocked_patterns:
    - "\\beval\\s*\\("
    - "\\bexec\\s*\\("
    - "\\bos\\.system\\s*\\("
    - "\\bsubprocess\\.(Popen|call|run)\\s*\\("
    - "\\brm\\s+-rf\\b"
```

## Design
- Regex-based detector scans text outputs or `result.text` fields for risky constructs.
- In `enforce` mode returns a violation with matched patterns; else may annotate only.

## Limitations
- Patterns are language-agnostic and may produce false positives in prose.
- Does not analyze code structure or execution context.

## TODOs
- Add language-aware rulesets and severity grading.
- Optional auto-sanitization (commenting dangerous lines) in permissive mode.
