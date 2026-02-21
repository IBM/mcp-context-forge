# Search Replace Plugin for MCP Gateway

> Author: Teryl Taylor
> Version: 0.1.0

A native plugin for MCP Gateway that performs regex-based search and replace operations on prompt arguments and responses.

## Features

- **Pre-fetch Hook**: Modifies prompt arguments before prompt retrieval
- **Post-fetch Hook**: Modifies rendered prompt messages after processing
- **Regex Support**: Full regex pattern matching and replacement
- **Multiple Patterns**: Configure multiple search/replace pairs
- **Chain Transformations**: Apply replacements in sequence
- **Dual Implementation**: Python and Rust implementations with consistent behavior
- **Pattern Validation**: Validates regex patterns at configuration time

## Installation

The plugin is included with MCP Gateway and requires no additional installation. Simply enable it in your configuration.

## Configuration

Add the plugin to your `plugins/config.yaml`:

```yaml
plugins:
  - name: "SearchReplacePlugin"
    kind: "plugins.regex_filter.search_replace.SearchReplacePlugin"
    description: "Performs text transformations using regex patterns"
    version: "0.1"
    author: "ContextForge"
    hooks: ["prompt_pre_fetch", "prompt_post_fetch"]
    tags: ["transformer", "regex", "text-processing"]
    mode: "enforce"  # enforce | permissive | disabled
    priority: 150    # Lower = higher priority
    conditions:
      - prompts: ["test_prompt", "chat_prompt"]  # Apply to specific prompts
        server_ids: []  # Apply to all servers
        tenant_ids: []  # Apply to all tenants
    config:
      words:
        - search: "crap"
          replace: "crud"
        - search: "damn"
          replace: "darn"
        - search: "\\bAI\\b"  # Word boundary regex
          replace: "artificial intelligence"
```

## Configuration Options

### Plugin Settings

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Unique plugin identifier |
| `kind` | string | Yes | Plugin class path |
| `hooks` | array | Yes | Hook points to enable |
| `mode` | string | No | Execution mode: `enforce`, `permissive`, or `disabled` |
| `priority` | integer | No | Execution order (default: 150) |
| `conditions` | array | No | Conditional execution rules |

### Search/Replace Configuration

| Field | Type | Description |
|-------|------|-------------|
| `words` | array | List of search/replace pairs |
| `words[].search` | string | Regex pattern to search for |
| `words[].replace` | string | Replacement text |

## Usage Examples

### Basic Word Replacement

```yaml
config:
  words:
    - search: "hello"
      replace: "greetings"
    - search: "goodbye"
      replace: "farewell"
```

### Regex Pattern Matching

```yaml
config:
  words:
    # Replace email addresses with placeholder
    - search: "[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}"
      replace: "[email]"

    # Replace phone numbers
    - search: "\\b\\d{3}-\\d{3}-\\d{4}\\b"
      replace: "[phone]"

    # Case-insensitive replacement
    - search: "(?i)microsoft"
      replace: "MS"
```

### Chained Transformations

```yaml
config:
  words:
    # These apply in order
    - search: "bad"
      replace: "not good"
    - search: "not good"
      replace: "could be better"
    # Result: "bad" → "not good" → "could be better"
```

## How It Works

### Pre-fetch Hook
1. Receives prompt name and arguments
2. Applies all configured patterns to each argument value
3. Returns modified arguments for prompt rendering

### Post-fetch Hook
1. Receives rendered prompt messages
2. Applies patterns to message content
3. Returns modified messages

## Testing

### Manual Testing

1. Enable the plugin in your configuration
2. Create a test prompt:
```bash
curl -X POST http://localhost:4444/prompts \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "test_prompt",
    "template": "User said: {{ message }}",
    "argument_schema": {
      "type": "object",
      "properties": {"message": {"type": "string"}},
      "required": ["message"]
    }
  }'
```

3. Test the replacement:
```bash
curl -X GET http://localhost:4444/prompts/test_prompt \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "This is crap"}'

# Expected: "User said: This is crud"
```

### Unit Testing

