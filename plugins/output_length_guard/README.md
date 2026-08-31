# Output Length Guard Plugin

> Author: Mihai Criveti
> Version: 1.0.0
> Last Updated: 2026-03-24

Guards tool outputs by enforcing minimum/maximum character and token lengths. Supports truncate or block strategies with recursive structuredContent processing, word-boundary truncation, and token-based budgets.

**✅ Production-Ready** - All bugs fixed, MCP protocol support added, structuredContent processing implemented, blocking strategy works with structured content, word-boundary truncation available, token budget system implemented.

## Hooks
- tool_post_invoke

## Config

```yaml
config:
  # Output limits
  min_chars: 0            # Minimum characters (0 = disabled)
  max_chars: 15000        # Maximum characters (null = disabled)
  min_tokens: 0           # Minimum tokens (0 = disabled)
  max_tokens: null        # Maximum tokens (null = disabled)
  chars_per_token: 4      # Chars per token ratio for estimation (1-10)

  # Behavior
  limit_mode: "character" # "character" or "token" - Choose ONE enforcement method
  strategy: "truncate"    # "truncate" or "block"
  ellipsis: "…"           # Appended when truncating
  word_boundary: false    # true = truncate at word boundaries

  # Security limits (optional, configurable)
  max_text_length: 1000000              # Maximum text length (DoS prevention)
  max_structure_size: 10000             # Maximum items in list/dict
  max_recursion_depth: 100              # Maximum nesting depth
```

**⚠️ IMPORTANT:** Use `limit_mode` to choose between character or token enforcement:
- **`limit_mode: "character"`** (default) - Only character limits enforced (`min_chars`, `max_chars`)
- **`limit_mode: "token"`** - Only token limits enforced (`min_tokens`, `max_tokens`)

