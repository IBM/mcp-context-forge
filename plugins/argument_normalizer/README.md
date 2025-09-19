# Argument Normalizer Plugin

Author: Mihai Criveti

Normalizes user/tool arguments before they reach prompts or tools. It improves robustness and predictability by:
- Unicode normalization (NFC/NFD/NFKC/NFKD) and control-char stripping
- Whitespace cleanup (trim, collapse internal whitespace, CRLF→LF, optional blank-line collapse)
- Optional casing strategies (none/lower/upper/title)
- Numeric date normalization to ISO 8601 (`YYYY-MM-DD`) with `day_first`/`year_first`
- Number normalization to canonical format with `.` as decimal separator

## Hooks
- `prompt_pre_fetch`
- `tool_pre_invoke`

## Quick Config Example
Add this entry in `plugins/config.yaml` (already wired by default):

```yaml
- name: "ArgumentNormalizer"
  kind: "plugins.argument_normalizer.argument_normalizer.ArgumentNormalizerPlugin"
  description: "Normalizes Unicode, whitespace, casing, dates, and numbers in args"
  version: "0.1.0"
  author: "Mihai Criveti"
  hooks: ["prompt_pre_fetch", "tool_pre_invoke"]
  tags: ["normalize", "inputs", "whitespace", "unicode", "dates", "numbers"]
  mode: "permissive"
  priority: 40
  conditions: []
  config:
    enable_unicode: true
    unicode_form: "NFC"
    remove_control_chars: true
    enable_whitespace: true
    trim: true
    collapse_internal: true
    normalize_newlines: true
    collapse_blank_lines: false
    enable_casing: false
    case_strategy: "none"
    enable_dates: true
    day_first: false
    year_first: false
    enable_numbers: true
    decimal_detection: "auto"
    field_overrides: []
```

## Field Overrides
Use `field_overrides` to tailor normalization per-field using regexes that match field paths (e.g. `user.name`, `items[0].title`). Example:

```yaml
config:
  field_overrides:
    - pattern: "^user\\.name$"
      enable_casing: true
      case_strategy: "title"
    - pattern: "price|amount|total"
      enable_numbers: true
      decimal_detection: "auto"
    - pattern: "^notes$"
      collapse_blank_lines: true
```

## Examples
- Input: `"  JOHN   DOE  "` with lower-casing → `"john doe"`
- Input: `"1.234,56 EUR"` with numeric normalization → `"1234.56 EUR"`
- Input: `"Due 31/12/2023"` with `day_first: true` → `"Due 2023-12-31"`
- Input: `"Cafe\u0301"` (combining accent) → `"Café"` (NFC)

## Testing
- Unit tests: `tests/unit/mcpgateway/plugins/plugins/argument_normalizer/test_argument_normalizer.py`
- Doctests embedded in `argument_normalizer.py` (`_normalize_text` docstring)

Run locally:

```bash
pytest -q tests/unit/mcpgateway/plugins/plugins/argument_normalizer/test_argument_normalizer.py
pytest -q --doctest-modules plugins/argument_normalizer/argument_normalizer.py
```

## Notes
- The plugin is non-blocking and only returns modified payloads when changes occur.
- Date parsing is regex-based and conservative; non-numeric formats are left unchanged.
- If both day and month are ≤ 12, `day_first` controls ambiguity.
- Numeric normalization keeps the last decimal separator and strips other thousands separators.
