# JSON Prune Plugin

> Authors: Mihai Criveti, Alexander Wiegand
> Version: 0.1.0

Strips unnecessary JSON fields from API tool responses before passing them to an LLM. Uses a whitelist approach: only fields explicitly listed in dot-notation paths are retained.

## Hooks
- tool_post_invoke

## Design
- Configures per-tool whitelists via the `webhooks` list in plugin config.
- Each webhook entry specifies a `name` (matching the tool name) and a `fields` list of dot-notation paths (e.g. `["name", "address.city"]`).
- Handles two result formats: plain JSON strings and MCP `content[0]["text"]` dicts.
- Uses recursive prefix-based pruning to support arbitrary nesting depth.
- Runs after `json_repair` (priority 149 vs 145) so JSON is already valid.

## Config Example

```yaml
config:
  debug: false
  webhooks:
    - name: "search_api"
      fields:
        - "title"
        - "url"
        - "snippet"
    - name: "weather_api"
      fields:
        - "location.name"
        - "current.temp_c"
        - "current.condition.text"
```

## Limitations
- Only top-level list elements are iterated; nested lists inside dicts are kept as-is when their parent path is whitelisted.
- Whitelist paths are exact dot-notation matches; no glob or wildcard support.

## TODOs
- Add wildcard/glob path support (e.g. `results.*.title`).
- Add blacklist mode as an alternative to whitelist.
- Support per-tool output size limits.