See [Configuration Modes](#configuration-modes) section below for detailed examples.

## Examples

### Example 1: Character-Based Mode (Default)

```yaml
- name: "OutputLengthGuardPlugin"
  kind: "plugins.output_length_guard.output_length_guard.OutputLengthGuardPlugin"
  hooks: ["tool_post_invoke"]
  mode: "permissive"
  priority: 160
  config:
    limit_mode: "character"  # Explicit character mode
    max_chars: 8192
    strategy: "truncate"
    word_boundary: true
```

### Example 2: Token-Based Mode

```yaml
- name: "OutputLengthGuardPlugin"
  kind: "plugins.output_length_guard.output_length_guard.OutputLengthGuardPlugin"
  hooks: ["tool_post_invoke"]
  mode: "permissive"
  priority: 160
  config:
    limit_mode: "token"      # Explicit token mode
    max_tokens: 2000         # Limit to ~2000 tokens
    chars_per_token: 4       # Estimation ratio
    strategy: "truncate"
    word_boundary: true
```

### Example 3: Token Mode for LLM Context Management

```yaml
- name: "OutputLengthGuardPlugin"
  kind: "plugins.output_length_guard.output_length_guard.OutputLengthGuardPlugin"
  hooks: ["tool_post_invoke"]
  mode: "permissive"
  priority: 160
  config:
    limit_mode: "token"      # Token-based enforcement
    max_tokens: 4000         # GPT-4 context window
    chars_per_token: 4
    strategy: "truncate"
    word_boundary: true
```

## Configuration Modes

Use `limit_mode` to explicitly choose between character-based or token-based enforcement.

### Mode 1: Character-Based (Default)

Use **only character limits** with `limit_mode: "character"`:

```yaml
config:
  limit_mode: "character"  # Explicit character mode
  min_chars: 0             # 0 = no minimum
  max_chars: 15000         # Set your character limit
  strategy: "truncate"
```

**When to use:**
- Simple text truncation needs
- Legacy systems without token counting
- When you need precise character control
- When token estimation isn't needed

**Behavior:**
- Only `min_chars` and `max_chars` are enforced
- Token limits (`min_tokens`, `max_tokens`) are completely ignored
- No token estimation is performed

---

### Mode 2: Token-Based

Use **only token limits** with `limit_mode: "token"`:

```yaml
config:
  limit_mode: "token"      # Explicit token mode
  min_tokens: 0            # 0 = no minimum
  max_tokens: 8000         # Set your token limit (e.g., for GPT-4)
  chars_per_token: 4       # Estimation ratio (1-10)
  strategy: "truncate"
```

**When to use:**
- LLM context window management
- API rate limiting based on tokens
- Cost optimization for token-based pricing
- When you need to fit within model token limits

**Behavior:**
- Only `min_tokens` and `max_tokens` are enforced
- Character limits (`min_chars`, `max_chars`) are completely ignored
- Token estimation is performed using `chars_per_token`

**Token Estimation:**
The plugin estimates tokens using: `estimated_tokens = text_length / chars_per_token`

**Recommended `chars_per_token` values:**
- English text (GPT models): `4` (default)
- Code: `3` (more token-dense)
- Asian languages: `2-3` (characters map to more tokens)
- Mixed content: `4` (safe default)

---

### Quick Reference: Choosing a Mode

| Use Case | `limit_mode` | Limits Used |
|----------|--------------|-------------|
| Character truncation | `"character"` | `min_chars`, `max_chars` |
| Token budget management | `"token"` | `min_tokens`, `max_tokens` |
| Default behavior | `"character"` | `min_chars`, `max_chars` |

### Common Scenarios

**Scenario 1: "I only care about character limits"**
```yaml
limit_mode: "character"
max_chars: 15000
```

**Scenario 2: "I only care about token limits"**
```yaml
limit_mode: "token"
max_tokens: 8000
chars_per_token: 4
```

**Scenario 3: "Manage LLM context window"**
```yaml
limit_mode: "token"
max_tokens: 4000      # GPT-4 Turbo
chars_per_token: 4
strategy: "truncate"
word_boundary: true
```

**Scenario 4: "Block outputs that are too short"**
```yaml
limit_mode: "character"
min_chars: 100
strategy: "block"
```

---

## Design

### Hook Placement
Runs at `tool_post_invoke` to evaluate and possibly transform final text.

### Supported Data Shapes
- `str` - Plain string results
- `{text: str}` - Dict with text field
- `list[str]` - List of strings
- **`[{type: "text", text: str}]` - MCP content array format**
- **`structuredContent` - Recursive processing of nested data structures**

### Strategies

#### Truncate Strategy (`strategy: "truncate"`)
- **Behavior**: Trims over-length content and appends `ellipsis`
- **Simple strings**: Truncates if length > max_chars
- **Structured content**: Recursively truncates all string values in lists/dicts
- **Under-length**: Allows through with metadata annotation
- **Use case**: When you want to preserve partial data rather than reject entirely

#### Block Strategy (`strategy: "block"`)
- **Behavior**: Returns a violation when any string is outside `[min_chars, max_chars]`
- **Simple strings**: Blocks if length < min_chars or > max_chars
- **Structured content**: Recursively checks all strings, blocks on first violation
- **Violation details**: Includes exact location of offending string (e.g., `"level1.level2.items[2]"`)
- **Early return**: Stops processing on first violation for performance
- **Use case**: When data integrity is critical and partial data is unacceptable

### Word-Boundary Truncation

When `word_boundary: true`, the plugin truncates at word boundaries to avoid cutting words in the middle:

**How it works:**
1. Finds the cut point at `max_chars - len(ellipsis)`
2. Searches backwards to find the last word boundary (space, punctuation)
3. Truncates at the boundary and appends ellipsis
4. Falls back to hard cut if no boundary found within 20% of max_chars

**Word boundary characters:** space, tab, newline, punctuation (`.`, `,`, `;`, `:`, `!`, `?`, `-`, etc.)

**Examples:**
```python
# word_boundary: true, max_chars: 20, ellipsis: "…"

"The quick brown fox jumps"
→ "The quick brown…"  # Cuts at space before "fox"

"Supercalifragilisticexpialidocious"
→ "Supercalifragili…"  # No boundary found, hard cut

"Hello, world! How are you?"
→ "Hello, world!…"  # Cuts at punctuation
```

**When to use:**
- **Enable** (`word_boundary: true`): When truncating human-readable text where word integrity matters
- **Disable** (`word_boundary: false`): When truncating data, code, or when exact character limits are critical

### Token-Based Budget System

The plugin now supports token-based limits in addition to character-based limits, enabling more accurate control over LLM context usage.

#### Overview

**Token estimation formula:** `tokens ≈ characters / chars_per_token`

This approximate method avoids third-party dependencies while providing reasonable accuracy for budget enforcement.

#### Configuration Fields

- **`min_tokens`** (int, optional): Minimum token count (validation only, doesn't truncate)
- **`max_tokens`** (int, optional): Maximum token count (enforces truncation/blocking)
- **`chars_per_token`** (int, 1-10, default: 4): Approximate characters per token ratio

#### How It Works

1. **Token Estimation**: Calculates `tokens = len(text) // chars_per_token`
2. **Cut Point Calculation**: Computes character cut point as `max_tokens * chars_per_token`
3. **Word Boundary**: Optionally adjusts cut point to nearest word boundary
4. **Truncation**: Applies cut and appends ellipsis

#### Modes

**Token-Only Mode:**
```yaml
config:
  max_tokens: 2000
  chars_per_token: 4
```

#### Customizing chars_per_token

The `chars_per_token` ratio depends on your content type:

| Content Type | Recommended Ratio | Reasoning |
|--------------|-------------------|-----------|
| English prose | 4 | Standard GPT tokenization (~4 chars/token) |
| Code | 3 | More symbols, shorter tokens |
| Technical docs | 4-5 | Mix of prose and technical terms |
| Non-English | 2-3 | Unicode characters may use more tokens |
| JSON/XML | 2-3 | Structural characters count as tokens |

**Example:**
```yaml
# For code-heavy content
config:
  max_tokens: 1500
  chars_per_token: 3  # More conservative for code
```

#### Performance

- **Direct Arithmetic**: O(1) token-to-character conversion for finding cut point
- **Token Caching**: Token counts calculated once and reused
- **Security Limits**:
  - Max text length: 1MB
  - Max structure size: 10K items
  - Max recursion depth: 100 levels

#### Examples

**Basic token truncation:**
```python
# Config: max_tokens=5, chars_per_token=4
"Hello world! This is a test string."  # 37 chars = 9 tokens
→ "Hello world! This…"  # 19 chars = 4 tokens
```

**Token + word boundary:**
```python
# Config: max_tokens=5, chars_per_token=4, word_boundary=true
"Hello world! This is a test string."
→ "Hello world!…"  # Cuts at word boundary, 12 chars = 3 tokens
```

**Hybrid mode:**
```python
# Config: max_chars=25, max_tokens=5, chars_per_token=4
"Hello world! This is a test string."
→ "Hello world! This…"  # Respects both limits (19 chars, 4 tokens)
```

**Structured content:**
```python
# Config: max_tokens=3, chars_per_token=4
{
  "items": [
    "Hello world! This is a test.",  # 29 chars = 7 tokens
    "Another long string here."      # 25 chars = 6 tokens
  ]
}
→ {
  "items": [
    "Hello world!…",  # 12 chars = 3 tokens
    "Another long…"   # 12 chars = 3 tokens
  ]
}
```

#### Blocking with Tokens

When `strategy: "block"`, violations include token information:

```python
# Config: strategy="block", max_tokens=5, chars_per_token=4
"Hello world! This is a test string."
→ Violation: "String at path '' exceeds max_tokens (9 > 5)"
```

#### Logging

Token operations are logged at DEBUG/INFO levels:

```
DEBUG: Estimating tokens for text (37 chars, ratio=4) → 9 tokens
DEBUG: Token cut point: max_tokens=5, chars_per_token=4 → cut at 20 chars
INFO: Token-based truncation: 37 chars → 20 chars (9 tokens → 5 tokens)
```

### Security Limits

The plugin includes configurable security limits to prevent resource exhaustion and protect against malicious inputs.

#### Available Security Limits

| Limit | Default | Valid Range | Purpose |
|-------|---------|-------------|---------|
| `max_text_length` | 1,000,000 | 1KB - 10MB | Maximum text size to process (prevents memory exhaustion) |
| `max_structure_size` | 10,000 | 10 - 100K | Maximum items in list/dict (prevents DoS attacks) |
| `max_recursion_depth` | 100 | 10 - 1000 | Maximum nesting depth (prevents stack overflow) |

#### Customizing Security Limits

**Example: Increase limits for large document processing**
```yaml
config:
  max_text_length: 5000000      # 5MB for large documents
  max_structure_size: 50000     # 50K items for big datasets
  max_recursion_depth: 200      # Deeper nesting allowed
```

**Example: Stricter limits for untrusted input**
```yaml
config:
  max_text_length: 100000       # 100KB limit
  max_structure_size: 1000      # 1K items max
  max_recursion_depth: 50       # Shallow nesting only
```

#### Security Best Practices

1. **Set appropriate limits** based on your use case and available resources
2. **Monitor logs** for security limit violations
3. **Customize sensitive keywords** to match your domain-specific secrets
4. **Test with edge cases** to ensure limits are effective
5. **Review limits periodically** as requirements change

#### Validation

All security limits are validated at configuration time:
- `max_text_length`: Must be between 1,000 and 10,000,000 bytes
- `max_structure_size`: Must be between 10 and 100,000 items
- `max_recursion_depth`: Must be between 10 and 1,000 levels

Invalid values will raise a `ValueError` with a descriptive message.

### Design Decisions

1. **Numeric String Preservation**: Numeric strings (integers, floats, scientific notation) are never truncated or blocked to prevent data corruption
2. **Path Tracking**: In block mode, violations include the exact path to the offending string for easy debugging
3. **Early Return**: Block mode returns immediately on first violation rather than collecting all violations
4. **Structure Preservation**: Truncate mode preserves the original data structure while modifying string values
5. **Priority Processing**: `structuredContent` is processed before `content` array to ensure consistency
6. **Word-Boundary Fallback**: If no boundary found within 20% of max_chars, falls back to hard cut to avoid excessive truncation

### Metadata
Includes original/new length, strategy, min/max for auditability.

### Configuration Validation
All config fields validated at load time using Pydantic validators.

## StructuredContent Processing

When a tool result contains `structuredContent` or `structured_content`, the plugin now:
1. **Recursively traverses** the structured data (lists, dicts, nested structures)
2. **Truncates all string values** found at any depth
3. **Regenerates the `content` field** with a formatted representation of the truncated data
4. **Preserves data structure** while applying length limits

### Examples

**List of strings:**
```json
Input:  {"structuredContent": {"result": ["longstring1", "longstring2"]}}
Output: {"structuredContent": {"result": ["long", "long"]}, "content": [{"type": "text", "text": "[\"long\",\"long\"]"}]}
```

**Nested dict:**
```json
Input:  {"structuredContent": {"user": {"name": "Alice Smith", "email": "alice@example.com"}}}
Output: {"structuredContent": {"user": {"name": "Alice", "email": "alice"}}, "content": [{"type": "text", "text": "{\"user\":{\"name\":\"Alice\",\"email\":\"alice\"}}"}]}
```

**Mixed nested structure:**
```json
Input:  {"structuredContent": {"users": [{"name": "Bob Johnson"}, {"name": "Carol White"}]}}
Output: {"structuredContent": {"users": [{"name": "Bob"}, {"name": "Carol"}]}, "content": [{"type": "text", "text": "{\"users\":[{\"name\":\"Bob\"},{\"name\":\"Carol\"}]}"}]}
```

## Numeric String Preservation

The plugin automatically detects and preserves numeric strings to prevent data corruption. This applies to both `content` and `structuredContent` fields.

**Preserved formats:**
- **Integers**: `"123"`, `"1000000000000"`
- **Floats**: `"123.45"`, `"3.14159"`, `"0.001"`
- **Scientific notation**: `"1.23e-4"`, `"5E+10"`, `"6.022e23"`

**Examples:**
```json
Input:  {"content": [{"type": "text", "text": "123.456789"}]}
Output: {"content": [{"type": "text", "text": "123.456789"}]}  // NOT truncated

Input:  {"structuredContent": {"price": "99.99", "quantity": "1000"}}
Output: {"structuredContent": {"price": "99.99", "quantity": "1000"}}  // Both preserved

Input:  {"content": [{"type": "text", "text": "Hello world"}]}
Output: {"content": [{"type": "text", "text": "Hello"}]}  // Truncated (non-numeric)
```

**Note:** Actual numeric types (int, float) in structured data are always preserved regardless of this check, as they pass through unchanged.

## Limitations
- Non-text payloads are ignored in `content` array.
- `truncate` strategy does not expand under-length outputs, only annotates.
- Counting is Unicode codepoints (not grapheme clusters); may differ from UI-perceived length.
- MCP content items with type != "text" pass through unchanged.
- Non-string values in structuredContent (int, bool, None) pass through unchanged.

## Changelog

### v1.0.0 (2026-03-24)

**Major Release** - Consolidates all features and fixes into stable production release.

#### Key Features
- **Word-Boundary Truncation** - Truncate at word boundaries for better readability
- **Structured Content Support** - Recursive processing of nested lists and dicts
- **Blocking Strategy** - Reject responses exceeding limits with detailed violation info
- **Numeric Preservation** - Preserves numeric strings (integers, floats, scientific notation)
- **MCP Protocol Support** - Full support for MCP content arrays and structured content
- **Path Tracking** - Violations include exact location of offending content
- **Configuration Validation** - Comprehensive Pydantic validators for all settings

#### Configuration
- **Simplified**: Focused configuration on core length management features
- **Validated**: Comprehensive Pydantic validators ensure correct settings

#### Technical Improvements
- **Early Return Optimization** - Block mode stops on first violation for better performance
- **Smart Boundary Detection** - Detects spaces, punctuation, and word separators
- **Content Regeneration** - Automatically updates content field from structured data
- **Comprehensive Testing** - Full test suite for all features


## Testing

### Test Files
- `test_blocking_structured.py` - Comprehensive tests for blocking strategy with structured content
- `test_numeric_preservation.py` - Tests for numeric string preservation
- `test_nested_truncation.py` - Tests for nested structure truncation
- `test_word_boundary.py` - Tests for word-boundary truncation feature

### Example Test Cases
```python
# Block mode with list - should block on long string
payload = ToolPostInvokePayload(
    name="echo_list",
    result=["short", "this_is_way_too_long", "ok"]
)
result = await plugin.tool_post_invoke(payload, context)
assert result.violation is not None
assert result.violation.details["location"] == "[1]"

# Block mode with nested dict - should block with path
payload = ToolPostInvokePayload(
    name="complex_tool",
    result={"level1": {"level2": {"items": ["short", "too_long"]}}}
)
result = await plugin.tool_post_invoke(payload, context)
assert result.violation.details["location"] == "level1.level2.items[1]"
```

## TODOs
- Support for image and resource content types in MCP format
- Optional collection of all violations in block mode (currently uses early return)
- Configurable word-boundary search distance (currently fixed at 20% of max_chars)
