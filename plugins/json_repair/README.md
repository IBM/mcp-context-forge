# JSON Repair Plugin

> Author: Mihai Criveti
> Version: 0.1.0

Attempts conservative repairs of almost-JSON string outputs (single→double quotes, trailing comma removal, simple brace wrapping).

## Hooks
- tool_post_invoke

## Design
- Attempts targeted fixes: single→double quotes for simple JSON-like strings, removes trailing commas before } or ], and braces raw key:value text when safe.
- Applies only when the repaired candidate parses as valid JSON.

## Limitations
- Heuristics are conservative; some valid-but-nonstandard cases will not be repaired.
- Does not repair deeply malformed structures or comments in JSON.

## TODOs
- Add optional lenient JSON parser mode for richer repairs.
- Provide diff metadata showing changes for auditability.
