# TOON Encoder Plugin

> **Document Location:** `plugins/toon_encoder/README.md`
>
> **Related Documents:**
> - [TOON Format Specification](https://github.com/toon-format/spec/blob/main/SPEC.md)
> - Tests: `tests/unit/plugins/toon_encoder/`

A post-invoke plugin that converts JSON tool results to [TOON (Token-Oriented Object Notation)](https://github.com/toon-format/spec) format for reduced token consumption when sending responses to LLM agents.

## Overview

TOON is a compact, human-readable encoding format designed specifically for LLM prompts. It provides lossless serialization of JSON data in a syntax that minimizes tokens by:

- Eliminating quotation marks around keys and simple string values
- Using compact array syntax: `field[N]: val1,val2,val3`
- Using columnar format for homogeneous object arrays
- Removing unnecessary punctuation where context is clear

## Token Savings

### Expected Savings by Data Type

| Data Type | JSON Size | TOON Size | Savings |
|-----------|-----------|-----------|---------|
| Simple object | 150 bytes | 80 bytes | **~47%** |
| Array of 10 objects | 2 KB | 600 bytes | **~70%** |
| Nested data | 5 KB | 2 KB | **~60%** |
| Simple primitives | minimal | minimal | ~0% |

### Verified Example

Real-world test with array of user objects:

```
JSON (231 chars):
{"users": [{"id": 0, "name": "user0", "active": true}, {"id": 1, "name": "user1", "active": true}, ...]}

TOON (109 chars):
users:
  [5]{active,id,name}:
   true,0,user0
   true,1,user1
   true,2,user2
   true,3,user3
   true,4,user4

Savings: 52.8% (122 bytes saved)
```

### Why This Matters

For an agent using MCP Gateway to federate 10+ MCP servers:
- Each tool call returns JSON responses (database queries, API data, etc.)
- JSON verbosity (quoted keys, quoted strings, punctuation) inflates token count
- **Accumulated impact across many tool calls:**
  - Inference latency (more tokens = longer processing)
  - Context window consumption (less room for reasoning)
  - API costs (for cloud-hosted inference)

## Running Locally

### Prerequisites

- Python 3.11+
- MCP Gateway repository cloned
- `uv` package manager (or pip)

### Step 1: Set Up Development Environment

```bash
# Clone the repo (if not already)
git clone https://github.com/IBM/mcp-context-forge.git
cd mcp-context-forge

# Create virtual environment and install dependencies
make venv install-dev

# Copy environment template
cp .env.example .env
```

### Step 2: Enable the Plugin

Edit `.env` to enable plugins:
```bash
PLUGINS_ENABLED=true
PLUGIN_CONFIG_FILE=plugins/config.yaml
```

Add the TOON encoder to `plugins/config.yaml`:
```yaml
plugins:
  # ... existing plugins ...

  - name: "ToonEncoder"
    kind: "plugins.toon_encoder.toon_encoder.ToonEncoderPlugin"
    hooks: ["tool_post_invoke"]
    mode: "enforce"
    priority: 900
    config:
      min_size_bytes: 100
```

### Step 3: Start the Gateway

```bash
# Development server with auto-reload
make dev

# Or production server
make serve
```

The gateway will start on `http://localhost:8000` (dev) or `http://localhost:4444` (prod).

### Step 4: Verify Plugin is Loaded

Check the startup logs for:
```
INFO: ToonEncoderPlugin initialized: min_size=100, max_size=1048576, exclude=[]
```

### Step 5: Test the Plugin

```bash
# Run plugin-specific tests
pytest tests/unit/plugins/toon_encoder/ -v

# Quick inline test of TOON encoder
python3 -c "
from plugins.toon_encoder.toon import encode, decode
data = {'users': [{'id': 1, 'name': 'alice'}, {'id': 2, 'name': 'bob'}]}
toon = encode(data)
print('TOON output:')
print(toon)
print()
print('Round-trip:', decode(toon) == data)
"
```

### Step 6: Test with Real Tool Calls

1. Register an MCP server via the Admin UI or API
2. Create a virtual server with tools
3. Invoke a tool that returns JSON
4. Check the response for `annotations.format: "toon"`

```bash
# Example: Call a tool via the API
curl -X POST http://localhost:8000/tools/my-tool/invoke \
  -H "Content-Type: application/json" \
  -d '{"arguments": {}}'

# Response should contain TOON-encoded content with format annotation
```

### Troubleshooting

| Issue | Solution |
|-------|----------|
| Plugin not loading | Check `PLUGINS_ENABLED=true` in `.env` |
| No TOON conversion | Verify JSON response > `min_size_bytes` (default 100) |
| Import errors | Run `make install-dev` to install dependencies |
| Tests failing | Ensure you're in the virtual environment |

---

## Installation

The plugin is included in the MCP Gateway plugins directory. Enable it in your configuration:

### 1. Add to `plugins/config.yaml`

```yaml
plugins:
  - name: "ToonEncoder"
    kind: "plugins.toon_encoder.toon_encoder.ToonEncoderPlugin"
    hooks: ["tool_post_invoke"]
    mode: "enforce"
    priority: 900  # Run late, after other post-processing
    config:
      min_size_bytes: 100        # Only convert JSON larger than this
      max_size_bytes: 1048576    # Skip very large payloads (1MB)
      exclude_tools: []          # Tool names to skip
      include_tools: null        # Whitelist (null = all tools)
      add_format_marker: true    # Add annotation marking content as TOON
      skip_on_error: true        # Continue with JSON if conversion fails
```

### 2. Enable plugins in `.env`

```bash
PLUGINS_ENABLED=true
PLUGIN_CONFIG_FILE=plugins/config.yaml
```

## Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `min_size_bytes` | int | 100 | Minimum JSON size to trigger conversion |
| `max_size_bytes` | int | 1048576 | Maximum JSON size to convert (prevents OOM) |
| `exclude_tools` | list | [] | Tool names to skip conversion |
| `include_tools` | list | null | Whitelist of tools (if set, only these are converted) |
| `add_format_marker` | bool | true | Add `annotations.format: "toon"` to converted content |
| `skip_on_error` | bool | true | Continue with original JSON if conversion fails |

## Usage Examples

### Example 1: Convert all tool results

```yaml
- name: "ToonEncoder"
  kind: "plugins.toon_encoder.toon_encoder.ToonEncoderPlugin"
  hooks: ["tool_post_invoke"]
  mode: "enforce"
  priority: 900
  config:
    min_size_bytes: 100
```

### Example 2: Only convert specific tools

```yaml
- name: "ToonEncoder"
  kind: "plugins.toon_encoder.toon_encoder.ToonEncoderPlugin"
  hooks: ["tool_post_invoke"]
  mode: "enforce"
  priority: 900
  config:
    include_tools:
      - "search_documents"
      - "query_database"
      - "list_items"
```

### Example 3: Exclude binary/streaming tools

```yaml
- name: "ToonEncoder"
  kind: "plugins.toon_encoder.toon_encoder.ToonEncoderPlugin"
  hooks: ["tool_post_invoke"]
  mode: "enforce"
  priority: 900
  config:
    exclude_tools:
      - "download_file"
      - "stream_data"
      - "get_binary"
```

## TOON Format Reference

TOON (Token-Oriented Object Notation) is designed to minimize tokens while preserving all JSON data.
For the complete specification, see the [official TOON spec](https://github.com/toon-format/spec/blob/main/SPEC.md).

### Primitives

| JSON | TOON | Notes |
|------|------|-------|
| `null` | `null` | Literal |
| `true` | `true` | Literal |
| `false` | `false` | Literal |
| `42` | `42` | Integers as-is |
| `3.14` | `3.14` | Floats as-is |
| `"hello"` | `hello` | Simple strings unquoted |
| `"hello world"` | `hello world` | Spaces OK in values |
| `"has,comma"` | `"has,comma"` | Special chars quoted |
| `""` | `""` | Empty string quoted |

### Objects

**Simple Object:**
```
JSON: {"name": "alice", "age": 30, "active": true}

TOON:
name: alice
age: 30
active: true
```

**Nested Object:**
```
JSON: {"user": {"name": "alice", "email": "alice@example.com"}}

TOON:
user:
  name: alice
  email: alice@example.com
```

**Empty Object:**
```
JSON: {}
TOON: (empty document)
```

### Arrays

**Simple Array (inline):**
```
JSON: [1, 2, 3]
TOON: [3]: 1,2,3
```

**String Array:**
```
JSON: ["apple", "banana", "cherry"]
TOON: [3]: apple,banana,cherry
```

**Empty Array:**
```
JSON: []
TOON: [0]:
```

**Nested Array:**
```
JSON: {"tags": ["python", "fastapi", "mcp"]}

TOON:
tags[3]: python,fastapi,mcp
```

### Columnar Format (Arrays of Objects)

When all objects in an array have identical keys with primitive values, TOON uses
a compact columnar format:

```
JSON:
[
  {"id": 1, "name": "alice", "score": 95},
  {"id": 2, "name": "bob", "score": 87},
  {"id": 3, "name": "charlie", "score": 92}
]

TOON:
[3]{id,name,score}:
 1,alice,95
 2,bob,87
 3,charlie,92
```

The header `[3]{id,name,score}:` specifies:
- `[3]` - Array contains 3 objects
- `{id,name,score}` - Column order (alphabetically sorted)
- Each row contains values in that column order

### Complex Nested Example

```
JSON:
{
  "status": "success",
  "data": {
    "users": [
      {"id": 1, "name": "alice", "roles": ["admin", "user"]},
      {"id": 2, "name": "bob", "roles": ["user"]}
    ],
    "total": 2
  },
  "metadata": {
    "page": 1,
    "per_page": 10
  }
}

TOON:
status: success
data:
  users:
    [2]:
     id: 1
     name: alice
     roles:
       [2]: admin,user
     id: 2
     name: bob
     roles:
       [1]: user
  total: 2
metadata:
  page: 1
  per_page: 10
```

### String Quoting Rules

Strings must be quoted if they:
- Are empty
- Equal `true`, `false`, or `null`
- Look like a number (e.g., `"123"`, `"3.14"`)
- Contain special characters: `,` `:` `[` `]` `{` `}` `"` `\` newlines
- Have leading or trailing whitespace

```
JSON: {"status": "null", "count": "42", "note": "a,b,c"}

TOON:
status: "null"
count: "42"
note: "a,b,c"
```

### Key Quoting Rules

Object keys must be quoted if they don't match `^[A-Za-z_][A-Za-z0-9_.]*$`:

```
JSON: {"valid_key": 1, "has space": 2, "123numeric": 3}

TOON:
valid_key: 1
"has space": 2
"123numeric": 3
```

## Agent Integration (Required)

> **IMPORTANT:** When you enable the TOON encoder plugin, your agent's system prompt **must be updated** to understand TOON format. Without this change, your agent will not be able to parse tool results correctly.

### Why This Is Required

- The gateway converts JSON tool responses to TOON format before sending to your agent
- Standard LLMs are trained on JSON, not TOON
- Your agent needs instructions on how to interpret TOON-formatted data
- Tool results will include `annotations.format: "toon"` to indicate the format

### Recommended System Prompt Addition

Add the following to your agent's system prompt:

```
## Tool Response Format: TOON

Tool results from this gateway use TOON (Token-Oriented Object Notation) format for efficiency.
Results with `annotations.format: "toon"` are TOON-encoded. Parse them as follows:

### TOON Syntax Rules

1. **Objects** - Key-value pairs on separate lines (no braces, no quoted keys):
   ```
   name: alice
   age: 30
   active: true
   ```
   Equivalent JSON: {"name": "alice", "age": 30, "active": true}

2. **Simple Arrays** - Count prefix with comma-separated values:
   ```
   [3]: apple,banana,cherry
   ```
   Equivalent JSON: ["apple", "banana", "cherry"]

3. **Object Arrays (Columnar)** - Count and keys in header, values in rows:
   ```
   [3]{id,name,score}:
    1,alice,95
    2,bob,87
    3,charlie,92
   ```
   Equivalent JSON: [{"id": 1, "name": "alice", "score": 95}, {"id": 2, "name": "bob", "score": 87}, {"id": 3, "name": "charlie", "score": 92}]

4. **Nested Objects** - Indented under parent key:
   ```
   user:
     name: alice
     email: alice@example.com
   settings:
     theme: dark
     notifications: true
   ```

5. **Special Values**:
   - `null` = null/None
   - `true` / `false` = booleans
   - Unquoted numbers = integers or floats
   - Quoted strings `"value"` = strings containing special characters (commas, colons, newlines)

### Parsing Instructions

When you receive a tool result:
1. Check if `annotations.format` equals `"toon"`
2. If yes, parse the text content using TOON rules above
3. If no annotation or format is not "toon", parse as standard JSON

TOON is a lossless format - all data from the original JSON is preserved.
```

### Complete System Prompt Example

Here's a complete example for an agent using MCP Gateway with TOON:

```
You are a helpful assistant with access to tools via MCP Gateway.

## Tool Response Format: TOON

Tool results from this gateway use TOON (Token-Oriented Object Notation) format for efficiency.
TOON reduces token usage by 40-70% compared to JSON while preserving all data.

### Quick Reference

| TOON | Meaning |
|------|---------|
| `key: value` | Object property |
| `[N]: a,b,c` | Array of N items |
| `[N]{k1,k2}:` followed by rows | Array of N objects with keys k1,k2 |
| `null`, `true`, `false` | Literal values |
| `"quoted"` | String with special characters |

### Example

TOON:
```
users:
  [2]{id,name,active}:
   1,alice,true
   2,bob,false
total: 2
```

Means:
```json
{
  "users": [
    {"id": 1, "name": "alice", "active": true},
    {"id": 2, "name": "bob", "active": false}
  ],
  "total": 2
}
```

When processing tool results, interpret TOON format and extract the data you need.
```

### Checking Format Annotation

Tool results include a format marker when TOON-encoded:

```python
# Result structure from gateway
{
    "content": [
        {
            "type": "text",
            "text": "name: alice\nage: 30",
            "annotations": {
                "format": "toon"  # <-- This indicates TOON encoding
            }
        }
    ]
}
   ```

## Programmatic Usage

The TOON encoder/decoder can be used directly:

```python
from plugins.toon_encoder.toon import encode, decode, estimate_token_savings

# Encode Python object to TOON
data = {"users": [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}]}
toon_str = encode(data)
print(toon_str)
# users:
#   [2]{id,name}:
#    1,alice
#    2,bob

# Decode TOON back to Python
decoded = decode(toon_str)
assert decoded == data

# Estimate savings
import json
json_str = json.dumps(data)
json_len, toon_len, savings_pct = estimate_token_savings(json_str)
print(f"Saved {savings_pct:.1f}% ({json_len - toon_len} bytes)")
```

## Monitoring

The plugin tracks conversion statistics accessible via the `get_stats()` method:

```python
stats = plugin.get_stats()
# {
#     "conversions_attempted": 150,
#     "conversions_successful": 142,
#     "total_bytes_saved": 45230,
#     "success_rate": 94.67
# }
```

Conversion metadata is also included in each response:

```python
result.metadata = {
    "toon_encoded": True,
    "bytes_saved": 1250,
    "savings_percent": 62.5,
    "conversion_time_ms": 0.45
}
```

## Testing

Run the plugin tests:

```bash
# Run TOON encoder tests
pytest tests/unit/plugins/toon_encoder/test_toon.py -v

# Run plugin integration tests
pytest tests/unit/plugins/toon_encoder/test_toon_encoder.py -v

# Run all plugin tests
pytest tests/unit/plugins/toon_encoder/ -v
```

## Limitations

1. **Agent must understand TOON** - The receiving LLM/agent needs to parse TOON format
2. **Not all data benefits** - Very simple data may not see significant savings
3. **No streaming support** - Entire response must be buffered for conversion

### Known Decoder Limitations

The built-in TOON decoder has some edge case limitations (these don't affect the plugin's
primary use case of encoding for LLMs, which parse the format themselves):

- **Quoted keys in single-line objects** - Objects with quoted keys like `"has space": 1`
  are encoded correctly but may not decode properly when on a single line
- **Arrays of arrays** - Nested arrays like `[[1,2], [3,4]]` may have decoding issues
- **Mixed sibling fields after columnar arrays** - When a columnar array is followed by
  primitive fields at the same nesting level, the primitives may not decode
- **Alternative delimiters in columnar headers** - The TOON spec v3.0 allows tab (`\t`) or
  pipe (`|`) as alternative delimiters in columnar array headers (e.g., `[2]{a|b}:` with
  rows `1|2`). The encoder always produces comma-delimited output. The decoder regex
  matches these alternative delimiters but does not parse them correctly—it always splits
  on commas. This is rarely encountered in practice since most TOON producers use commas.

These limitations affect the `decode()` function used for round-trip testing. The `encode()`
function correctly handles all these cases per the TOON specification.

## License

Apache-2.0 - See LICENSE file in repository root.
