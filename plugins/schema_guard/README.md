# Schema Guard Plugin

> Author: Mihai Criveti
> Version: 0.1.0

Validates tool args and results against a minimal JSONSchema-like subset (type, properties, required).

## Hooks
- tool_pre_invoke
- tool_post_invoke

## Config
```yaml
config:
  arg_schemas:
    calc:
      type: object
      required: [a, b]
      properties:
        a: {type: integer}
        b: {type: integer}
  result_schemas:
    calc:
      type: object
      required: [result]
      properties:
        result: {type: number}
  block_on_violation: true
```

## Design
- Validates against a small subset of JSONSchema: `type`, `properties`, `required`, and array `items`.
- Pre-hook checks input args; post-hook checks tool result.
- Blocking behavior controlled by `block_on_violation`; otherwise attaches `schema_errors` in metadata.

## Limitations
- No support for advanced JSONSchema keywords (e.g., `oneOf`, `allOf`, `format`, `enum`).
- No automatic coercion; values must already match the schema types.
- Deep/nested validation supported only through nested `properties`/`items` in the provided schema.

## TODOs
- Add optional type coercion (e.g., strings to numbers/booleans).
- Extend keyword support (min/max, pattern, enum, string length).
- Schema registry integration and per-tool versioning.