```python
import pytest
from plugins.regex_filter.search_replace import SearchReplacePlugin, SearchReplaceConfig

@pytest.mark.asyncio
async def test_search_replace():
    config = PluginConfig(
        name="test",
        kind="plugins.regex_filter.search_replace.SearchReplacePlugin",
        version="0.1",
        hooks=["prompt_pre_fetch"],
        config={
            "words": [
                {"search": "foo", "replace": "bar"}
            ]
        }
    )

    plugin = SearchReplacePlugin(config)
    payload = PromptPrehookPayload(
        name="test",
        args={"message": "foo is foo"}
    )

    result = await plugin.prompt_pre_fetch(payload, context)
    assert result.modified_payload.args["message"] == "bar is bar"
```

## Regex Pattern Compatibility

### Python vs Rust Regex Differences

This plugin has both Python and Rust implementations. While most regex patterns work identically in both, there are some differences to be aware of:

#### ✅ Compatible Patterns (Work in Both)

- Basic patterns: `hello`, `\d+`, `\w+`
- Character classes: `[a-z]`, `[0-9]`
- Quantifiers: `*`, `+`, `?`, `{n,m}`
- Anchors: `^`, `$`, `\b`
- Groups: `(...)`, `(?:...)`
- Alternation: `|`
- Lookahead: `(?=...)`, `(?!...)`
- Case-insensitive: `(?i)pattern`

#### ⚠️ Potentially Incompatible Patterns

| Feature | Python | Rust | Recommendation |
|---------|--------|------|----------------|
| Named groups | `(?P<name>...)` | `(?<name>...)` | Use non-capturing groups `(?:...)` |
| Lookbehind | `(?<=...)`, `(?<!...)` | Limited support | Avoid or test thoroughly |
| Backreferences | `\1`, `\g<1>` | `$1` in replacement | Use simple patterns |
| Unicode categories | `\p{L}` | Different syntax | Test with both implementations |

### Pattern Validation

The plugin validates all regex patterns at initialization time:

```python
# ✅ Valid - will initialize successfully
config = {
    "words": [
        {"search": r"\bword\b", "replace": "replacement"},
        {"search": r"\d{3}-\d{2}-\d{4}", "replace": "XXX-XX-XXXX"}
    ]
}

# ❌ Invalid - will raise ValueError
config = {
    "words": [
        {"search": "[invalid(", "replace": "replacement"}  # Unclosed bracket
    ]
}
```

### Compatibility Warnings

The Python implementation detects potentially incompatible patterns and logs warnings:

```python
# This will log a warning about Python-specific syntax
config = {
    "words": [
        {"search": r"(?P<name>\w+)", "replace": "REDACTED"}
    ]
}
# Warning: Pattern 0 '(?P<name>\w+)': Uses Python-specific named groups...
```

### Best Practices

1. **Test with both implementations** if using advanced regex features
2. **Use simple, portable patterns** when possible
3. **Avoid Python-specific syntax** like `(?P<name>...)`
4. **Check logs for warnings** about potential incompatibilities
5. **Run tests** with both Python and Rust to ensure consistency

## Performance Considerations

- Patterns are compiled once during initialization
- Regex complexity affects performance
- Consider priority when chaining with other plugins
- Use specific prompt conditions to limit scope
- Rust implementation provides 2-10x performance improvement for large payloads

## Common Use Cases

1. **Profanity Filter**: Replace inappropriate language
2. **Terminology Standardization**: Ensure consistent terms
3. **PII Redaction**: Simple pattern-based PII removal
4. **Format Normalization**: Standardize date/time formats
5. **Abbreviation Expansion**: Expand common abbreviations

## Troubleshooting

### Patterns Not Matching
- Check regex syntax and escaping
- Test patterns with online regex tools
- Enable debug logging to see transformations

### Performance Issues
- Simplify complex regex patterns
- Reduce number of patterns
- Use prompt conditions to limit scope

### Unexpected Results
- Remember patterns apply in order
- Check for overlapping patterns
- Test with simple inputs first

## Available Hooks

The plugin manifest declares support for:
- `prompt_pre_hook` - Before prompt retrieval
- `prompt_post_hook` - After prompt rendering
- `tool_pre_hook` - Before tool execution (not implemented)
- `tool_post_hook` - After tool execution (not implemented)

Currently only prompt hooks are implemented.

## Contributing

To extend this plugin:

1. Add new transformation strategies
2. Implement tool hooks
3. Add pattern validation
4. Create preset pattern libraries

## License

Apache-2.0

## Support

For issues or questions, please open an issue in the MCP Gateway repository.
